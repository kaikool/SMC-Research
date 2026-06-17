# Experiment Log — SuperTrend AI LuxAlgo Research

## E01: Baseline SuperTrend AI cross entry (M15)
**Entry rule:** STAI cross: 0→1 LONG, 1→0 SHORT  
**Exit rule:** SL=2×ATR, TP=2.5×R  
**Filters:** None  
**Result:** 126 trades, 12.1/wk, WR 26.2%, PF 0.30, Exp -0.43%, DD -2.1%  
**Diagnosis:** Quá nhiễu, WR thấp  

## E02: M15 + session filter + wider RR  
**Change:** Thêm session filter London/NY, RR từ 2.5→3.0  
**Result:** 78 trades, 7.49/wk, WR 32.1%, PF 0.53, Exp -0.27%, DD -0.9%  
**Diagnosis:** WR cải thiện nhẹ nhưng PF vẫn < 1  

## E03: M15 + wider factors (1-4) + worst cluster  
**Change:** Factor range 1-4 step 1 (4 factors), chọn worst cluster  
**Result:** 81 trades, 7.78/wk, WR 21.0%, PF 0.33, Exp -0.43%, DD -1.4%  
**Diagnosis:** Worst cluster làm giảm WR  

## E04: M15 + entry tại trailing stop touch  
**Change:** Entry khi price chạm SuperTrust trailing stop (mean reversion)  
**Result:** 124 trades, 11.9/wk, WR 46.8%, PF 0.28, Exp -0.42%, DD -2.1%  
**Diagnosis:** WR tốt nhất trên M15 (46.8%) nhưng PF thấp  

## E05: M15 + pullback MA20 + SuperTrust filter  
**Change:** Entry tại pullback MA20, SuperTrust direction làm filter  
**Result:** 134 trades, 12.86/wk, WR 41.8%, PF 0.20, Exp -0.41%, DD -2.2%  
**Diagnosis:** Pullback không chọn lọc  

## E06: M15 + pullback MA20 + session filter  
**Change:** Thêm session London/NY  
**Result:** 109 trades, 10.46/wk, WR 45.9%, PF 0.21, Exp -0.40%, DD -1.8%  
**Diagnosis:** Session filter cải thiện WR nhẹ  

## E07: M15 + RSI entry + SuperTrust direction filter  
**Change:** LONG khi SuperTrust UP + RSI > 30, SHORT khi DOWN + RSI < 40  
**Result:** 129 trades, 6.19/wk, WR 28.7%, PF 0.43, Exp -0.31%, DD -1.4%  
**Diagnosis:** RSI filter quá rộng, không improve  

## E08: M15 + swing breakout entry  
**Change:** Entry tại swing high/low break  
**Result:** 198 trades, 9.5/wk, WR 30.8%, PF 0.32, Exp -0.35%, DD -2.6%  
**Diagnosis:** Swing break nhiễu  

## E09: M15 + SuperTrust trailing stop (không SL/TP fixed)  
**Change:** Entry tại STAI flip, exit tại trailing stop  
**Result:** 146 trades, 2.19/wk, WR 18.5%, PF 0.34, Exp -0.35%, DD -1.7%  
**Diagnosis:** Trailing stop không hiệu quả trên M15  

## E10: 1h SuperTrust AI cross  
**Change:** Chuyển lên 1h timeframe  
**Result:** 53 trades, 2.12/wk, WR 34.0%, PF 0.68, Exp -0.27%, DD -0.7%  
**Diagnosis:** 1h tốt hơn M15 (PF 0.68) nhưng freq thấp  

## E11: 4h SuperTrust AI cross  
**Change:** Chuyển lên 4h timeframe  
**Result:** 56 trades, 0.84/wk, WR 35.7%, PF 1.16, Exp 0.05%, DD -0.4%  
**Diagnosis:** PF 1.16 — gần target! Long WR 53.8%, London WR 62.5%  

## E12: 4h + LONG only + London session  
**Change:** Chỉ LONG, session London 8-16  
**Result:** 31 trades, 0.46/wk, WR 48.4%, PF 1.53, Exp 0.29%, DD -0.3%  
**Diagnosis:** PF 1.53 — target exceeded! WR 48% → cần cải thiện  

## E13: 4h + LONG only + London+NY overlap + short ATR  
**Change:** Session 13-22, ATR=8  
**Result:** 19 trades, 0.28/wk, WR 63.2%, PF 1.75, Exp 0.63%, DD -0.2%  
**Diagnosis:** ★ BEST CANDIDATE — WR 63.2%, PF 1.75, nhưng freq 0.28/wk  

