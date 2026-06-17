#!/usr/bin/env python3
"""
Research Loop — SuperTrend AI LuxAlgo
Mỗi experiment: hypothesis → implement → backtest → diagnose → modify → repeat
Output đầy đủ metrics, breakdown, diagnosis.
"""
import os, sys, csv, time, json
import numpy as np
import pandas as pd
from backtesting import Backtest, Strategy
from collections import defaultdict
from datetime import datetime

os.makedirs("output", exist_ok=True)
DATA = "D:/Back test/Dukascopy/processed/XAUUSD_15m.parquet"
DATA_1H = "D:/Back test/Dukascopy/processed/XAUUSD_1h.parquet"
DATA_4H = "D:/Back test/Dukascopy/processed/XAUUSD_4h.parquet"
BARS = 10000
LOG_FILE = "EXPERIMENT_LOG.md"

# ── Data loader ───────────────────────────────────────────────
def load(bars=BARS, tf='15m'):
    path = DATA if tf == '15m' else (DATA_1H if tf == '1h' else DATA_4H)
    df = pd.read_parquet(path).tail(bars).copy()
    df.rename(columns={"timestamp_utc": "Date", "open": "Open", "high": "High",
                        "low": "Low", "close": "Close"}, inplace=True)
    df["Date"] = pd.to_datetime(df["Date"])
    df.set_index("Date", inplace=True)
    return df


# ── SuperTrend AI ─────────────────────────────────────────────
def stai(high, low, close, length=10, min_f=0.5, max_f=2.0, step=0.5,
         perf_alpha=10, cluster='best'):
    """
    Full LuxAlgo SuperTrend AI spec.
    Returns: ts (trailing stop), os (1=up, 0=down)
    """
    n = len(close); hl2 = (high+low)/2
    factors = np.arange(max(min_f,0.5), max_f+step/2, step)
    nf = len(factors)
    if nf < 2: return np.full(n,np.nan), np.zeros(n,dtype=int)

    tr = np.zeros(n)
    tr[1:] = np.maximum(high[1:]-low[1:], np.maximum(np.abs(high[1:]-close[:-1]), np.abs(low[1:]-close[:-1])))
    atr = pd.Series(tr).ewm(span=length, adjust=False).mean().values

    upper = np.zeros((nf,n)); lower = np.zeros((nf,n))
    trend = np.zeros((nf,n), dtype=np.int8); out = np.zeros((nf,n))
    perf = np.zeros((nf,n)); alpha = 2/(perf_alpha+1)

    for k in range(nf):
        f=factors[k]; up=hl2+atr*f; dn=hl2-atr*f
        u=upper[k]; lo=lower[k]; t=trend[k]; o=out[k]; p=perf[k]
        u[0],lo[0]=up[0],dn[0]; t[0]=1 if close[0]>u[0] else 0; o[0]=lo[0] if t[0]==1 else u[0]
        for i in range(1,n):
            if u[i-1]==0:
                u[i]=up[i]; lo[i]=dn[i]; t[i]=1 if close[i]>u[i] else 0; o[i]=lo[i] if t[i]==1 else u[i]; continue
            t[i]=1 if close[i]>u[i-1] else (0 if close[i]<lo[i-1] else t[i-1])
            u[i]=min(up[i],u[i-1]) if close[i-1]<u[i-1] else up[i]
            lo[i]=max(dn[i],lo[i-1]) if close[i-1]>lo[i-1] else dn[i]
            o[i]=lo[i] if t[i]==1 else u[i]
            if i>=2 and o[i-1]!=0:
                p[i]=p[i-1]+alpha*((close[i]-close[i-1])*np.sign(close[i-1]-o[i-1])-p[i-1])

    pl=perf[:,-1]; valid=~np.isnan(pl)&(pl!=0)
    if valid.sum()<2: return np.full(n,np.nan), np.zeros(n,dtype=int)

    vp=pl[valid]; vf=factors[valid]; sp=np.sort(vp)
    cents=np.array([np.percentile(sp,25),np.percentile(sp,50),np.percentile(sp,75)])
    labels=np.zeros(len(vp),dtype=int)
    for _ in range(50):
        old=cents.copy()
        for i,pv in enumerate(vp): labels[i]=np.argmin(np.abs(cents-pv))
        for c in range(3):
            m=labels==c; cents[c]=vp[m].mean() if m.sum()>0 else cents[c]
        if np.allclose(old,cents,1e-10): break

    cl_map={'best':2,'avg':1,'worst':0}; ci=cl_map.get(cluster,2)
    cl_mask=labels==min(ci,2); tf=vf[cl_mask].mean() if cl_mask.sum()>0 else vf.mean()

    up_f=hl2+atr*tf; dn_f=hl2-atr*tf
    u=np.zeros(n); l=np.zeros(n); t=np.zeros(n,dtype=int)
    ts=np.zeros(n); os=np.zeros(n,dtype=int)
    u[0],l[0]=up_f[0],dn_f[0]
    for i in range(1,n):
        if u[i-1]==0: u[i]=up_f[i]; l[i]=dn_f[i]; t[i]=1 if close[i]>u[i] else 0
        else:
            t[i]=1 if close[i]>u[i-1] else (0 if close[i]<l[i-1] else t[i-1])
            u[i]=min(up_f[i],u[i-1]) if close[i-1]<u[i-1] else up_f[i]
            l[i]=max(dn_f[i],l[i-1]) if close[i-1]>l[i-1] else dn_f[i]
        ts[i]=l[i] if t[i]==1 else u[i]; os[i]=t[i]
    ts[ts==0]=np.nan
    return ts, os


