# VERSION 1 — SMC Research Engine Spec

## 1. Tổng quan

Hệ thống SMC Event Engine phát hiện cấu trúc thị trường Smart Money Concepts:
Order Block (OB), Break of Structure (BOS), Change of Character (CHOCH),
Swing High/Low, Equal Highs/Lows, Premium/Discount Zones, Liquidity Sweep.

**Pipeline:**
```
OHLC → Swing detection → Structure break (BOS/CHOCH) → Order Block creation
      → OB lifecycle (touch/mitigate/expire) → Entry model → Execution
```

**Data:** XAUUSD M15, 210K bars, 2017-2025

---

## 2. Layer 1 — SMC Event Engine

### 2.1 Swing Detection

```
Input: high[], low[], close[] arrays
Parameters: swing_length = 5, internal_length = 2

Mỗi bar index i (bắt đầu từ 0):
  1. Append bar.high, bar.low, bar.timestamp vào history arrays
  2. Update True Range (TR) và ATR(14)
     TR = max(high - low, |high - prev_close|, |low - prev_close|)
     ATR = SMA(TR, 14)
  3. Trailing extremes: cập nhật trailing_top (cao nhất) và trailing_bottom (thấp nhất)

Swing pivot detection (LuxAlgo leg method):
  pivot_idx = bar_index - swing_length
  new_swing_high = highs[pivot_idx] > max(highs[pivot_idx + 1 : bar_index + 1])
  new_swing_low  = lows[pivot_idx]  < min(lows[pivot_idx + 1 : bar_index + 1])

  Leg tracking:
    prev_leg = swing_leg (0 = bearish, 1 = bullish)
    if new_swing_high: current_leg = 0 (bearish_leg — swing high)
    if new_swing_low:  current_leg = 1 (bullish_leg — swing low)
    
    leg_changed = current_leg != prev_leg
    started_bearish = leg_changed AND current_leg == 0  → new SWING HIGH at pivot_idx
    started_bullish = leg_changed AND current_leg == 1  → new SWING LOW at pivot_idx

  Nếu started_bearish → emit SWING_HIGH event tại bar_index (không phải pivot_idx)
  Nếu started_bullish → emit SWING_LOW event tại bar_index

  Tương tự với internal_length (mặc định 2) → emit INTERNAL_SWING_HIGH / INTERNAL_SWING_LOW

  ⚠️ Pivot được xác nhận tại bar_index - size, emit event tại bar_index.
     Không emit event tại pivot_idx — tránh lookahead.
```

### 2.2 Equal Highs/Lows (EQH/EQL)

```
Parameter: bars_confirmation = 5, threshold = 0.001 (tỷ lệ ATR)

Mỗi bar, so sánh pivot vừa phát hiện với swing_high / swing_low gần nhất:
  Nếu |swing_high.price - highs[pivot_idx]| < threshold * ATR:
    → emit EQUAL_HIGH
  Nếu |swing_low.price - lows[pivot_idx]| < threshold * ATR:
    → emit EQUAL_LOW
```

### 2.3 Structure Break — BOS / CHOCH

```
Input: swing_high PivotPoint, swing_low PivotPoint
       internal_high, internal_low (cho internal level)
       prev_close, close (giá đóng cửa bar trước và bar hiện tại)
       swing_trend (0 = neutral, 1 = bullish, -1 = bearish)

Với mỗi pivot_high (cả swing và internal):
  Nếu pivot_high.price > 0 AND pivot_high chưa bị cross:
    Kiểm tra: prev_close <= pivot_high.price < close
      → Bullish break (giá đóng cửa trên swing high)
      
      Xác định tag:
        Nếu swing_trend == BEARISH → tag = "CHOCH" (đảo chiều)
        Nếu swing_trend == BULLISH → tag = "BOS" (tiếp diễn)
      
      Cập nhật trend = BULLISH
      pivot_high.crossed = True (không bị phá vỡ lần 2)
      Emit: "BOS_BULLISH" hoặc "CHOCH_BULLISH" (thêm "INTERNAL_" nếu internal)

Với mỗi pivot_low (cả swing và internal):
  Nếu pivot_low.price > 0 AND pivot_low chưa bị cross:
    Kiểm tra: prev_close >= pivot_low.price > close
      → Bearish break (giá đóng cửa dưới swing low)
      
      Xác định tag:
        Nếu swing_trend == BULLISH → tag = "CHOCH" (đảo chiều)
        Nếu swing_trend == BEARISH → tag = "BOS" (tiếp diễn)
      
      Cập nhật trend = BEARISH
      pivot_low.crossed = True
      Emit: "BOS_BEARISH" hoặc "CHOCH_BEARISH"

Internal extra condition: chỉ fire nếu internal pivot khác swing pivot
Internal confluence filter (tùy chọn):
  Bullish bar: upper_wick > lower_wick (râu trên > râu dưới)
  Bearish bar: upper_wick < lower_wick
  upper_wick = high - max(close, open)
  lower_wick = min(close, open) - low
```

