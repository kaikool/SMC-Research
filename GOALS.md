# 🎯 Research Goals & Loop Protocol

## Điều kiện dừng (chỉ dừng khi đủ ALL)

| # | Tiêu chí | Ngưỡng | Ghi chú |
|---|----------|--------|---------|
| 1 | Tần suất | ≥ 3 lệnh/tuần | Trên 210k bars M15 (~438 tuần) |
| 2 | Winrate | ≥ 65% | Trên tập test hợp lệ, không p-hack |
| 3 | Tính causal | 0 lookahead | Chỉ dùng dữ liệu tại bar t |
| 4 | Số trade tối thiểu | ≥ 200 fills | Đủ để có ý nghĩa thống kê |
| 5 | Robustness cơ bản | Walk-forward / split-test | Không overfit 1 đoạn |

## Vòng lặp nghiên cứu

Mỗi vòng lặp gồm:

```
1. HYPOTHESIS: Nêu giả thuyết rõ ràng (thay gì, vì sao)
2. IMPLEMENT: Sửa code (thêm/bỏ feature, filter, logic)
3. BACKTEST: Chạy 210k bars → báo WR + freq + total R
4. VERIFY: 
   - Có đạt ≥ 65% WR và ≥ 3/tuần?
   - Có causal (không lookahead)?
   - So với baseline trước đó, cải thiện hay tệ hơn?
5. LOG: Ghi vào NHAT_KY_PHAT_TRIEN.md
6. LOOP: Nếu chưa đạt → quay lại bước 1
```

## Quyền thay đổi (được phép)

- ✅ Thêm feature mới (indicator, filter, regime)
- ✅ Bỏ feature không hiệu quả
- ✅ Thay đổi filter condition (vol, session, trend)
- ✅ Thay đổi logic entry/exit (SL, TP, entry price)
- ✅ Thay đổi session / regime / volatility threshold
- ✅ Thay đổi OB type được chấp nhận (swing / internal)

## Không được phép

- ❌ Dùng lookahead / future data trong entry
- ❌ Dùng single-bar event làm tín hiệu chính
- ❌ P-hack: chọn đoạn data thuận lợi rồi báo kết quả
- ❌ Báo WR mà không kèm frequency

## Log format bắt buộc

```markdown
## Vòng N: [giả thuyết ngắn]

### Thay đổi
- File X: sửa dòng Y → lý do Z
- Thêm feature A với threshold B

### Kết quả
| Model | WR | /week | Total R | Fills |
|-------|:--:|:-----:|:-------:|:-----:|
| V8 | 65.0% | 3.70 | +2218 | 1623 |

### So sánh baseline
- WR: 65.0% vs trước 60.6% (+4.4%)
- Freq: 3.70 vs trước 6.05 (-39%)
- Kết luận: trade-off WR vs freq, đã đạt target

### Causal check
- [x] Không lookahead (OB active_from verified)
- [x] Event-sourced cache, lifecycle remove
```

## Baseline hiện tại

| Model | WR | /week | Total R | Ghi chú |
|-------|:--:|:-----:|:-------:|---------|
| V8 Combined | 65.0% | 3.70 | +2218 | 🏆 ĐẠT MỤC TIÊU |

## Phiên bản đã đạt

- **V8_Combined**: 65.0% WR, 3.70/week, +2218R — 2026-06-17