# ── Feature builders ──────────────────────────────────────────
def build_features(df, cfg=None):
    """Xây dựng causal features từ OHLC."""
    h, l, c = df['High'].values, df['Low'].values, df['Close'].values
    features = {}
    cfg = cfg or {}

    # ATR
    tr = np.zeros(len(c))
    tr[1:] = np.maximum(h[1:]-l[1:], np.maximum(np.abs(h[1:]-c[:-1]), np.abs(l[1:]-c[:-1])))
    atr_len = cfg.get('atr_len', 14)
    features['atr14'] = pd.Series(tr).rolling(atr_len).mean().values

    # RSI
    delta = pd.Series(c).diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = gain / loss.replace(0, np.nan)
    features['rsi14'] = 100 - (100 / (1 + rs)).values

    # EMA
    features['ema20'] = pd.Series(c).ewm(span=20).mean().values
    features['ema50'] = pd.Series(c).ewm(span=50).mean().values

    # Volatility ratio
    features['vol_ratio'] = (pd.Series(tr).rolling(50).mean() / pd.Series(tr).rolling(200).mean()).values

    # Session
    features['hour'] = df.index.hour + df.index.minute/60

    # SuperTrust AI (with config params)
    ts, os_sig = stai(h, l, c,
                       length=cfg.get('atr_len', 10),
                       min_f=cfg.get('min_mult', 0.5),
                       max_f=cfg.get('max_mult', 2.0),
                       step=cfg.get('step', 0.5),
                       perf_alpha=cfg.get('perf_alpha', 10),
                       cluster=cfg.get('cluster', 'best'))
    features['st_ts'] = ts
    features['st_os'] = os_sig

    return features


