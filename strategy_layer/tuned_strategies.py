#!/usr/bin/env python3
"""
Tuned Strategy Models — variants aiming for WR ≥ 65% + ≥ 3 orders/week.

Variants:
  V1  M5 Extended — accept internal OB + swing OB, min TP = 1.5R
  V2  M7 Filtered — session(London/NY) + volatility + premium/discount + trend
  V3  M7 Strict — only swing-level OB + all filters
  V4  Combined — M5 signals + M7 strong signals
  V5  Int BOS + OB (M1-like but at swing) + session filter

All return OrderIntent[] same as existing models.
"""
from dataclasses import dataclass, field
from collections import defaultdict
from strategy_layer.entry_strategies import (
    BaseModel, OrderIntent, calc_optimal_sltp, TradingFilters,
    f, i, is_swing, is_internal,
)

# ── Universal filters ────────────────────────────────────
def in_session(timestamp, sessions=("london", "london_ny", "ny")):
    """Check bar timestamp against UTC trading sessions."""
    from datetime import datetime, timezone
    dt = datetime.fromtimestamp(timestamp / 1000, tz=timezone.utc)
    hr = dt.hour + dt.minute / 60.0
    if "london_ny" in sessions and 13 <= hr < 17: return True
    if "london" in sessions and 8 <= hr < 13: return True
    if "ny" in sessions and 13 <= hr < 22: return True
    if "asia" in sessions and 0 <= hr < 9: return True
    return False

def has_volatility(snapshot, min_atr=10):
    """Check if ATR > threshold. snapshot['active_ob_count'] used as vol proxy."""
    vol = float(snapshot.get("active_ob_count", 0))
    return vol >= min_atr

def in_discount_zone(snapshot, direction):
    """For LONG: price should be in discount zone. For SHORT: in premium zone."""
    if direction == 1:
        return snapshot.get("in_discount", "False") == "True"
    else:
        return snapshot.get("in_premium", "False") == "True"

# ═══════════════════════════════════════════════════════════
# V1: M5 Extended — accept swing AND internal OB, min TP
# ═══════════════════════════════════════════════════════════
class V1_M5_Extended(BaseModel):
    """M5 Strong Defense but also accept internal OB + min TP = 1.5R."""
    def __init__(self, config=None):
        super().__init__("V1_M5_EXTENDED", config)
        self.pending = []
    
    def on_bar(self, bar_idx, events, snapshot, active_obs):
        orders = []
        trend = i(snapshot, "current_trend")
        sh = f(snapshot, "last_swing_high")
        sl = f(snapshot, "last_swing_low")
        ts = int(snapshot.get("timestamp", 0))
        
        for ob in active_obs:
            if i(ob, "direction") == 0: continue
            direction = i(ob, "direction")
            
            # Trend filter
            if direction == 1 and trend == -1: continue
            if direction == -1 and trend == 1: continue
            
            # Accept swing AND internal OB (M5 originally only swing)
            # But require session filter
            if not in_session(ts): continue
            
            top = f(ob, "top"); bot = f(ob, "bottom")
            height = top - bot
            if height <= 0: continue
            
            entry = top if direction == 1 else bot
            sl_price = bot - height * 0.5 if direction == 1 else top + height * 0.5
            
            # Min R-based TP: at least 1.5R
            risk = abs(entry - sl_price)
            if risk <= 0.01: continue
            
            eq = (sh + sl) / 2 if sh and sl else entry * 1.005
            if direction == 1:
                tp_raw = max(eq, entry + risk * 1.5)
            else:
                tp_raw = min(eq, entry - risk * 1.5)
            
            tp = min(tp_raw, entry + risk * 5) if direction == 1 else max(tp_raw, entry - risk * 5)
            
            oid = ob.get("object_id", "")
            if self.is_dup(("V1", oid)): continue
            
            orders.append(OrderIntent(
                setup_id=f"V1_{self.counter}", model=self.name,
                direction=direction,
                entry_price=round(entry, 2), sl_price=round(sl_price, 2),
                tp_price=round(tp, 2),
                entry_zone_top=round(top, 2), entry_zone_bottom=round(bot, 2),
                reason=f"V1_M5x_bar{bar_idx}", bar_index=bar_idx, timestamp=ts,
            ))
            self.counter += 1
        
        return orders


