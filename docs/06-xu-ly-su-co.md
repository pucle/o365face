# Xử lý sự cố
| Hiện tượng | Cách xử lý |
|---|---|
| `ZoneInfoNotFoundError` | `pip install tzdata` |
| Git Bash: `.venv/bin/activate: No such file` | `source .venv/Scripts/activate` |
| UI báo "Sai hoặc thiếu API token" | nút **Token**; server đã đặt `API_TOKEN` chưa |
| Không bật được camera trình duyệt | cần HTTPS hoặc `localhost`; cho phép quyền camera |
| Đăng ký không giữ ảnh / chặng không chuyển | chỉ 1 người trong khung; lại gần; đủ sáng; làm theo mũi tên (chữ đỏ cam cho biết lý do: chưa thấy mặt, nhòe, 2 người…); nếu hết giờ chặng đó sẽ báo yếu, dùng *Làm lại hướng yếu* |
| "Khuôn mặt này giống X hơn…" | chọn nhầm thành viên; dừng và chọn lại |
| "Phiên đăng ký đã hết hạn" | để quá 20 phút hoặc server khởi động lại: bấm Bắt đầu lại |
| Ảnh bị "duplicate"/"blurry" | nhúc nhích nhẹ giữa các lần chụp; giữ yên, thêm sáng |
| Người đã đăng ký bị "lạ" ở cửa | nhìn thẳng; đăng ký thêm ở Đầy đủ; xem điểm ở *Thử nhận diện*; hạ `door_threshold` nhẹ |
| Hai người bị nhầm | tăng `*_margin`/ngưỡng; xoá mẫu mờ; đăng ký lại |
| Cam trần không gán tên | chỉnh `--door-zone`; người phải xuất hiện **một mình** ở vùng cửa sau khi check-in (≤ 60 s) |
| Hay báo "vắng" oan | tăng `grace_s`; thêm mẫu cam trần; che khuất lâu → tăng `min_absence_s` |
| Mất dữ liệu sau khi Space khởi động lại | chưa bật Persistent storage |
| HF 401/403 từ client | Space private: đặt `HF_TOKEN` |
| Server chậm | dùng `--skip` lớn hơn ở room client; giảm `det_size_room`; nâng phần cứng |
