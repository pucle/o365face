---
title: Club Attendance
sdk: docker
app_port: 7860
pinned: false
---

# Điểm danh CLB bằng nhận diện khuôn mặt (2 camera)

* **Cam cửa**: chỉ chạy khi có người đến (đúng 1 mặt, đủ to, nhìn thẳng, ổn định 0,7 s) → bỏ phiếu 4 khung → check-in.
* **Cam trần**: theo dõi từng người (YOLO + ByteTrack), đếm số người, biết là ai. Danh tính chủ yếu được **chuyển giao từ cam cửa** (người vừa check-in = track mới xuất hiện ở vùng cửa), sau đó được kiểm chứng bằng mặt nhìn từ trên/nghiêng với ngưỡng riêng cho góc cao.
* **Vắng mặt**: người có ca trực mà rời phòng quá `grace_s` (mặc định 120 s) → tính vắng từ lúc mất dấu; khi quay lại ghi "từ…đến…, N phút", cắt theo ranh giới ca. Người không có ca chỉ check-in và theo dõi hiện diện.
* **Giao diện web** (`/ui/`): đăng ký mặt **kiểu CLB** (5 động tác, tự chụp liên tục, tự chọn 20–30 ảnh tốt nhất), nhập dataset có sẵn, thử nhận diện từ góc cao/nghiêng, thử check-in, ca trực & báo cáo, hiệu chỉnh ngưỡng.

## Chạy thử nhanh trên Windows (5 phút)
Cài đặt (chung cho mọi shell; Git Bash dùng `source .venv/Scripts/activate`):
```bat
py -3.11 -m venv .venv
.venv\Scripts\activate
pip install -r requirements-server.txt
```
Đặt mật khẩu API rồi chạy (**mỗi shell một cú pháp**, đặt sai cú pháp thì server báo chưa có token):
```powershell
# PowerShell
$env:API_TOKEN = "mat-khau-cua-ban"; uvicorn server.app:app --port 7860
```
```bat
:: cmd
set "API_TOKEN=mat-khau-cua-ban"
uvicorn server.app:app --port 7860
```
```bash
# Git Bash
export API_TOKEN=mat-khau-cua-ban
uvicorn server.app:app --port 7860
```
Mở **http://localhost:7860/** → **Token** → nhập `API_TOKEN` → *Thành viên* → thêm người → *Đăng ký mặt*. Webcam trong trình duyệt chỉ chạy trên `localhost` hoặc HTTPS (Hugging Face Space là HTTPS). Lần đầu InsightFace tự tải model `buffalo_l` (~280 MB).

## Cách dùng: đăng ký khuôn mặt theo quy trình CLB
1. Trang **Đăng ký mặt** → chọn thành viên (người chưa đủ mẫu nằm đầu danh sách) → **Bắt đầu**.
2. Đếm 3-2-1, rồi làm theo chữ lớn + mũi tên, hệ thống **tự chuyển** 5 chặng, không cần bấm chụp: **nhìn thẳng → quay trái ~45° → quay phải ~45° → ngẩng ~45° → cúi ~45°**. Mỗi chặng ~3–5 s, vòng tròn trên thẻ chặng đầy là xong.
3. Màn kết quả: số mẫu giữ lại theo từng hướng (ảnh nhỏ chỉ nằm trong trình duyệt), kiểm tra chéo, kết luận **"Đủ tin cậy"** hoặc **"Nên bổ sung: <hướng>"**. Bấm **Lưu**; hướng yếu thì **Làm lại hướng yếu**. Có nút **Đăng ký người tiếp theo** và **Hoàn tác**.
4. Server nhận khung hình liên tục, chấm điểm (độ nét, kích thước, ánh sáng, độ tin cậy, gần góc đích), loại ngoại lai/người lạ, rồi giữ **20–30 ảnh gốc (mặc định 24)**: 8 chính diện + 4 mỗi hướng còn lại, kèm bản lật. **Đăng ký lại = bổ sung** vào mẫu đã có (muốn thay hẳn: *Nâng cao → Thay thế mẫu cũ*). Chỉ lưu vector, không lưu ảnh.

Mẹo: ngồi cách camera 50–80 cm, mặt đủ sáng từ phía trước (không ngược sáng), chỉ một người trong khung, bỏ khẩu trang/kính đen; quay đầu **chậm** và đủ góc (nếu "quay quá" mũi tên sẽ kéo về); camera ngang tầm mắt. Có sẵn ảnh/video của CLB: trang **Nhập dataset** hoặc `python tools/import_dataset.py dataset/` (cùng bộ chọn mẫu; **chỉ khi thiếu dữ liệu** mới bù augmentation nhẹ, có đánh dấu, tối đa 50% số mẫu gốc, không tính vào độ phủ góc). Chi tiết: docs/03 và docs/10.