# ═══════════════════════════════════════════════════════════
# V2a-d: M7 Filtered variants — different volatility thresholds
# ═══════════════════════════════════════════════════════════
class V2_M7_Filtered(BaseModel):
    """M7 + trend + volatility(>=n). Base class used by variants."""
    MIN_VOL = 4  # override in subclass
    
    def __init__(self, config=None):
        super().__init__("V2_M7_FILTERED", config)
        self.pending = []
    
    def on_bar(self, bar_idx, events, snapshot, active_obs):
        orders = []
        trend = i(snapshot, "current_trend")
        sh = f(snapshot, "last_swing_high")
        sl = f(snapshot, "last_swing_low")
        ts = int(snapshot.get("timestamp", 0))
        
        if not has_volatility(snapshot, self.MIN_VOL): return []
        
        for ev in events:
            et = ev.get("event_type", ""); d = i(ev, "direction")
            if d == 0: continue
            if d == 1 and trend == -1: continue
            if d == -1 and trend == 1: continue
            
            if et in ("INTERNAL_CHOCH_BEARISH", "CHOCH_BEARISH") and d == -1:
                self.pending.append((f"{self.name}_{self.counter}", bar_idx, -1, et, sh, sl, ts))
                self.counter += 1
            elif et in ("INTERNAL_CHOCH_BULLISH", "CHOCH_BULLISH") and d == 1:
                self.pending.append((f"{self.name}_{self.counter}", bar_idx, 1, et, sh, sl, ts))
                self.counter += 1
        
        still = []
        for sid, sbi, sdir, sete, ssh, ssl, sts in self.pending:
            for ob in active_obs:
                if not is_internal(ob) or i(ob, "direction") != sdir: continue
                ob_bar = i(ob, "_bar_index", -1)
                if ob_bar < sbi: continue
                oid = ob.get("object_id", "")
                if self.is_dup((self.name, sete, oid)): continue
                
                top = f(ob, "top"); bot = f(ob, "bottom")
                height = max(top - bot, 0.3)
                entry = (top + bot) / 2
                
                if sdir == 1:
                    sl_price = bot - height * 0.5
                else:
                    sl_price = top + height * 0.5
                
                risk = abs(entry - sl_price)
                if risk <= 0.01: continue
                
                eq = (ssh + ssl) / 2 if ssh and ssl else entry * 1.005
                tp = min(eq, entry + risk * 5) if sdir == 1 else max(eq, entry - risk * 5)
                
                orders.append(OrderIntent(
                    setup_id=sid, model=self.name,
                    direction=sdir, entry_price=round(entry, 2),
                    sl_price=round(sl_price, 2), tp_price=round(tp, 2),
                    entry_zone_top=round(top, 2), entry_zone_bottom=round(bot, 2),
                    reason="V2_IntCHOCH→IntOB", bar_index=bar_idx, timestamp=sts,
                ))
                break
            else:
                if bar_idx - sbi <= 200: still.append((sid, sbi, sdir, sete, ssh, ssl, sts))
        self.pending = still
        return orders

class V2a_Vol6(V2_M7_Filtered):
    MIN_VOL = 6
    def __init__(self): super().__init__(); self.name = "V2A_VOL6"

class V2b_Vol8(V2_M7_Filtered):
    MIN_VOL = 8
    def __init__(self): super().__init__(); self.name = "V2B_VOL8"