### 2.4 Order Block (OB) Creation

```
Khi BOS hoặc CHOCH fire (confirmed = true):

  direction = direction of the break (BULLISH=1 hoặc BEARISH=-1)
  level = SWING hoặc INTERNAL
  pivot_bar = bar_index của swing point bị phá vỡ
  current_bar = bar_index hiện tại (bar break)
  
  BULLISH break (BOS_BULLISH / CHOCH_BULLISH):
    # Tìm bar có giá thấp nhất (parsedLow) trong [pivot_bar, current_bar)
    segment = parsed_lows[pivot_bar : current_bar]
    min_idx = argmin(segment)
    ob_bar = pivot_bar + min_idx
    ob_top = parsed_highs[ob_bar]   # biên trên OB
    ob_bottom = parsed_lows[ob_bar]  # biên dưới OB
  
  BEARISH break (BOS_BEARISH / CHOCH_BEARISH):
    # Tìm bar có giá cao nhất (parsedHigh) trong [pivot_bar, current_bar)
    segment = parsed_highs[pivot_bar : current_bar]
    max_idx = argmax(segment)
    ob_bar = pivot_bar + max_idx
    ob_top = parsed_highs[ob_bar]   # biên trên OB
    ob_bottom = parsed_lows[ob_bar]  # biên dưới OB
  
  Volatility filter (LuxAlgo):
    Nếu bar[ob_bar].range >= 2 * ATR:
      # Volatility quá cao → swap parsedHigh/parsedLow
      ob_top, ob_bottom = ob_bottom, ob_top
  
  OB properties:
    id = "OB_{counter}"
    direction = direction của break
    structure_type = level (SWING / INTERNAL)
    origin_bar = ob_bar (bar chứa OB zone)
    created_at = timestamp của ob_bar
    active_from = timestamp của current_bar (bar BOS — OB có hiệu lực từ bar này)
    top = ob_top
    bottom = ob_bottom
    status = "active"
    source_event = event_type (vd "BOS_BULLISH")

  ⚠️ active_from = current_bar.timestamp, KHÔNG phải ob_bar.timestamp.
     OB chỉ có thể được dùng từ bar SAU KHI BOS xảy ra.
```

### 2.5 OB Lifecycle

```
Mỗi bar, kiểm tra tất cả OB đang active:

  TOUCH (lần đầu tiên):
    Nếu bar chạm vùng OB (high >= ob.bottom AND low <= ob.top):
      → emit OB_TOUCHED (lần đầu tiên, chỉ 1 lần)
  
  MITIGATION:
    direction = BULLISH (OB hỗ trợ LONG):
      Nếu bar.low < ob.bottom:
        → emit OB_MITIGATED, status = "mitigated"
    direction = BEARISH (OB kháng cự SHORT):
      Nếu bar.high > ob.top:
        → emit OB_MITIGATED, status = "mitigated"
  
  INVALIDATION (close_through):
    direction = BULLISH:
      Nếu bar.close < ob.bottom:
        → emit OB_INVALIDATED, status = "invalidated"
    direction = BEARISH:
      Nếu bar.close > ob.top:
        → emit OB_INVALIDATED, status = "invalidated"
  
  EXPIRY:
    Nếu age > max_age_bars (mặc định 200):
      → emit OB_EXPIRED, status = "expired"

  Xóa OB khỏi active list khi mitigated / invalidated / expired.
```

### 2.6 Premium / Discount Zones

