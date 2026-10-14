# Hiệu chỉnh & vận hành

## Ngưỡng
| Tham số | Mặc định | Ý nghĩa |
|---|---|---|
| door_threshold / door_margin / door_votes | 0.45 / 0.08 / 3 | cửa: điểm tối thiểu, hơn người nhì, số khung đồng ý |
| room_threshold / room_threshold_high / room_margin / room_votes | 0.42 / 0.38 / 0.06 / 2 | cam trần; "high" áp dụng khi cúi ≥ `high_angle_pitch` hoặc quay ≥ `high_angle_yaw` |
| grace_s / min_absence_s | 120 / 60 | thời gian chờ trước khi tính vắng; vắng ngắn hơn bị bỏ |
| open_hour / close_hour | 8 / 20 | giờ hoạt động |

Mặc định dựa trên đo thực tế: người khác nhau ≈ 0.0–0.25, cùng người thường > 0.5 (mặt thẳng > 0.8). Ngưỡng thấp cho góc cao vì điểm của cùng một người giảm khi cúi/nghiêng; đổi lại dễ nhầm hơn — hãy hiệu chỉnh bằng dữ liệu của CLB.

## Hiệu chỉnh (Cài đặt → Hiệu chỉnh ngưỡng)
Biểu đồ: xanh = điểm cùng người, đỏ = khác người/người lạ. Ngưỡng nên nằm **trên mọi điểm đỏ** (+0.03–0.05) và **dưới phần lớn điểm xanh**. Nút *Áp dụng ngưỡng đề xuất* dùng điểm cao nhất của người khác + mẫu người lạ. Cần ≥ 2 người đăng ký, và tốt nhất ≥ 5 lượt người lạ (nút ở *Thử nhận diện*). Đây là ước lượng, không phải bảo chứng; kiểm tra lại sau khi thêm người.
Lỗi nhận nhầm thường do mẫu đăng ký sai tên hoặc mờ → xoá mẫu và đăng ký lại.

## Bật/tắt theo giờ
Client tự nghỉ ngoài `--open/--close`. Để khỏi trả tiền ngoài giờ dùng `tools/space_power.py` (docs/02). Trạng thái hiện diện được khôi phục sau khi khởi động lại trong cùng ngày.

## Sao lưu
*Cài đặt → Tải sao lưu CSDL* (file SQLite, chứa vector mặt — bảo quản như dữ liệu nhạy cảm).