class V2c_VolSwing(V2_M7_Filtered):
    """Vol=4 + only swing OBs"""
    MIN_VOL = 4
    def __init__(self): super().__init__(); self.name = "V2C_SWINGOB"
    def on_bar(self, bar_idx, events, snapshot, active_obs):
        orders = []
        trend = i(snapshot, "current_trend")
        sh = f(snapshot, "last_swing_high")
        sl = f(snapshot, "last_swing_low")
        ts = int(snapshot.get("timestamp", 0))
        if not in_session(ts): return []
        if not has_volatility(snapshot, self.MIN_VOL): return []
        for ev in events:
            et = ev.get("event_type", ""); d = i(ev, "direction")
            if d == 0: continue
            if d == 1 and trend == -1: continue
            if d == -1 and trend == 1: continue
            if et in ("INTERNAL_CHOCH_BEARISH", "CHOCH_BEARISH") and d == -1:
                self.pending.append((f"{self.name}_{self.counter}", bar_idx, -1, et, sh, sl, ts))
                self.counter += 1
            elif et in ("INTERNAL_CHOCH_BULLISH", "CHOCH_BULLISH") and d == 1:
                self.pending.append((f"{self.name}_{self.counter}", bar_idx, 1, et, sh, sl, ts))
                self.counter += 1
        still = []
        for sid, sbi, sdir, sete, ssh, ssl, sts in self.pending:
            for ob in active_obs:
                if not is_swing(ob) or i(ob, "direction") != sdir: continue
                ob_bar = i(ob, "_bar_index", -1)
                if ob_bar < sbi: continue
                oid = ob.get("object_id", "")
                if self.is_dup((self.name, sete, oid)): continue
                top = f(ob, "top"); bot = f(ob, "bottom")
                height = max(top - bot, 0.3)
                entry = (top + bot) / 2
                if sdir == 1: sl_price = bot - height * 0.5
                else: sl_price = top + height * 0.5
                risk = abs(entry - sl_price)
                if risk <= 0.01: continue
                eq = (ssh + ssl) / 2 if ssh and ssl else entry * 1.005
                tp = min(eq, entry + risk * 5) if sdir == 1 else max(eq, entry - risk * 5)
                orders.append(OrderIntent(setup_id=sid, model=self.name, direction=sdir,
                    entry_price=round(entry,2), sl_price=round(sl_price,2), tp_price=round(tp,2),
                    entry_zone_top=round(top,2), entry_zone_bottom=round(bot,2),
                    reason="V2C_SwingCHOCH→SwingOB", bar_index=bar_idx, timestamp=sts))
                break
            else:
                if bar_idx - sbi <= 200: still.append((sid, sbi, sdir, sete, ssh, ssl, sts))
        self.pending = still
        return orders

class V2d_Vol8Session(V2_M7_Filtered):
    """Vol>=8 + London/NY session only"""
    MIN_VOL = 8
    def __init__(self): super().__init__(); self.name = "V2D_VOL8SES"
    def on_bar(self, bar_idx, events, snapshot, active_obs):
        ts = int(snapshot.get("timestamp", 0))
        if not in_session(ts): return []
        return super().on_bar(bar_idx, events, snapshot, active_obs)

class V2e_Vol10(V2_M7_Filtered):
    """Vol>=10"""
    MIN_VOL = 10
    def __init__(self): super().__init__(); self.name = "V2E_VOL10"

class V2f_Vol6Session(V2_M7_Filtered):
    """Vol>=6 + London/NY session only"""
    MIN_VOL = 6
    def __init__(self): super().__init__(); self.name = "V2F_VOL6SES"
    def on_bar(self, bar_idx, events, snapshot, active_obs):
        ts = int(snapshot.get("timestamp", 0))
        if not in_session(ts): return []
        return super().on_bar(bar_idx, events, snapshot, active_obs)

class V2g_Vol4Session(V2_M7_Filtered):
    """Vol>=4 + London/NY session only"""
    MIN_VOL = 4
    def __init__(self): super().__init__(); self.name = "V2G_VOL4SES"
    def on_bar(self, bar_idx, events, snapshot, active_obs):
        ts = int(snapshot.get("timestamp", 0))
        if not in_session(ts): return []
        return super().on_bar(bar_idx, events, snapshot, active_obs)


