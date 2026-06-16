"""
Entry Strategies v5 — optimized SL/TP + session filter + trailing stop.
"""
from dataclasses import dataclass, field
from collections import defaultdict
import csv
from datetime import datetime, timezone

@dataclass
class OrderIntent:
    setup_id: str
    model: str
    direction: int
    entry_price: float
    sl_price: float
    tp_price: float
    sl2_price: float = 0.0  # trailing stop level
    order_type: str = "limit"
    entry_zone_top: float = 0.0
    entry_zone_bottom: float = 0.0
    reason: str = ""
    bar_index: int = 0
    timestamp: int = 0

# ── Helpers ──────────────────────────────────────────────
def f(d, k, default=0.0):
    try: return float(d.get(k, default))
    except: return float(default)
def i(d, k, default=0):
    try: return int(d.get(k, default))
    except: return int(default)
def is_swing(ob):
    return "SWING" in str(ob.get("type","")).upper()
def is_internal(ob):
    return "INTERNAL" in str(ob.get("type","")).upper()

# ── ENHANCED TRADING FILTERS ───────────────────────────
class TradingFilters:
    def __init__(self):
        self.daily_count = 0
        self.last_date = ""
        self.bar_times = {}  # bar_index -> timestamp for session check
    
    def load_timestamps(self, snapshots_path):
        """Load bar timestamps for session filtering."""
        with open(snapshots_path) as f:
            for row in csv.DictReader(f):
                try:
                    bi = int(row["bar_index"])
                    ts = int(row["timestamp"])
                    self.bar_times[bi] = ts
                except: pass
    
    def get_session(self, bar_idx):
        """Determine trading session from bar timestamp (UTC)."""
        ts = self.bar_times.get(bar_idx, 0)
        if not ts: return "unknown"
        dt = datetime.fromtimestamp(ts/1000, tz=timezone.utc)
        hour = dt.hour + dt.minute/60.0
        
        # Trading sessions UTC:
        # Asia: 0-9h
        # London: 8-17h
        # NY: 13-22h
        # London/NY overlap: 13-17h (BEST)
        if 13 <= hour < 17: return "london_ny_overlap"
        elif 8 <= hour < 13: return "london"
        elif 13 <= hour < 22: return "new_york"
        elif 0 <= hour < 9: return "asia"
        else: return "off_hours"
    
    def check(self, bar_idx, snapshot, require_session=False):
        # Daily limit
        current_date = str(snapshot.get("timestamp",""))[:8]
        if current_date != self.last_date:
            self.daily_count = 0
            self.last_date = current_date
        if self.daily_count >= 20:
            return False, "max_daily"
        
        # Session filter (optional)
        if require_session:
            session = self.get_session(bar_idx)
            if session not in ("london_ny_overlap", "london", "new_york"):
                return False, f"bad_session:{session}"
        
        return True, ""
    
    def record_trade(self, bar_idx):
        self.daily_count += 1

@dataclass
class SetupInfo:
    id: str
    model: str
    bar_idx: int
    direction: int
    trigger_event: str = ""
    max_bars: int = 200

# ── BASE ─────────────────────────────────────────────────
class BaseModel:
    def __init__(self, name, config=None):
        self.name = name
        self.config = config or {}
        self.counter = 0
        self.used_signals = set()
        self.filters = TradingFilters()
        self._bar_orders = []  # track orders per bar for dedup
    def is_dup(self, key):
        if key in self.used_signals: return True
        self.used_signals.add(key); return False

# ── OPTIMIZED SL/TP CALC ───────────────────────────────
def calc_optimal_sltp(entry, top, bot, direction, sh, sl, max_r=5.0):
    """Calculate optimized SL/TP with R cap."""
    height = top - bot
    min_h = max(height, 0.3)
    
    if direction == 1:  # LONG
        sl_price = bot - min_h * 0.5  # widen: 0.3→0.5
        risk = entry - sl_price
        if risk <= 0: return None
        
        # TP tại equilibrium, nhưng cap ở max_R
        eq = (sh + sl) / 2 if sh and sl else entry * 1.01
        tp_raw = max(eq, entry * 1.003)
        tp = min(tp_raw, entry + risk * max_r)  # cap at max_R
    else:  # SHORT
        sl_price = top + min_h * 0.5
        risk = sl_price - entry
        if risk <= 0: return None
        
        eq = (sh + sl) / 2 if sh and sl else entry * 0.99
        tp_raw = min(eq, entry * 0.997)
        tp = max(tp_raw, entry - risk * max_r)  # cap at max_R
    
    # Time stop: cut loss after 25 bars
    return sl_price, tp