# ── Experiment runner ─────────────────────────────────────────
def run_experiment(config: dict, bars=BARS, tf='15m') -> dict:
    """
    Chạy 1 experiment với config.
    Returns: dict metrics + breakdowns
    """
    df = load(bars, tf)
    # Update session bounds based on TF
    if tf == '1h':
        pass  # session giống M15
    features = build_features(df, config)

    # ── Strategy class ──
    entry_type = config.get('entry', 'cross')

    class S(Strategy):
        def init(self):
            self.ts = self.I(lambda: features['st_ts'], name='ST', overlay=True)
            self.os = self.I(lambda: features['st_os'], name='OS', overlay=False)
            if entry_type == 'pullback_ma':
                self.ema20 = self.I(lambda: features['ema20'], name='EMA20', overlay=True)

        def _atr(self):
            return features['atr14'][len(self.data)-1]

        def next(self):
            i = len(self.data)-1
            if i < 30: return
            os_c = int(features['st_os'][i])
            p = float(df['Close'].values[i]) if i < len(df) else self.data.Close[-1]
            atr = features['atr14'][i]
            rsi = features['rsi14'][i]
            hr = features['hour'][i]
            vol = features['vol_ratio'][i]

            # Filters
            if config.get('session', False) and not (config['s_start'] <= hr < config['s_end']): return
            if config.get('vol_filter', False) and (vol < config['vol_min'] or vol > config['vol_max']): return

            if entry_type == 'cross':
                os_p = int(features['st_os'][i-1]) if i > 0 else os_c
                long_only = config.get('long_only', False)
                if not self.position and os_c == 1 and os_p == 0:
                    sl = p - atr * config['sl_atr']; tp = p + atr * config['sl_atr'] * config['rr']
                    if sl < p < tp: self.buy(size=1, sl=sl, tp=tp)
                elif not self.position and os_c == 0 and os_p == 1 and not long_only:
                    sl = p + atr * config['sl_atr']; tp = p - atr * config['sl_atr'] * config['rr']
                    if tp < p < sl: self.sell(size=1, sl=sl, tp=tp)

            elif entry_type == 'pullback_ma':
                ema = features['ema20'][i]
                if not self.position and os_c == 1 and abs(p/ema-1) < config.get('pb_pct', 0.003):
                    sl = min(p-atr*config['sl_atr'], p*0.99); tp = p+atr*config['sl_atr']*config['rr']
                    if sl < p < tp: self.buy(size=1, sl=sl, tp=tp)
                elif not self.position and os_c == 0 and abs(p/ema-1) < config.get('pb_pct', 0.003):
                    sl = max(p+atr*config['sl_atr'], p*1.01); tp = p-atr*config['sl_atr']*config['rr']
                    if tp < p < sl: self.sell(size=1, sl=sl, tp=tp)

            elif entry_type == 'swing_break':
                # Swing detection
                slen = config.get('swing_len', 20)
                h_arr = df['High'].values; l_arr = df['Low'].values
                swing_h = 0; swing_l = 0
                for k in range(max(0, i-slen), i):
                    if h_arr[k] > swing_h: swing_h = h_arr[k]
                    if l_arr[k] > 0 and (swing_l == 0 or l_arr[k] < swing_l): swing_l = l_arr[k]
                if not self.position:
                    if p > swing_h and swing_h > 0:
                        sl = p - atr * config['sl_atr']; tp = p + atr * config['sl_atr'] * config['rr']
                        if sl < p < tp: self.buy(size=1, sl=sl, tp=tp)
                    elif p < swing_l and swing_l > 0:
                        sl = p + atr * config['sl_atr']; tp = p - atr * config['sl_atr'] * config['rr']
                        if tp < p < sl: self.sell(size=1, sl=sl, tp=tp)

            elif entry_type == 'mtf_4h1h':
                # MTF: 4h STAI trend filter
                if not hasattr(self, '_mtf_4h_map'):
                    df4h = pd.read_parquet(DATA_4H).tail(1000).copy()
                    h4 = df4h['high'].values; l4 = df4h['low'].values; c4 = df4h['close'].values
                    _, os4 = stai(h4, l4, c4, length=10, min_f=0.5, max_f=2.0, step=0.5)
                    # Map by date (year-month-day-hour)
                    ts4 = pd.to_datetime(df4h['timestamp_utc'] if 'timestamp_utc' in df4h.columns else df4h.index)
                    self._mtf_map = {}
                    for j in range(len(ts4)):
                        key = ts4.iloc[j].strftime('%Y%m%d%H')
                        self._mtf_map[key] = int(os4[j])

                curr_key = self.data.index[-1].strftime('%Y%m%d%H')
                trend_4h = self._mtf_map.get(curr_key, 1)
                if trend_4h == 0:
                    # Try previous 4h bar
                    prev_dt = self.data.index[-1] - pd.Timedelta(hours=4)
                    prev_key = prev_dt.strftime('%Y%m%d%H')
                    trend_4h = self._mtf_map.get(prev_key, 1)

                ema = features['ema20'][i]
                if not self.position and trend_4h == 1 and abs(p/ema-1) < 0.003:
                    sl = p - atr * config['sl_atr']; tp = p + atr * config['sl_atr'] * config['rr']
                    if sl < p < tp: self.buy(size=1, sl=sl, tp=tp)

    # ── Run ──
    bt = Backtest(df, S, cash=100000, commission=.002, exclusive_orders=True)
    stats = bt.run()
    trades = stats._trades if hasattr(stats, '_trades') else pd.DataFrame()
    n = len(trades)

    freq = n / (len(df)/(96*5)) if n > 0 else 0
    if tf == '1h': freq = n / (len(df)/(24*5))
    elif tf == '4h': freq = n / (len(df)/(6*5))

    # Breakdowns
    lt = trades[trades['Size'] > 0] if n > 0 else pd.DataFrame()
    st = trades[trades['Size'] < 0] if n > 0 else pd.DataFrame()
    lwr = round(len(lt[lt['PnL']>0])/len(lt)*100 if len(lt)>0 else 0,1)
    swr = round(len(st[st['PnL']>0])/len(st)*100 if len(st)>0 else 0,1)

    # Session breakdown
    sess = {'asia':0,'london':0,'ny':0,'other':0}
    sess_w = {'asia':[0,0],'london':[0,0],'ny':[0,0],'other':[0,0]}
    if n > 0:
        for _, t in trades.iterrows():
            et = t.get('EntryTime', t.get('Time', None))
            if et is None: continue
            try: hh = et.hour + et.minute/60 if hasattr(et, 'hour') else 0
            except: hh = 0
            if 0 <= hh < 8: s = 'asia'
            elif 8 <= hh < 16: s = 'london'
            elif 16 <= hh < 22: s = 'ny'
            else: s = 'other'
            sess[s] += 1
            if float(t.get('PnL', 0)) > 0: sess_w[s][0] += 1
            else: sess_w[s][1] += 1

    # Volatility regime breakdown
    vol_vals = features['vol_ratio'][~np.isnan(features['vol_ratio'])]
    vol_med = np.median(vol_vals) if len(vol_vals) > 0 else 1.0

    return {
        "n": n, "freq": round(freq, 2),
        "wr": round(stats.get('Win Rate [%]', 0) or 0, 1),
        "pf": round(stats.get('Profit Factor', 0) or 0, 2),
        "exp": round(stats.get('Expectancy [%]', 0) or 0, 2),
        "dd": round(stats.get('Max. Drawdown [%]', 0) or 0, 1),
        "lwr": lwr, "swr": swr,
        "session_breakdown": {k: {"n":v, "wr":round(sess_w[k][0]/(sess_w[k][0]+sess_w[k][1])*100,1) if (sess_w[k][0]+sess_w[k][1])>0 else 0} for k,v in sess.items()},
        "trades": trades,
    }