# ═══════════════════════════════════════════════════════════
# V3: M7 Strict — ONLY swing-level OB (stronger structure)
# ═══════════════════════════════════════════════════════════
class V3_M7_SwingOB(BaseModel):
    """Like M7 but only accepts SWING OBs (not internal)."""
    def __init__(self, config=None):
        super().__init__("V3_M7_SWINGOB", config)
        self.pending = []
    
    def on_bar(self, bar_idx, events, snapshot, active_obs):
        orders = []
        trend = i(snapshot, "current_trend")
        sh = f(snapshot, "last_swing_high")
        sl = f(snapshot, "last_swing_low")
        ts = int(snapshot.get("timestamp", 0))
        
        if not in_session(ts, ("london_ny", "london")): return []
        
        for ev in events:
            et = ev.get("event_type", ""); d = i(ev, "direction")
            if d == 0: continue
            if d == 1 and trend == -1: continue
            if d == -1 and trend == 1: continue
            
            if et in ("INTERNAL_CHOCH_BEARISH", "CHOCH_BEARISH") and d == -1:
                self.pending.append((f"V3_{self.counter}", bar_idx, -1, et, sh, sl, ts))
                self.counter += 1
            elif et in ("INTERNAL_CHOCH_BULLISH", "CHOCH_BULLISH") and d == 1:
                self.pending.append((f"V3_{self.counter}", bar_idx, 1, et, sh, sl, ts))
                self.counter += 1
        
        still = []
        for sid, sbi, sdir, sete, ssh, ssl, sts in self.pending:
            for ob in active_obs:
                if not is_swing(ob) or i(ob, "direction") != sdir: continue
                ob_bar = i(ob, "_bar_index", -1)
                if ob_bar < sbi: continue
                oid = ob.get("object_id", "")
                if self.is_dup(("V3", sete, oid)): continue
                
                top = f(ob, "top"); bot = f(ob, "bottom")
                height = max(top - bot, 0.3)
                entry = top if sdir == 1 else bot
                
                if sdir == 1:
                    sl_price = bot - height * 0.5
                else:
                    sl_price = top + height * 0.5
                
                risk = abs(entry - sl_price)
                if risk <= 0.01: continue
                
                eq = (ssh + ssl) / 2 if ssh and ssl else entry * 1.005
                if sdir == 1:
                    tp = max(eq, entry + risk * 1.5)
                else:
                    tp = min(eq, entry - risk * 1.5)
                tp = min(tp, entry + risk * 5) if sdir == 1 else max(tp, entry - risk * 5)
                
                orders.append(OrderIntent(
                    setup_id=sid, model=self.name,
                    direction=sdir, entry_price=round(entry, 2),
                    sl_price=round(sl_price, 2), tp_price=round(tp, 2),
                    entry_zone_top=round(top, 2), entry_zone_bottom=round(bot, 2),
                    reason=f"V3_SwingCHOCH→SwingOB", bar_index=bar_idx, timestamp=sts,
                ))
                break
            else:
                if bar_idx - sbi <= 200:
                    still.append((sid, sbi, sdir, sete, ssh, ssl, sts))
        self.pending = still
        return orders