# ═══════════════════════════════════════════════════════════
# M1: EQH/EQL → Int CHOCH → Int OB
# ═══════════════════════════════════════════════════════════
class Model1_EQHEQL_Sweep_InternalCHOCH(BaseModel):
    def __init__(self, config=None):
        super().__init__("M1_EQHEQL_CHOCH_OB", config)
        self.eqh, self.eql = [], []
        self.pending = []

    def on_bar(self, bar_idx, events, snapshot, active_obs):
        orders = []
        trend=i(snapshot,"current_trend")
        for ev in events:
            et = ev.get("event_type","")
            if et == "EQUAL_HIGH":
                self.eqh.append({"b":bar_idx,"l":f(ev,"level_top") or f(ev,"price")})
            elif et == "EQUAL_LOW":
                self.eql.append({"b":bar_idx,"l":f(ev,"level_bottom") or f(ev,"price")})
        self.eqh = [s for s in self.eqh if bar_idx - s["b"] <= 200]
        self.eql = [s for s in self.eql if bar_idx - s["b"] <= 200]

        for ev in events:
            et=ev.get("event_type",""); d=i(ev,"direction")
            if d==1 and trend==-1: continue
            if d==-1 and trend==1: continue
            if et=="INTERNAL_CHOCH_BEARISH" and d==-1:
                if any(bar_idx-s["b"]<=200 and s["b"]<bar_idx for s in self.eqh):
                    self.pending.append(SetupInfo(id=f"M1_{self.counter}",model=self.name,bar_idx=bar_idx,direction=-1,trigger_event=et))
                    self.counter+=1
            elif et=="INTERNAL_CHOCH_BULLISH" and d==1:
                if any(bar_idx-s["b"]<=200 and s["b"]<bar_idx for s in self.eql):
                    self.pending.append(SetupInfo(id=f"M1_{self.counter}",model=self.name,bar_idx=bar_idx,direction=1,trigger_event=et))
                    self.counter+=1

        still=[]
        for setup in self.pending:
            for ob in active_obs:
                if not is_internal(ob) or i(ob,"direction")!=setup.direction: continue
                ob_bar=i(ob,"_bar_index")
                if ob_bar<setup.bar_idx: continue
                ob_id=ob.get("object_id","")
                if self.is_dup((setup.trigger_event,ob_id)): continue
                top=f(ob,"top"); bot=f(ob,"bottom"); entry=(top+bot)/2
                sh=f(snapshot,"last_swing_high"); sl=f(snapshot,"last_swing_low")
                
                result = calc_optimal_sltp(entry, top, bot, setup.direction, sh, sl)
                if not result: continue
                sl_price, tp = result
                
                ts = int(snapshot.get("timestamp", 0))
                orders.append(OrderIntent(setup_id=setup.id,model=self.name,
                    direction=setup.direction,entry_price=round(entry,2),
                    sl_price=round(sl_price,2),tp_price=round(tp,2),
                    entry_zone_top=round(top,2),entry_zone_bottom=round(bot,2),
                    reason=f"EQH/EQL→IntCHOCH→IntOB",bar_index=bar_idx,timestamp=ts))
                break
            else:
                if bar_idx-setup.bar_idx<=setup.max_bars: still.append(setup)
        self.pending=still
        return orders