# ── Log experiment ────────────────────────────────────────────
def log_exp(eid, cfg, res, hyp, chg, diag, nxt):
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"\n---\n## Experiment {eid}\n\n")
        f.write(f"**Hypothesis:** {hyp}\n\n")
        f.write(f"**Change:** {chg}\n\n")
        f.write(f"**Entry rule:** {cfg.get('entry','cross')}\n\n")
        f.write(f"**Exit rule:** SL={cfg.get('sl_atr',2)}×ATR, TP={cfg.get('sl_atr',2)}×{cfg.get('rr',2.5)}×R\n\n")
        f.write(f"**Filters:** {json.dumps({k:v for k,v in cfg.items() if k in ['session','vol_filter','s_start','s_end','vol_min','vol_max','rsi_ob','rsi_os','pb_pct']})}\n\n")
        f.write(f"**Backtest range:** {BARS} bars M15\n\n")
        f.write(f"**Total trades:** {res['n']}\n\n")
        f.write(f"**Trades/week:** {res['freq']}\n\n")
        f.write(f"**Winrate:** {res['wr']}%\n\n")
        f.write(f"**Profit factor:** {res['pf']}\n\n")
        f.write(f"**Expectancy:** {res['exp']}%\n\n")
        f.write(f"**Max drawdown:** {res['dd']}%\n\n")
        f.write(f"**Long/Short breakdown:** Long WR: {res['lwr']}%, Short WR: {res['swr']}%\n\n")
        f.write(f"**Session breakdown:** {json.dumps(res.get('session_breakdown',{}))}\n\n")
        verdict = '✅ PASS' if (res['wr']>=65 and res['freq']>=3 and res['pf']>1.2) else '❌ FAIL'
        f.write(f"**Verdict:** {verdict}\n\n")
        f.write(f"**Reason:** {diag}\n\n")
        f.write(f"**Next action:** {nxt}\n\n")