# ═══════════════════════════════════════════════════════════
# V4: EQH/EQL + Swing OB (M1 at swing level)
# ═══════════════════════════════════════════════════════════
class V4_EQHEQL_SwingOB(BaseModel):
    """EQH/EQL sweep → Swing CHOCH → Swing OB. Stricter structure."""
    def __init__(self, config=None):
        super().__init__("V4_EQHEQL_SWINGOB", config)
        self.eqh, self.eql = [], []
        self.pending = []
    
    def on_bar(self, bar_idx, events, snapshot, active_obs):
        orders = []
        trend = i(snapshot, "current_trend")
        sh = f(snapshot, "last_swing_high")
        sl = f(snapshot, "last_swing_low")
        ts = int(snapshot.get("timestamp", 0))
        
        if not in_session(ts, ("london_ny", "london")): return []
        if not has_volatility(snapshot, 5): return []
        
        for ev in events:
            et = ev.get("event_type", "")
            if et == "EQUAL_HIGH":
                self.eqh.append({"b": bar_idx, "l": f(ev, "level_top") or f(ev, "price")})
            elif et == "EQUAL_LOW":
                self.eql.append({"b": bar_idx, "l": f(ev, "level_bottom") or f(ev, "price")})
        self.eqh = [s for s in self.eqh if bar_idx - s["b"] <= 200]
        self.eql = [s for s in self.eql if bar_idx - s["b"] <= 200]
        
        for ev in events:
            et = ev.get("event_type", ""); d = i(ev, "direction")
            if d == 0: continue
            if d == 1 and trend == -1: continue
            if d == -1 and trend == 1: continue
            
            if et == "CHOCH_BEARISH" and d == -1:
                if any(bar_idx - s["b"] <= 200 and s["b"] < bar_idx for s in self.eqh):
                    self.pending.append((f"V4_{self.counter}", bar_idx, -1, "CHOCH_BEARISH", sh, sl, ts))
                    self.counter += 1
            elif et == "CHOCH_BULLISH" and d == 1:
                if any(bar_idx - s["b"] <= 200 and s["b"] < bar_idx for s in self.eql):
                    self.pending.append((f"V4_{self.counter}", bar_idx, 1, "CHOCH_BULLISH", sh, sl, ts))
                    self.counter += 1
        
        still = []
        for sid, sbi, sdir, sete, ssh, ssl, sts in self.pending:
            for ob in active_obs:
                if not is_swing(ob) or i(ob, "direction") != sdir: continue
                ob_bar = i(ob, "_bar_index", -1)
                if ob_bar < sbi: continue
                oid = ob.get("object_id", "")
                if self.is_dup(("V4", sete, oid)): continue
                
                top = f(ob, "top"); bot = f(ob, "bottom")
                height = max(top - bot, 0.3)
                entry = (top + bot) / 2
                
                if sdir == 1:
                    sl_price = bot - height * 0.5
                else:
                    sl_price = top + height * 0.5
                
                risk = abs(entry - sl_price)
                if risk <= 0.01: continue
                
                eq = (ssh + ssl) / 2 if ssh and ssl else entry * 1.005
                if sdir == 1:
                    tp = max(eq, entry + risk * 1.5)
                else:
                    tp = min(eq, entry - risk * 1.5)
                tp = min(tp, entry + risk * 5) if sdir == 1 else max(tp, entry - risk * 5)
                
                orders.append(OrderIntent(
                    setup_id=sid, model=self.name,
                    direction=sdir, entry_price=round(entry, 2),
                    sl_price=round(sl_price, 2), tp_price=round(tp, 2),
                    entry_zone_top=round(top, 2), entry_zone_bottom=round(bot, 2),
                    reason=f"V4_EQHEQL→SwingCHOCH→SwingOB", bar_index=bar_idx, timestamp=sts,
                ))
                break
            else:
                if bar_idx - sbi <= 200:
                    still.append((sid, sbi, sdir, sete, ssh, ssl, sts))
        self.pending = still
        return orders