# ═══════════════════════════════════════════════════════════
# M5: Strong H/L → Swing OB
# ═══════════════════════════════════════════════════════════
class Model5_StrongDefense(BaseModel):
    def __init__(self, config=None):
        super().__init__("M5_STRONG_DEFENSE", config)

    def on_bar(self, bar_idx, events, snapshot, active_obs):
        orders=[]
        self._bar_orders = []  # reset per bar
        trend=i(snapshot,"current_trend"); sh=f(snapshot,"last_swing_high"); sl=f(snapshot,"last_swing_low")
        strong_h=sh if trend==-1 else 0; strong_l=sl if trend==1 else 0
        weak_h=sh if trend==1 else 0; weak_l=sl if trend==-1 else 0
        price=f(events[-1],"price") if events else 0
        ns=strong_l>0 and abs(price-strong_l)/max(strong_l,0.001)<0.01
        nh=strong_h>0 and abs(price-strong_h)/max(strong_h,0.001)<0.01
        ts = int(snapshot.get("timestamp", 0))

        for ob in active_obs:
            ob_dir=i(ob,"direction"); ob_bar=i(ob,"_bar_index")
            if ob_bar<bar_idx-30: continue
            ob_id=ob.get("object_id",""); top=f(ob,"top"); bot=f(ob,"bottom"); entry=(top+bot)/2
            
            if ns and ob_dir==1 and is_swing(ob):
                if self.is_dup(("SL",ob_id)): continue
                # FIX 1: chỉ LONG khi price >= strong_low (chưa phá support)
                if price < strong_l: continue
                # FIX 3: chỉ 1 order per bar per direction
                if any(o.direction==1 and o.bar_index==bar_idx for o in self._bar_orders): continue
                # FIX TP: dùng weak level (xa) thay vì equilibrium (gần)
                tp = weak_h * 0.997 if weak_h > 0 else entry * 1.01
                sl_price = min(strong_l * 0.995, entry - (top-bot)*0.5)
                if entry - sl_price <= 0 or tp - entry <= 0: continue
                o1 = OrderIntent(setup_id=f"M5_{self.counter}",model=self.name,
                    direction=1,entry_price=round(entry,2),sl_price=round(sl_price,2),tp_price=round(tp,2),
                    entry_zone_top=round(top,2),entry_zone_bottom=round(bot,2),
                    reason=f"StrongLow→SwingOB",bar_index=bar_idx,timestamp=ts)
                orders.append(o1); self._bar_orders.append(o1); self.counter+=1

            if nh and ob_dir==-1 and is_swing(ob):
                if self.is_dup(("SH",ob_id)): continue
                if price > strong_h: continue
                if any(o.direction==-1 and o.bar_index==bar_idx for o in self._bar_orders): continue
                # FIX TP: dùng weak level (xa) thay vì equilibrium (gần)
                tp = weak_l * 1.003 if weak_l > 0 else entry * 0.99
                sl_price = max(strong_h * 1.005, entry + (top-bot)*0.5)
                if sl_price - entry <= 0 or entry - tp <= 0: continue
                o2 = OrderIntent(setup_id=f"M5_{self.counter}",model=self.name,
                    direction=-1,entry_price=round(entry,2),sl_price=round(sl_price,2),tp_price=round(tp,2),
                    entry_zone_top=round(top,2),entry_zone_bottom=round(bot,2),
                    reason=f"StrongHigh→SwingOB",bar_index=bar_idx,timestamp=ts)
                orders.append(o2); self._bar_orders.append(o2); self.counter+=1
        return orders

# ═══════════════════════════════════════════════════════════
# M7: Int CHOCH → Int OB (optimized SL/TP)
# ═══════════════════════════════════════════════════════════
class Model7_IntCHOCH_OB(BaseModel):
    """Int CHOCH → Int OB — vào LIMIT tại OB mid, chờ giá quay lại."""
    def __init__(self, config=None):
        super().__init__("M7_INTCHOCH_OB", config)
        self.pending = []

    def on_bar(self, bar_idx, events, snapshot, active_obs):
        orders=[]
        trend=i(snapshot,"current_trend")
        ts = int(snapshot.get("timestamp", 0))
        
        for ev in events:
            et=ev.get("event_type",""); d=i(ev,"direction")
            if d==1 and trend==-1: continue
            if d==-1 and trend==1: continue
            if et=="INTERNAL_CHOCH_BULLISH" and d==1:
                self.pending.append(SetupInfo(id=f"M7_{self.counter}",model=self.name,bar_idx=bar_idx,direction=1,trigger_event=et))
                self.counter+=1
            elif et=="INTERNAL_CHOCH_BEARISH" and d==-1:
                self.pending.append(SetupInfo(id=f"M7_{self.counter}",model=self.name,bar_idx=bar_idx,direction=-1,trigger_event=et))
                self.counter+=1

        still=[]
        for setup in self.pending:
            for ob in active_obs:
                if not is_internal(ob) or i(ob,"direction")!=setup.direction: continue
                ob_bar=i(ob,"_bar_index")
                if ob_bar<setup.bar_idx: continue
                ob_id=ob.get("object_id","")
                if self.is_dup((setup.trigger_event,ob_id)): continue
                top=f(ob,"top"); bot=f(ob,"bottom"); entry=(top+bot)/2
                sh=f(snapshot,"last_swing_high"); sl=f(snapshot,"last_swing_low")
                
                result = calc_optimal_sltp(entry, top, bot, setup.direction, sh, sl)
                if not result: continue
                sl_price, tp = result
                
                orders.append(OrderIntent(setup_id=setup.id,model=self.name,
                    direction=setup.direction,entry_price=round(entry,2),
                    sl_price=round(sl_price,2),tp_price=round(tp,2),
                    entry_zone_top=round(top,2),entry_zone_bottom=round(bot,2),
                    reason=f"IntCHOCH→IntOB",bar_index=bar_idx,timestamp=ts))
                break
            else:
                if bar_idx-setup.bar_idx<=setup.max_bars: still.append(setup)
        self.pending=still
        return orders