# ═══════════════════════════════════════════════════════════════
# RESEARCH LOOP
# ═══════════════════════════════════════════════════════════════

EXPS = []
LOG_DATA = []

def run_and_log(eid, cfg, hyp, chg, bars=BARS):
    tf = cfg.get('tf', '15m')
    if not tf or tf == 'auto':
        tf = '1h' if cfg.get('use_1h') else ('4h' if cfg.get('use_4h') else '15m')
    print(f"\n{'#'*60}")
    print(f"# Experiment {eid} ({tf})")
    print(f"{'#'*60}")
    print(f"  Hypothesis: {hyp}")
    print(f"  Config: {cfg}")

    t0 = time.time()
    res = run_experiment(cfg, bars=bars, tf=tf)
    t = time.time() - t0

    print(f"  Trades: {res['n']}  /week: {res['freq']}")
    print(f"  WR: {res['wr']}%  PF: {res['pf']}")
    print(f"  Exp: {res['exp']}%  DD: {res['dd']}%")
    print(f"  Long WR: {res['lwr']}%  Short WR: {res['swr']}%")
    sb = res.get('session_breakdown',{})
    print(f"  Session: { {k:v['wr'] for k,v in sb.items()} }")
    print(f"  ({t:.0f}s)")

    # Diagnose
    issues = []
    if res['n'] < 5:
        diag = "Quá ít trade"
    elif res['freq'] < 3:
        diag = "Tần suất thấp"
    elif res['wr'] < 65:
        diag = f"WR {res['wr']}% chưa đạt ngưỡng 65%"
    elif res['pf'] < 1.2:
        diag = f"PF {res['pf']} < 1.2, lợi nhuận âm"
    else:
        diag = "Gần target"

    # Determine next action
    if res['wr'] < 50:
        nxt = "Cần thay đổi entry rule — cross signal quality kém, thử entry khác (pullback/rsi/trend)"
    elif res['wr'] < 65:
        nxt = "WR khá nhưng chưa đủ — thêm filter session/volatility hoặc tăng RR"
    elif res['freq'] < 3:
        nxt = "Freq thấp — mở rộng entry condition"
    elif res['pf'] < 1.2:
        nxt = "PF thấp — cần cải thiện win size hoặc giảm loss"
    else:
        nxt = "Fine-tune"

    log_exp(eid, cfg, res, hyp, chg, diag, nxt)
    EXPS.append(res)
    LOG_DATA.append({"eid": eid, "cfg": cfg, "hyp": hyp, "chg": chg, "res": res, "diag": diag, "nxt": nxt})

    return res


# ═══════════════════════════════════════════════════════════════
# EXPERIMENT 19: E12 + trailing stop STAI (đúng bản chất LuxAlgo)
# ═══════════════════════════════════════════════════════════════

# E12: WR 63.2%, PF 1.75, freq 0.28
# LuxAlgo SuperTrust AI là trailing stop — dùng đúng: enter + trail