# ═══════════════════════════════════════════════════════════
# V8: Combined — V2D (M7 filter vol8+session) + M5 (swing OB)
# ═══════════════════════════════════════════════════════════
class V8_Combined(BaseModel):
    """Meta-model: kết hợp V2D (CHOCH + Int OB + vol≥8 + session) và M5 (swing OB + trend).
    
    Chiến lược:
    1. Core: M5 rule — entry at swing OB, trend filter, SL at OB-0.5H, TP at equilibrium
    2. Supplemental: V2D rule — Int CHOCH → Int OB, vol≥8, session(London/NY), original TP
    """
    def __init__(self, config=None):
        super().__init__("V8_COMBINED", config)
        self.pending = []
    
    def on_bar(self, bar_idx, events, snapshot, active_obs):
        orders = []
        trend = i(snapshot, "current_trend")
        sh = f(snapshot, "last_swing_high")
        sl = f(snapshot, "last_swing_low")
        ts = int(snapshot.get("timestamp", 0))
        vol = float(snapshot.get("active_ob_count", 0))
        
        # ── Rule 1: M5 — enter at swing OB in trend direction ──
        for ob in active_obs:
            if not is_swing(ob): continue
            direction = i(ob, "direction")
            if direction == 0: continue
            if direction == 1 and trend == -1: continue
            if direction == -1 and trend == 1: continue
            
            oid = ob.get("object_id", "")
            if not oid or self.is_dup(("V8_M5", oid)): continue
            
            top = f(ob, "top"); bot = f(ob, "bottom")
            if top <= 0 or bot <= 0: continue
            height = max(top - bot, 0.3)
            
            entry = top if direction == 1 else bot
            if direction == 1:
                sl_price = bot - height * 0.5
            else:
                sl_price = top + height * 0.5
            
            risk = abs(entry - sl_price)
            if risk <= 0.01: continue
            
            eq = (sh + sl) / 2 if sh and sl else entry * 1.005
            tp = min(eq, entry + risk * 5) if direction == 1 else max(eq, entry - risk * 5)
            
            orders.append(OrderIntent(setup_id=f"V8_M5_{self.counter}", model=self.name,
                direction=direction, entry_price=round(entry,2), sl_price=round(sl_price,2),
                tp_price=round(tp,2), entry_zone_top=round(top,2), entry_zone_bottom=round(bot,2),
                reason="V8_M5_StrongOB", bar_index=bar_idx, timestamp=ts))
            self.counter += 1
        
        # ── Rule 2: V2D — Int CHOCH → Int OB, vol≥8 + session ──
        if vol >= 8 and in_session(ts):
            for ev in events:
                et = ev.get("event_type", ""); d = i(ev, "direction")
                if d == 0: continue
                if d == 1 and trend == -1: continue
                if d == -1 and trend == 1: continue
                if et in ("INTERNAL_CHOCH_BEARISH", "CHOCH_BEARISH") and d == -1:
                    self.pending.append((f"V8_V2D_{self.counter}", bar_idx, -1, et, sh, sl, ts))
                    self.counter += 1
                elif et in ("INTERNAL_CHOCH_BULLISH", "CHOCH_BULLISH") and d == 1:
                    self.pending.append((f"V8_V2D_{self.counter}", bar_idx, 1, et, sh, sl, ts))
                    self.counter += 1
        
        still = []
        for sid, sbi, sdir, sete, ssh, ssl, sts in self.pending:
            for ob in active_obs:
                if not is_internal(ob) or i(ob, "direction") != sdir: continue
                ob_bar = i(ob, "_bar_index", -1)
                if ob_bar < sbi: continue
                oid = ob.get("object_id", "")
                if self.is_dup(("V8_V2D", sete, oid)): continue
                
                top = f(ob, "top"); bot = f(ob, "bottom")
                height = max(top - bot, 0.3)
                entry = (top + bot) / 2
                if sdir == 1: sl_price = bot - height * 0.5
                else: sl_price = top + height * 0.5
                risk = abs(entry - sl_price)
                if risk <= 0.01: continue
                eq = (ssh + ssl) / 2 if ssh and ssl else entry * 1.005
                tp = min(eq, entry + risk * 5) if sdir == 1 else max(eq, entry - risk * 5)
                orders.append(OrderIntent(setup_id=sid, model=self.name, direction=sdir,
                    entry_price=round(entry,2), sl_price=round(sl_price,2), tp_price=round(tp,2),
                    entry_zone_top=round(top,2), entry_zone_bottom=round(bot,2),
                    reason="V8_V2D_IntCHOCH→IntOB", bar_index=bar_idx, timestamp=sts))
                break
            else:
                if bar_idx - sbi <= 200: still.append((sid, sbi, sdir, sete, ssh, ssl, sts))
        self.pending = still
        
        return orders