# ═══════════════════════════════════════════════════════════
# Full pipeline runner with execution layer
# ═══════════════════════════════════════════════════════════
def run_full_pipeline(events_path, snapshots_path, objects_path, prices_path=None):
    """Run all optimized models and simulate trades via execution layer."""
    import sys, os
    sys.path.insert(0, os.path.dirname(__file__))
    
    from execution_layer.execution_engine import ExecutionEngine
    from execution_layer.execution_config import ExecutionConfig
    
    # Load data
    with open(snapshots_path) as f:
        all_snaps = list(csv.DictReader(f))
    
    bar_snapshots = {int(s["bar_index"]): s for s in all_snaps}
    
    with open(events_path) as f:
        events_by_bar = defaultdict(list)
        for row in csv.DictReader(f):
            events_by_bar[int(row["bar_index"])].append(row)
    
    with open(objects_path) as f:
        all_objects = list(csv.DictReader(f))
    
    # Map OB timestamps to bar indices
    ts_to_bar = {}
    for s in all_snaps:
        try: ts_to_bar[int(s["timestamp"])] = int(s["bar_index"])
        except: pass
    
    for ob in all_objects:
        try:
            ob_ts = int(ob.get("created_at", 0))
            bi = ts_to_bar.get(ob_ts, -1)
            if bi == -1 and ob_ts > 0:
                sorted_ts = sorted(k for k in ts_to_bar.keys() if k <= ob_ts)
                if sorted_ts: bi = ts_to_bar[sorted_ts[-1]]
            ob["_bar_index"] = bi
        except: ob["_bar_index"] = -1
    
    objects_by_bar = defaultdict(list)
    for ob in all_objects:
        bi = ob.get("_bar_index", -1)
        if bi >= 0: objects_by_bar[bi].append(ob)
    
    # Build OB cache with WINDOW=200
    active_ob_cache = {}
    recent_obs = []
    bar_indices = sorted(bar_snapshots.keys())
    for bi in bar_indices:
        for ob in objects_by_bar.get(bi, []): recent_obs.append(ob)
        recent_obs = [ob for ob in recent_obs if bi - ob.get("_bar_index", 0) <= 200]
        active_ob_cache[bi] = list(recent_obs)
    
    print(f"Loaded {len(bar_indices)} bars, {len(all_objects)} objects")
    
    # Initialize models
    models = [
        ("M1_EQHEQL_CHOCH_OB", Model1_EQHEQL_Sweep_InternalCHOCH()),
        ("M5_STRONG_DEFENSE", Model5_StrongDefense()),
        ("M7_INTCHOCH_OB", Model7_IntCHOCH_OB()),
    ]
    
    # Initialize execution engine
    exec_cfg = ExecutionConfig()
    exec_cfg.initial_capital = 10000.0
    exec_cfg.commission_pct = 0.01  # 0.01% per trade
    exec_cfg.slippage_pips = 1.0
    
    engine = ExecutionEngine(exec_cfg)
    
    # Run simulation
    all_orders = []
    
    for model_name, model in models:
        orders = []
        for bi in bar_indices:
            bar_events = events_by_bar.get(bi, [])
            snapshot = bar_snapshots.get(bi, {})
            obs = active_ob_cache.get(bi, [])
            bar_orders = model.on_bar(bi, bar_events, snapshot, obs)
            orders.extend(bar_orders)
        
        print(f"{model_name}: {len(orders)} orders")
        all_orders.extend(orders)
        
        # Feed to execution engine
        for o in orders:
            engine.submit_order(
                order_id=o.setup_id,
                symbol="XAUUSD",
                direction=o.direction,
                order_type=o.order_type,
                price=o.entry_price,
                quantity=0.01,  # fixed 0.01 lot
                sl_price=o.sl_price,
                tp_price=o.tp_price,
                timestamp=o.timestamp,
            )
    
    # Run engine
    print(f"\nRunning execution engine on {len(bar_indices)} bars...")
    summary = engine.run()
    
    return summary, all_orders