```
Trailing extremes (cập nhật mỗi bar):
  trailing_top = max(trailing_top, bar.high)  — giá cao nhất
  trailing_bottom = min(trailing_bottom, bar.low)  — giá thấp nhất

Khoảng PD = trailing_top - trailing_bottom
  premium_zone = [trailing_top - PD*0.25, trailing_top]  — trên 25% (bán)
  discount_zone = [trailing_bottom, trailing_bottom + PD*0.25]  — dưới 25% (mua)

Khi bar.close vào premium → emit PRICE_ENTER_PREMIUM
Khi bar.close vào discount → emit PRICE_ENTER_DISCOUNT
```

### 2.7 Liquidity Sweep

```
Khi có equal highs/lows và bar phá vỡ các mức đó:
  - Phá vỡ equal highs với bearish candle → emit LIQUIDITY_SWEEP
  - Phá vỡ equal lows với bullish candle → emit LIQUIDITY_SWEEP
```

### 2.8 Snapshot (trạng thái mỗi bar)

```
Mỗi bar, snapshot ghi:
  timestamp, bar_index, last_swing_high, last_swing_low
  current_trend (swing_trend), active_ob_count
  in_premium, in_discount (bool)
  trailing_top, trailing_bottom
```

---

## 3. Layer 2 — OB Cache cho Backtest

### 3.1 Event-sourced OB Cache

```
Không dùng sliding window. Xây cache bằng events:
  1. Map OB.active_from → bar_index (dùng timestamp)
  2. Tạo dictionary: obs_by_activation_bar[bar_index] = [OB1, OB2, ...]
  3. Tạo dictionary: ob_by_id[object_id] = OB
  4. Tạo lifecycle map: lifecycle_by_bar[bar_index] = [OB_MITIGATED, ...]

  active_ids = set()
  for bi from 0 to max_bar:
    # Thêm OB mới activation
    for ob in obs_by_activation_bar[bi]:
      active_ids.add(ob.object_id)
    # Xóa OB bị lifecycle
    for ev in lifecycle_by_bar[bi]:
      active_ids.discard(ev.object_id)
    # Lọc theo window (200 bars)
    cache[bi] = [ob_by_id[oid] for oid in active_ids 
                 if bi - ob_by_id[oid]._bar_index <= 200]

  → O(n) thay vì O(n²)
```

### 3.2 OB Lookup cho Entry Model

```
Model nhận vào active_obs[bar_index] — list OB đang active tại bar đó.
Mỗi OB có các field: object_id, type, direction, top, bottom, _bar_index, _origin_bar_index

Model check:
  ob_bar = OB._bar_index  (bar OB bắt đầu có hiệu lực, active_from mapped)
  setup_bar = bar_index của signal trigger (BOS/CHOCH event)
  
  entry_condition = ob_bar >= setup_bar  (OB chỉ dùng được SAU KHI signal xảy ra)
  
  LONG: entry = OB.top, SL = OB.bottom - 0.5*height
  SHORT: entry = OB.bottom, SL = OB.top + 0.5*height
```

---

## 4. V8 Combined — Entry Model

Kết hợp 2 rule:

### Rule A — Swing OB

```
Điều kiện:
  - OB.type == "SWING" (ORDER_BLOCK_SWING)
  - OB.direction cùng chiều với swing_trend
  - Mỗi OB chỉ vào 1 lần

Entry:
  LONG: entry = OB.top
  SHORT: entry = OB.bottom

SL:
  LONG: OB.bottom - (OB.top - OB.bottom) * 0.5
  SHORT: OB.top + (OB.top - OB.bottom) * 0.5

TP:
  equilibrium = (last_swing_high + last_swing_low) / 2
  Capped at 5R (R = |entry - SL|)
```

### Rule B — CHOCH + Internal OB

```
Điều kiện:
  - Có event INTERNAL_CHOCH_BEARISH hoặc CHOCH_BEARISH (direction=-1)
    hoặc INTERNAL_CHOCH_BULLISH hoặc CHOCH_BULLISH (direction=1)
  - Trend cùng chiều với direction
  - active_ob_count >= 8 (volatility filter)
  - Session London/NY (UTC 8:00 - 22:00)
  - Internal OB cùng hướng, active

Entry:
  LONG: entry = (OB.top + OB.bottom) / 2
  SHORT: entry = (OB.top + OB.bottom) / 2

SL:
  LONG: OB.bottom - height * 0.5
  SHORT: OB.top + height * 0.5

TP:
  equilibrium = (last_swing_high + last_swing_low) / 2
  Capped at 5R

⚠️ Kết hợp: nếu Rule A và Rule B cùng bar → chỉ vào 1 lệnh (không double)
```