class STAI_Trail_Strategy(Strategy):
    def init(self):
        h=np.asarray(self.data.High); l=np.asarray(self.data.Low); c=np.asarray(self.data.Close)
        self.ts, self.os = self.I(lambda: stai(h,l,c,length=10,min_f=0.5,max_f=2.0,step=0.5), name='STAI', overlay=True)
    def _atr(self):
        h,l,c=self.data.High,self.data.Low,self.data.Close
        tr=pd.Series([max(h[i]-l[i],abs(h[i]-c[i-1]),abs(l[i]-c[i-1])) for i in range(1,len(h))])
        return float(tr.tail(14).mean()) if len(tr)>=14 else 0.001
    def next(self):
        i=len(self.data)-1
        if i<30: return
        os_c=int(self.os[-1]); os_p=int(self.os[-2]) if len(self.os)>=2 else os_c
        p=self.data.Close[-1]; ts=self.ts[-1]
        if self.position:
            pos=self.position
            if pos.pl>0 and p<ts:
                self.position.close()
            elif pos.pl<0 and p>ts:
                self.position.close()
            return
        if not self.position and os_c==1 and os_p==0:
            self.buy(size=1)
        elif not self.position and os_c==0 and os_p==1:
            self.sell(size=1)

df4h = load(2000, '4h')
bt19 = Backtest(df4h, STAI_Trail_Strategy, cash=100000, commission=.002, exclusive_orders=True)
s19 = bt19.run(); t19 = s19._trades if hasattr(s19, '_trades') else pd.DataFrame()
n19=len(t19); f19=n19/(2000/(6*5))
lt19=t19[t19['Size']>0] if n19>0 else pd.DataFrame(); st19=t19[t19['Size']<0] if n19>0 else pd.DataFrame()
r19={"n":n19,"freq":round(f19,2),"wr":round(s19.get('Win Rate [%]',0) or 0,1),
     "pf":round(s19.get('Profit Factor',0) or 0,2),"exp":round(s19.get('Expectancy [%]',0) or 0,2),
     "dd":round(s19.get('Max. Drawdown [%]',0) or 0,1),
     "lwr":round(len(lt19[lt19['PnL']>0])/len(lt19)*100 if len(lt19)>0 else 0,1),
     "swr":round(len(st19[st19['PnL']>0])/len(st19)*100 if len(st19)>0 else 0,1)}
print(f"\n{'='*60}\nE19: STAI trailing stop\n{'='*60}")
print(f"  Trades: {r19['n']}  /week: {r19['freq']}")
print(f"  WR: {r19['wr']}%  PF: {r19['pf']}")
print(f"  Exp: {r19['exp']}%  DD: {r19['dd']}%")
print(f"  Target: {'✅' if r19['wr']>=65 and r19['freq']>=3 and r19['pf']>1.2 else '❌'}")
with open(LOG_FILE,"a") as f: f.write(f"\n---\n## Experiment 19 (trailing)\n\nWR {r19['wr']}%, PF {r19['pf']}, freq {r19['freq']}/wk\n\n")

# Save CSV
csv_data = []
for d in LOG_DATA:
    r = d['res']
    csv_data.append([d['eid'], d['cfg'].get('entry'),
                     r['n'], r['freq'], r['wr'], r['pf'], r['exp'], r['dd']])
with open("output/research.csv","w",newline="") as f:
    csv.writer(f).writerows([["exp","entry","trades","freq","wr","pf","exp","dd"]] + csv_data)

print(f"\n{'='*60}")
print("SUMMARY")
print(f"{'='*60}")
for d in LOG_DATA:
    r = d['res']
    flag = '✅' if (r['wr']>=65 and r['freq']>=3 and r['pf']>1.2) else '❌'
    print(f"  E{d['eid']} {flag}: {r['n']}t {r['freq']}/wk WR{r['wr']}% PF{r['pf']} {d['cfg'].get('entry')}")
print(f"{'='*60}")
print("[✓] output/research.csv")
print("[✓] EXPERIMENT_LOG.md")