## Cách test
```bash
python -m unittest discover -s tests -p "test_*.py"     # unit test Python (chọn mẫu, augmentation, phiên, cấu hình...)
node tests/guide.test.js                                 # logic 5 chặng + khớp góc với Python
```
Cần server + model thật (chạy server trước, token `dev`):
```bash
python tools/integration_real.py ANH_NHIEU_NGUOI.jpg http://127.0.0.1:7860 dev   # API + model thật + phiên đăng ký
python tests/e2e/ui_e2e.py  cam.y4m  http://127.0.0.1:7860 dev ./shots            # trình duyệt thật, camera giả
python tests/e2e/club_e2e.py cam.y4m http://127.0.0.1:7860 dev ./shots            # 5 chặng (xoay đầu giả lập), điện thoại dọc
python tests/e2e/import_e2e.py THU_MUC_DATASET http://127.0.0.1:7860 dev ./shots  # trang Nhập dataset
python tools/smoke_test.py http://127.0.0.1:7860 --token dev                      # sau mỗi lần deploy
python tools/bench_enroll.py --token dev --video clip.mp4                         # đo thời gian đăng ký
```
(e2e cần `pip install playwright` và Chromium; chạy trên server **mới**, dữ liệu trống.) **Checklist thủ công** với người thật: ① thiếu sáng ② đeo kính ③ quay quá 45° (mũi tên có kéo về không) ④ 2 người trong khung (phải báo, không lưu) ⑤ chọn nhầm người (phải cảnh báo "giống X") ⑥ đăng ký lại cùng người (số mẫu tăng, không mất mẫu cũ) ⑦ thử *Thử nhận diện* sau khi lưu. Phần nào đã test thật/chưa: docs/08.

## Cách deploy
* **Docker/local**: `docker build -t club . && docker run -p 7860:7860 -e API_TOKEN=... -v club-data:/data club`.
* **Hugging Face** (khuyến nghị): `export HF_TOKEN=hf_xxx` (PowerShell `$env:HF_TOKEN="hf_xxx"`, cmd `set "HF_TOKEN=hf_xxx"`), rồi `python tools/deploy_hf.py USER/club-attendance --api-token MAT_KHAU` (thêm `--dry-run` để xem trước). Kiểm: `python tools/smoke_test.py https://USER-club-attendance.hf.space --token MAT_KHAU --hf-token $HF_TOKEN`.
* **Vercel** (chỉ UI + proxy): `python deploy/vercel/build.py`, `cd deploy/vercel`, `npx vercel`, đặt `BACKEND_URL` (+ `HF_TOKEN` nếu Space private), `npx vercel --prod`.
* **Biến môi trường**: `API_TOKEN` (bắt buộc), `DATA_DIR` (nơi lưu DB; trên HF bật persistent storage → `/data`), `MODEL_NAME` (`buffalo_l` hoặc `buffalo_s`), `CORS_ORIGINS` (khi UI ở domain khác, không dùng proxy), `TZ_NAME`. **Sao lưu**: `GET /api/backup` (hoặc nút ở trang Cài đặt) — làm trước khi đổi/tắt Space. Chi tiết: docs/09.

## Tài liệu
| File | Nội dung |
|---|---|
| [docs/01-kien-truc.md](docs/01-kien-truc.md) | Kiến trúc, luồng dữ liệu, máy trạng thái hiện diện |
| [docs/02-huong-dan-trien-khai.md](docs/02-huong-dan-trien-khai.md) | **Làm theo từng bước**: cài đặt → đăng ký → thử → lên Hugging Face → chạy client |
| [docs/03-giao-dien-va-dang-ky.md](docs/03-giao-dien-va-dang-ky.md) | Đăng ký kiểu CLB: 5 chặng, chọn 20–30 mẫu, kết quả, đặt camera |
| [docs/04-hieu-chinh-va-van-hanh.md](docs/04-hieu-chinh-va-van-hanh.md) | Ngưỡng, hiệu chỉnh, bật/tắt theo giờ, sao lưu |
| [docs/05-api-va-cau-hinh.md](docs/05-api-va-cau-hinh.md) | API, biến môi trường, tham số |
| [docs/06-xu-ly-su-co.md](docs/06-xu-ly-su-co.md) | Lỗi thường gặp |
| [docs/07-rieng-tu-va-giay-phep.md](docs/07-rieng-tu-va-giay-phep.md) | Dữ liệu sinh trắc, đồng ý, **giấy phép model** |
| [docs/09-trien-khai-hf-vercel.md](docs/09-trien-khai-hf-vercel.md) | Lệnh deploy Hugging Face, UI trên Vercel, smoke test |
| [docs/10-nhap-dataset.md](docs/10-nhap-dataset.md) | **Nhập dataset ảnh/video đã thu của thành viên** (thẳng, ±45°, ngẩng/cúi) |
| [docs/11-render-neon.md](docs/11-render-neon.md) | **Deploy Render free + Neon Postgres** (chế độ lite 512 MB, giai đoạn 1 chỉ thu thập khuôn mặt, chống OOM) |
| [docs/08-kiem-thu.md](docs/08-kiem-thu.md) | Cái gì đã test thật, cái gì **chưa** |

## Cấu trúc
`common/` logic thuần (hiện diện, ghép mặt, góc, hiệu chỉnh, pipeline cam trần) · `server/` FastAPI + InsightFace + SQLite + UI (`server/static`) · `client/` cam cửa, cam trần · `tools/` đăng ký hàng loạt, bật/tắt Space, test tích hợp · `tests/` unit + E2E.