### Filters (cho cả 2 rule):

```
Trend filter:
  direction == 1 AND swing_trend == -1 → skip (counter-trend)
  direction == -1 AND swing_trend == 1 → skip

Volatility filter (Rule B):
  active_ob_count >= 8
  active_ob_count = số OB đang active tại bar hiện tại

Session filter (Rule B):
  UTC hour >= 8 AND hour < 22 (London mở cửa đến NY đóng cửa)
```

---

## 5. OrderIntent & Execution

### OrderIntent (đầu ra từ strategy sang execution):

```
setup_id: string
direction: 1 (LONG) / -1 (SHORT)
order_type: "limit" (luôn limit cho OB entry)
entry_price: giá OB boundary hoặc OB mid
entry_zone_top: OB.top
entry_zone_bottom: OB.bottom
stop_loss: giá SL đã tính
take_profit: giá TP đã tính
signal_bar: bar_index signal
valid_until_bar: signal_bar + 150 (bars)
```

### Execution logic:

```
FILL:
  LONG limit: Nếu bar.low <= entry_price → khớp tại entry_price (cost-adjusted)
  SHORT limit: Nếu bar.high >= entry_price → khớp tại entry_price (cost-adjusted)
  Chờ tối đa valid_until_bar, nếu không khớp → expired

  Cost adjustment (XAUUSD):
    spread = 0.30, slippage = 0.10
    LONG pay ask: entry_cost = entry + spread/2 + slippage
    SHORT receive bid: entry_cost = entry - spread/2 - slippage
    SL exit: LONG receive bid (trừ cost), SHORT pay ask (cộng cost)
    TP exit: tương tự SL exit

SL/TP CHECK:
  Sau khi fill, mỗi bar kiểm tra:
    LONG: 
      Nếu bar.low <= stop_loss → SL_HIT, R = -1.0
      Nếu bar.high >= take_profit → TP_HIT, R = |tp - entry_cost| / |entry_cost - sl|
    SHORT:
      Nếu bar.high >= stop_loss → SL_HIT, R = -1.0
      Nếu bar.low <= take_profit → TP_HIT, R = |tp - entry_cost| / |entry_cost - sl|
  Chờ tối đa 200 bars sau fill → TIMEOUT (exit tại bar.close)
  Nếu hết dữ liệu → OPEN (không tính)
```

---

## 6. Kết quả Backtest

```
210k bars XAUUSD M15 (2017-2025)
Spread 0.30 + Slippage 0.10 price units
Limit fill (OHLC), SL/TP check bar-by-bar (OHLC)

V8_COMBINED:  68.9% WR | 3.70/week | +2225.32R
              ✅ ≥ 65%  | ✅ ≥ 3    | ✅ có lãi
```

---

## 7. Lưu ý khi code Pine Script

```
1. ta.pivothigh(5,5) / ta.pivotlow(5,5) — swing pivot
   ta.pivothigh(2,2) / ta.pivotlow(2,2) — internal pivot
   ta.valuewhen() để lấy giá và bar index

2. OB zone = [swing_bar, BOS_bar) — KHÔNG gồm BOS_bar
   Dùng toán tử [] của Pine để slice: high[swing_bar:BOS_bar]

3. Biến var để track OB state (box, active time, mitigated flag)

4. Volatility: ta.atr(14) / ta.sma(ta.atr(14), 20) * 10 ≥ 8
   Trong Python dùng active_ob_count ≥ 8. Pine không có active_ob_count
   nên thay bằng ATR/SMA proxy.

5. Session: time(timeframe.period, "0800-2200:12345")

6. Tham khảo file tuned_strategies.py class V8_Combined
   để xem logic entry đầy đủ.

7. Không dùng barstate.isconfirmed hoặc future lookahead.
   Entry signal chỉ tại bar.close hoặc bar mới.
```
