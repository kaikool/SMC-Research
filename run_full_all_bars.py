"""Full run on all 210k bars — 3 optimized models + PnL."""
import sys, os, csv
from pathlib import Path
from collections import defaultdict
sys.path.insert(0, os.path.dirname(__file__))
os.environ["PYTHONUNBUFFERED"] = "1"
csv.field_size_limit(10*1024*1024)

from strategy_layer.entry_strategies import (
    Model1_EQHEQL_Sweep_InternalCHOCH,
    Model5_StrongDefense,
    Model7_IntCHOCH_OB,
)

WINDOW = 200

def main():
    d = Path("output_full_fvg/layer1")
    
    print("Loading snapshots...")
    with open(d/"snapshots.csv") as f:
        snaps = list(csv.DictReader(f))
    bar_snaps = {int(s["bar_index"]): s for s in snaps}
    bix = sorted(bar_snaps.keys())
    print(f"  Bars: {len(bix)} ({bix[0]} → {bix[-1]})")
    
    print("Loading events...")
    with open(d/"events.csv") as f:
        eb = defaultdict(list)
        for r in csv.DictReader(f): eb[int(r["bar_index"])].append(r)
    print(f"  Events: {sum(len(v) for v in eb.values())}")
    
    print("Loading objects...")
    with open(d/"objects.csv") as f:
        obs = list(csv.DictReader(f))
    tsb = {}
    for s in snaps:
        try: tsb[int(s["timestamp"])] = int(s["bar_index"])
        except: pass
    for o in obs:
        try:
            ot = int(o.get("created_at",0))
            bi = tsb.get(ot,-1)
            if bi==-1 and ot>0:
                st = sorted(k for k in tsb.keys() if k<=ot)
                if st: bi=tsb[st[-1]]
            o["_bar_index"] = bi
        except: o["_bar_index"]=-1
    obb = defaultdict(list)
    for o in obs:
        bi = o.get("_bar_index",-1)
        if bi>=0: obb[bi].append(o)
    
    print("Building OB cache...")
    cache = {}
    recent = []
    for bi in bix:
        for o in obb.get(bi,[]): recent.append(o)
        recent = [o for o in recent if bi-o.get("_bar_index",0)<=WINDOW]
        cache[bi] = list(recent)
    print(f"  ~{sum(len(v) for v in cache.values())//len(cache)} avg/bar")
    
    print("Loading prices...")
    import pandas as pd
    df = pd.read_parquet("D:/PHUCTD/SMC Research/data/XAUUSD_15m.parquet")
    prices = {}
    for _,r in df.iterrows():
        ts = r["timestamp_utc"]
        ms = int(ts.timestamp()*1000) if hasattr(ts,'timestamp') else 0
        bi = tsb.get(ms,-1)
        if bi>=0: prices[bi]={"open":float(r["open"]),"high":float(r["high"]),"low":float(r["low"]),"close":float(r["close"])}
    print(f"  {len(prices)} bars")
    
    models = [
        ("M1_EQHEQL_CHOCH_OB", Model1_EQHEQL_Sweep_InternalCHOCH()),
        ("M5_STRONG_DEFENSE", Model5_StrongDefense()),
        ("M7_INTCHOCH_OB", Model7_IntCHOCH_OB()),
    ]
    
    total_orders=0; total_wins=0; total_losses=0; total_r=0.0
    
    for mn, model in models:
        orders = []
        n=len(bix)
        for idx, bi in enumerate(bix):
            bar_orders = model.on_bar(bi, eb.get(bi,[]), bar_snaps.get(bi,{}), cache.get(bi,[]))
            orders.extend(bar_orders)
            if (idx+1)%50000==0: print(f"  {mn}: {idx+1}/{n} bars, {len(orders)} orders so far")
        
        wins=0; losses=0; tr=0.0
        for o in orders:
            entry=o.entry_price; sl=o.sl_price; tp=o.tp_price
            risk=abs(entry-sl) if sl!=entry else 1
            reward=abs(tp-entry)
            for off in range(1,201):
                bi=o.bar_index+off; bar=prices.get(bi)
                if not bar: break
                if o.direction==1:
                    if bar["low"]<=sl: losses+=1; tr+=-1.0; break
                    if bar["high"]>=tp: wins+=1; tr+=reward/risk; break
                else:
                    if bar["high"]>=sl: losses+=1; tr+=-1.0; break
                    if bar["low"]<=tp: wins+=1; tr+=reward/risk; break
        
        closed=wins+losses
        wr=wins/closed*100 if closed>0 else 0
        print(f"{mn}: {len(orders)} orders, {wins}W/{losses}L, WR={wr:.1f}%, R={tr:.1f}")
        total_orders+=len(orders); total_wins+=wins; total_losses+=losses; total_r+=tr
    
    twr=total_wins/(total_wins+total_losses)*100 if (total_wins+total_losses)>0 else 0
    weeks = len(bix)/(96*5)
    print(f"\n{'='*50}")
    print(f"FULL 210k BARS RESULTS")
    print(f"{'='*50}")
    print(f"Total orders: {total_orders}")
    print(f"Wins: {total_wins}, Losses: {total_losses}")
    print(f"Win Rate: {twr:.1f}%")
    print(f"Total R: {total_r:.1f}")
    print(f"Orders/week: {total_orders/weeks:.1f} (target: 3+)")
    print(f"Target WR >65%: {'✅' if twr>65 else '❌'}")
    print(f"Target 3+/week: {'✅' if total_orders/weeks>=3 else '❌'}")

if __name__=="__main__":
    main()