## E14: 4h + BOTH directions + London+NY overlap  
**Change:** Thêm SHORT để tăng freq  
**Result:** 34 trades, 0.51/wk, WR 50.0%, PF 1.04, Exp 0.03%, DD -0.2%  
**Diagnosis:** BOTH directions giảm WR và PF  

## E15: 4h + no session filter + optimized ATR  
**Change:** Bỏ session, ATR=10, BOTH directions  
**Result:** 104 trades, 1.56/wk, WR 35.6%, PF 0.68, Exp -0.27%, DD -1.0%  
**Diagnosis:** Mở rộng filter làm WR giảm mạnh  

## E16: 4h + high sensitivity (ATR=8, mult=1.5)  
**Change:** ATR=8, factor max=1.5, no session  
**Result:** 103 trades, 1.54/wk, WR 33.0%, PF 0.68, Exp -0.29%, DD -1.0%  
**Diagnosis:** Sensitivity quá cao → noise  

## E17: MTF 4h trend + 1h pullback entry  
**Change:** 4h STAI làm trend filter, entry trên 1h  
**Result:** 123 trades, 4.92/wk, WR 40.7%, PF 0.46, Exp -0.36%, DD -2.3%  
**Diagnosis:** MTF không cải thiện WR đủ  

## E18: 4h + BOTH directions + London+NY session  
**Change:** E13 + E14: BOTH directions, session 8-22  
**Result:** 67 trades, 1.0/wk, WR 26.9%, PF 0.15, Exp -0.55%, DD -2.4%  
**Diagnosis:** BOTH directions trên 4h không hiệu quả  

## E19: 4h + freq recovery (no session, tight SL, RR=1.5)  
**Change:** E13 mở session 24h, SL=1.0, RR=1.5  
**Result:** 250 trades, 30.0/wk, WR 13.2%, PF 0.05, Exp -0.59%, DD -3.5%  
**Diagnosis:** Quá lỏng → chết  

---

## Kết luận

| ID | Entry | TF | Trades | /wk | WR | PF | Exp | DD |
|----|-------|----|--------|-----|----|----|-----|----|
| E01 | cross | M15 | 126 | 12.1 | 26.2% | 0.30 | -0.43% | -2.1% |
| E02 | +session+RR3 | M15 | 78 | 7.5 | 32.1% | 0.53 | -0.27% | -0.9% |
| E03 | wide factors | M15 | 81 | 7.8 | 21.0% | 0.33 | -0.43% | -1.4% |
| E04 | TS touch | M15 | 124 | 11.9 | 46.8% | 0.28 | -0.42% | -2.1% |
| E05 | pullback MA20 | M15 | 134 | 12.9 | 41.8% | 0.20 | -0.41% | -2.2% |
| E06 | pullback+sess | M15 | 109 | 10.5 | 45.9% | 0.21 | -0.40% | -1.8% |
| E07 | RSI+ST | M15 | 129 | 6.2 | 28.7% | 0.43 | -0.31% | -1.4% |
| E08 | swing break | M15 | 198 | 9.5 | 30.8% | 0.32 | -0.35% | -2.6% |
| E09 | trailing ST | M15 | 146 | 2.2 | 18.5% | 0.34 | -0.35% | -1.7% |
| E10 | cross | 1h | 53 | 2.1 | 34.0% | 0.68 | -0.27% | -0.7% |
| E11 | cross | 4h | 56 | 0.8 | 35.7% | 1.16 | +0.05% | -0.4% |
| E12 | **LONG only** | 4h | 31 | 0.5 | 48.4% | **1.53** | +0.29% | -0.3% |
| **E13** | **LONG+overlap** | **4h** | **19** | **0.3** | **63.2%** | **1.75** | **+0.63%** | **-0.2%** |
| E14 | BOTH+overlap | 4h | 34 | 0.5 | 50.0% | 1.04 | +0.03% | -0.2% |
| E15 | no session | 4h | 104 | 1.6 | 35.6% | 0.68 | -0.27% | -1.0% |
| E16 | high sens | 4h | 103 | 1.5 | 33.0% | 0.68 | -0.29% | -1.0% |
| E17 | MTF 4h+1h | 1h | 123 | 4.9 | 40.7% | 0.46 | -0.36% | -2.3% |
| E18 | BOTH | 4h | 67 | 1.0 | 26.9% | 0.15 | -0.55% | -2.4% |
| E19 | freq recov | 4h | 250 | 30.0 | 13.2% | 0.05 | -0.59% | -3.5% |

**Best candidate: E13** — WR 63.2%, PF 1.75. Chỉ thiếu freq (0.28/wk) để đạt full target.
