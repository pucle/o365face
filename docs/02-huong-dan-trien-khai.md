# Hướng dẫn triển khai từng bước

## Bước 1 — Chạy trên máy bạn
Xem README. Kiểm tra `http://localhost:7860/health` trả `{"ok":true,...}`.
Nếu lỗi `ZoneInfoNotFoundError`: `pip install tzdata`. Git Bash trên Windows: `source .venv/Scripts/activate`.

## Bước 2 — Đăng ký thành viên (trong UI)
1. *Thành viên* → thêm mã (không dấu, vd `an01`) + tên. **Phải được người đó đồng ý.**
2. *Đăng ký mặt* → chọn người → tích đồng ý → Bắt đầu → làm 5 động tác theo chữ lớn (xem docs/03). Khoảng 20–40 giây/người.
3. Xem lưới độ phủ: ô viền cam là góc còn thiếu cho cam trần.
4. Nên có thêm ảnh/video quay **đúng bằng cam trần thật** (chế độ *Tải video*): cải thiện nhiều nhất cho góc cao.

## Bước 3 — Thử
* *Thử nhận diện*: ngữ cảnh **Cam trần**, thử cúi đầu, nghiêng người; xem điểm và lý do từ chối. Bấm **Lưu mặt là người lạ** khi có người chưa đăng ký đứng trước camera (≥ 5 lượt) rồi vào *Cài đặt* → **Áp dụng ngưỡng đề xuất**.
* *Thử check-in*: bật webcam, đứng trước camera như ở cửa.
* *Ca trực*: thêm ca, rồi dùng client để thấy vắng mặt được ghi.

## Bước 4 — Lên Hugging Face (rẻ nhất, dễ nhất)
1. Tạo Space: SDK **Docker**, để **Private**.
2. Đẩy toàn bộ thư mục này (có `Dockerfile`) lên Space (git hoặc Upload files). Thêm đầu file `README.md` của Space (nếu HF tạo sẵn) đoạn: `sdk: docker` / `app_port: 7860`.
3. *Settings → Variables and secrets*: secret `API_TOKEN` = chuỗi dài ngẫu nhiên. (Tuỳ chọn) `TZ_NAME=Asia/Ho_Chi_Minh`.
4. *Settings → Persistent storage*: bật (nhỏ nhất) → dữ liệu ở `/data` (server tự dùng). Không bật = **mất dữ liệu mỗi lần khởi động lại**.
5. *Settings → Hardware*: **CPU Upgrade** (≈ 0,03 USD/giờ). Chạy 12 h/ngày ≈ 11 USD/tháng nếu tắt ngoài giờ; để 24/7 ≈ 22 USD. (Giá có thể đổi; kiểm tra trên trang Spaces.) CPU Basic miễn phí chậm và **tự ngủ** — chỉ dùng để thử.
6. Tắt/bật theo giờ: `python tools/space_power.py USER/SPACE restart` lúc 7:55 và `pause` lúc 20:05 (Task Scheduler/cron). Space bị pause không tính tiền phần cứng; storage vẫn tính nhỏ.
7. Space Private: client phải gửi thêm `Authorization: Bearer <HF_TOKEN>` — đặt biến môi trường `HF_TOKEN` (client tự thêm). Trình duyệt: đăng nhập HF trước rồi mở URL Space.

Ước lượng tốc độ (CPU, ảnh 640 px): vài trăm ms – ~1 s/khung. Đủ cho check-in và cam trần (chỉ gửi crop người chưa biết, ~mỗi 1,5 s/người).

## Bước 5 — Chạy client
```bat
pip install -r requirements-client.txt
set SERVER_URL=https://USER-SPACE.hf.space
set API_TOKEN=...
set HF_TOKEN=hf_...            :: nếu Space private
python client\door_client.py --source 0 --show
pip install ultralytics
python client\room_client.py --source rtsp://user:pass@ip/stream --door-zone 0,0.5,0.3,1 --show
```
`--door-zone x1,y1,x2,y2` (tỉ lệ 0–1) là vùng trong khung **cam trần** mà người vào cửa xuất hiện đầu tiên: dùng `--show` để canh. Không cần ultralytics: `--mode frame` gửi cả khung mỗi 2 s (nhận diện tốt khi mặt đủ lớn, không có handoff).
Chạy nền khi khởi động Windows: Task Scheduler → "At log on" → chạy lệnh trên.

## Bước 6 — Vận hành hằng ngày
Xem docs/04. Sao lưu CSDL hằng tuần (nút trong *Cài đặt*).
