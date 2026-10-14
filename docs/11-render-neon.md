# Hướng dẫn deploy chi tiết: Render (free) + Neon Postgres

Mục lục: 0 Tóm tắt · 1 Giới hạn cần biết · 2 Giữ dữ liệu `club.db` cũ · 3 Tạo Neon · 4 Đưa code lên GitHub · 5 Tạo dịch vụ Render · 6 Kiểm tra · 7 Giai đoạn 1: thu thập khuôn mặt · 8 Giai đoạn 2: điểm danh đầy đủ · 9 Cam ở CLB · 10 Sao lưu · 11 Xử lý sự cố · 12 Chưa kiểm chứng

## 0. Tóm tắt
Neon lưu **toàn bộ dữ liệu** (thành viên, vector khuôn mặt, ca trực, check-in, cảnh báo, cấu hình). Render chỉ chạy code, không giữ gì trên đĩa. Hai giai đoạn dùng **cùng một dịch vụ Render và cùng CSDL**, chỉ đổi 2 biến môi trường:

| | `APP_ENTRY` | `APP_MODE` | Làm được |
|---|---|---|---|
| Giai đoạn 1 | `server.enroll_app:app` | `enroll` | Thành viên, đăng ký mặt, nhập dataset, xuất dữ liệu |
| Giai đoạn 2 | `server.app:app` | `full` | Thêm cam cửa, cam trần, ca trực, báo cáo, cảnh báo |

## 1. Giới hạn cần biết (đã đo / đã đọc tài liệu)
- Render free: **512 MB RAM**; tự ngủ sau **15 phút** không có truy cập, đánh thức mất khoảng **1 phút**; **ổ đĩa mất khi restart/redeploy**; 750 giờ chạy/tháng (dịch vụ ngủ không tính giờ); Render có thể restart bất kỳ lúc nào.
- RAM đo trên máy thử (Python 3.13): `buffalo_l` + model góc đầu 3D ≈ **770 MB** → không chạy nổi; chế độ **lite** (`buffalo_s`, không model 3D, 1 luồng) ≈ **230–250 MB**, giữ phẳng sau 480 khung đăng ký liên tiếp.
- Hệ quả của lite:
  1. Vector `buffalo_s` **khác** vector `buffalo_l` → **không dùng chung được**; server từ chối chạy khi CSDL chứa vector của model khác.
  2. Góc đầu **ước lượng từ 5 điểm mốc**: yaw khá ổn, **pitch kém** (ngẩng/cúi lệch tới ±10°). Bước "ngẩng/cúi ~45°" kém tin cậy hơn bản 3D.
  3. Độ chính xác nhận diện thấp hơn `buffalo_l`: sau khi có dữ liệu, hiệu chỉnh ngưỡng ở trang *Cài đặt*.
  4. CPU gói free yếu hơn máy thử nhiều: mỗi khung hình có thể chậm hơn rất nhiều (chưa đo).
- Chỉ lưu **vector đặc trưng** (2 KB/mẫu), **không lưu ảnh**. 100 người × 24 mẫu ≈ 5 MB, Neon free 1 GB là dư.

## 2. Giữ dữ liệu `club.db` cũ — đọc kỹ trước khi làm
`club.db` chứa 2 loại dữ liệu, xử lý khác nhau:

| Dữ liệu | Giữ được? |
|---|---|
| Thành viên, ca trực, lịch sử check-in, vắng mặt, cài đặt/ngưỡng | **Giữ được** — chuyển sang Neon |
| **Vector khuôn mặt** (đăng ký bằng `buffalo_l`) | **Không dùng được với lite** → phải đăng ký lại (nhanh, ~1 phút/người) |

Nếu bạn muốn **giữ cả vector cũ**, chỉ có một cách: chạy bằng `buffalo_l` (cần ≥ ~1 GB RAM, tức gói Render trả phí hoặc máy khác) và bỏ lite. Khi đó bỏ `LITE_MODE`, đặt `MODEL_NAME=buffalo_l` và chuyển **đủ** dữ liệu (không dùng `--no-embeddings`).

**Cách lấy `club.db` cũ**
- Từ Hugging Face Space có persistent storage: vào tab *Files* của Space, mở thư mục `data` (hoặc `/data`) và tải `club.db`; hoặc mở UI cũ → *Cài đặt* → **Tải sao lưu CSDL**; hoặc `curl -H "X-API-Token: TOKEN" https://<space>.hf.space/api/backup -o club.db`.
- Từ máy local: tệp `data/club.db` trong thư mục project.
- Đặt tệp đó vào một thư mục **tên đúng là `club.db`** (ví dụ `D:\club-old\club.db`).

**Cách chuyển sang Neon (sau khi làm mục 3)**
```
pip install "psycopg[binary]" requests
```
PowerShell:
```
$env:DATABASE_URL="postgresql://...neon..."
python tools/db_check.py
python tools/migrate_db.py --from-sqlite D:\club-old\club.db --to-url $env:DATABASE_URL --no-embeddings
```
cmd:
```
set "DATABASE_URL=postgresql://...neon..."
python tools\db_check.py
python tools\migrate_db.py --from-sqlite D:\club-old\club.db --to-url "%DATABASE_URL%" --no-embeddings
```
Git Bash:
```
export DATABASE_URL='postgresql://...neon...'
python tools/db_check.py
python tools/migrate_db.py --from-sqlite /d/club-old/club.db --to-url "$DATABASE_URL" --no-embeddings
```
- `--no-embeddings` bỏ vector cũ (và mẫu người lạ, trạng thái hiện diện tạm), **giữ** mọi thứ còn lại.
- Mặc định lệnh **không ghi đè**: nếu Neon đã có dữ liệu nó dừng lại; thêm `--replace` nếu chắc chắn muốn thay.
- Đừng sửa/xoá `club.db` cũ cho tới khi mọi thứ chạy ổn: đó là bản sao lưu của bạn. Có thể xuất thêm JSON: `python tools/migrate_db.py --from-sqlite club.db --to-json backup-cu.json` (chứa vector, giữ kín).
- Sau khi chuyển, danh sách thành viên đã có sẵn, chỉ cần đăng ký lại khuôn mặt cho từng người (mục 7); đăng ký sẽ **bổ sung** vào thành viên đó, không tạo trùng.

## 3. Tạo Neon
1. Vào neon.tech, đăng ký, **Create project** (region gần nhất, ví dụ Singapore). Tên CSDL mặc định `neondb` là được.
2. Bấm **Connect** → bật **Connection pooling** (chuỗi có `-pooler` trong tên máy chủ) → copy chuỗi dạng `postgresql://user:matkhau@ep-xxxx-pooler.region.aws.neon.tech/neondb?sslmode=require`.
3. Kiểm tra từ máy bạn: chạy `python tools/db_check.py` (lệnh ở mục 2). Kết quả mong đợi: dòng "Kết nối + tạo bảng", "Ghi / đọc / xoá thử: OK". Lần đầu có thể chậm vài giây vì Neon đang "thức dậy".
4. Giới hạn Neon free cần nhớ: 1 GB dữ liệu; compute tự tắt sau 5 phút không dùng; có hạn mức giờ compute mỗi tháng. Server đã được chỉnh để **ít ghi DB** (chỉ ghi khi có thay đổi) để Neon được ngủ.
5. **Không bao giờ** đưa chuỗi kết nối lên GitHub hay gửi cho người khác; nếu lộ, vào Neon → đổi mật khẩu role.

## 4. Đưa code lên GitHub
1. Giải nén bản zip, vào thư mục `club-attendance`.
2. Tạo repo **private** trên GitHub (khuyến nghị, vì chứa logic hệ thống).
3. Trong thư mục project:
```
git init
git add .
git commit -m "club attendance"
git branch -M main
git remote add origin https://github.com/<ten>/<repo>.git
git push -u origin main
```
4. Kiểm tra `.gitignore`/`.dockerignore` đã loại `data/`. Không có `club.db`, token hay chuỗi kết nối trong repo.

## 5. Tạo dịch vụ trên Render
**Cách A — Blueprint (nhanh):** Render → *New* → *Blueprint* → kết nối GitHub, chọn repo → Render đọc `render.yaml`. Khi được hỏi, điền:
- `API_TOKEN`: một chuỗi dài ngẫu nhiên (ví dụ 32+ ký tự). Đây là "mật khẩu" của hệ thống, UI sẽ hỏi.
- `DATABASE_URL`: chuỗi Neon ở mục 3.

**Cách B — thủ công:** *New* → *Web Service* → chọn repo → *Language/Runtime*: **Docker** → *Dockerfile Path*: `./Dockerfile.render` → *Instance Type*: **Free** → *Health Check Path*: `/health` → thêm biến môi trường:

| Biến | Giá trị |
|---|---|
| `API_TOKEN` | chuỗi ngẫu nhiên dài |
| `DATABASE_URL` | chuỗi Neon |
| `APP_ENTRY` | `server.enroll_app:app` |
| `APP_MODE` | `enroll` |
| `LITE_MODE` | `1` |
| `MODEL_NAME` | `buffalo_s` |
| `TZ_NAME` | `Asia/Ho_Chi_Minh` |

Bấm *Create*. Lần build đầu mất vài phút (cài thư viện, tải model `buffalo_s` rồi xoá 3 file model không dùng).

## 6. Kiểm tra sau khi deploy
1. Mở `https://<tên-dịch-vụ>.onrender.com/health`. Cần thấy: `"ok":true`, `"model":"buffalo_s"`, `"db":"postgres"`, `"mode":"enroll"`, `"lite":true`, `rss_mb` khoảng 200–260.
2. Mở `/ui/`, bấm nút **Token**, nhập `API_TOKEN`. Chấm trạng thái xanh = kết nối được. *Cài đặt* → **Kiểm tra kết nối** cũng báo model, số người, số mẫu.
3. Thử một thành viên (mục 7). Sau đó vào Neon → *Tables* sẽ thấy dữ liệu trong bảng `members` và `embeddings`.
4. Nếu `/health` báo lỗi hoặc dịch vụ bị restart liên tục: xem mục 11.

## 7. Giai đoạn 1 — thu thập khuôn mặt thành viên
1. Mở `/ui/` → **Thành viên** → thêm từng người (mã không dấu, tên hiển thị). Nếu đã chuyển dữ liệu cũ ở mục 2 thì danh sách có sẵn.
2. **Đăng ký mặt** → chọn người → *Bắt đầu*: nhìn thẳng, rồi quay trái ~45°, phải ~45°, ngẩng, cúi theo mũi tên; hệ thống chọn 20–30 mẫu tốt nhất và chỉ ghi **một lần** vào Neon khi bạn bấm Lưu. Camera chọn ở trang **Camera**.
3. Có ảnh/video đã chụp sẵn: **Nhập dataset** (hoặc `tools/import_dataset.py`).
4. Mẹo: đủ sáng từ phía trước, cách camera 50–80 cm, một người trong khung, không khẩu trang/kính đen. Vì **pitch kém chính xác ở lite**, nếu mũi tên ngẩng/cúi khó "ăn", cứ tăng độ ngẩng/cúi rõ hơn một chút rồi quan sát; nếu vẫn kẹt, chỉ cần đủ mẫu chính diện/trái/phải và bổ sung ngẩng/cúi bằng nhập dataset.
5. Trang *Thành viên* hiện tiến độ từng người. Chờ khi cả CLB đều "Đủ tin cậy" thì sang giai đoạn 2.
6. Server bận hoặc ngủ: lần mở đầu có thể chờ ~1 phút (Render đang đánh thức); đừng bấm lại liên tục.

## 8. Giai đoạn 2 — điểm danh đầy đủ
1. Render → dịch vụ → **Environment**: đổi `APP_ENTRY` = `server.app:app` và `APP_MODE` = `full`; giữ `LITE_MODE=1`, `MODEL_NAME=buffalo_s`. *Save* → Render tự deploy lại.
2. `/health` giờ phải báo `"mode":"full"`. Các mục *Ca trực*, *Camera*, *Thử nghiệm* xuất hiện lại.
3. Trang **Ca trực**: thêm ca; **Tổng quan** có mục *Lịch sử & cảnh báo* (người lạ ở cửa, người lạ trong phòng, vắng mặt, chưa check-in).
4. Quay lại giai đoạn 1 bất cứ lúc nào bằng cách đổi 2 biến về `server.enroll_app:app` / `enroll`.
5. Nếu thấy nhận diện nhầm/bỏ sót: *Cài đặt* → hiệu chỉnh ngưỡng (có biểu đồ), vì `buffalo_s` có phân bố điểm khác `buffalo_l`.

## 9. Cam ở CLB
- Mỗi cam một việc: trang **Camera** (trình duyệt) chọn camera cho *Đăng ký*, *Cửa*, *Nhận diện*; phần "Nguồn cho client Python" lưu số webcam hoặc `rtsp://…` cho cam cửa/cam trần.
- Trên máy cố định ở CLB (Python 3.11): `pip install -r requirements-client.txt`, rồi
  `python client/door_client.py --url https://<tên>.onrender.com --token <API_TOKEN>` và `python client/room_client.py --url … --token …` (mặc định `--source auto` lấy nguồn từ trang Camera). Chạy `python client/camera_list.py --save` để biết webcam nào số mấy.
- Vì Render free ngủ khi không có truy cập, cam gửi khung đầu tiên sẽ phải chờ ~1 phút. Trong giờ hoạt động (8h–20h) client gửi liên tục nên dịch vụ sẽ **không ngủ** — bù lại tốn giờ chạy: 12 giờ/ngày × 30 = 360 giờ, nằm trong 750 giờ/tháng.

## 10. Sao lưu và khôi phục
- Sao lưu: UI *Cài đặt* → xuất, hoặc `GET /api/export` (JSON), hoặc `python tools/migrate_db.py --from-url "<Neon>" --to-json backup.json`. File chứa vector khuôn mặt: giữ kín như dữ liệu cá nhân. Neon cũng có lịch sử khôi phục (history/branch) theo gói.
- Khôi phục: `python tools/migrate_db.py --from-json backup.json --to-url "<Neon mới>" [--replace]`.
- Chuyển nhà cung cấp (Neon → Supabase…): xuất JSON rồi nạp vào chuỗi kết nối mới.

## 11. Chống tràn RAM / rò rỉ và xử lý sự cố
**Đã cài sẵn:** 1 worker; ONNX 1 luồng, tắt arena, `MALLOC_ARENA_MAX=2`; ảnh đầu vào tối đa 1280 px; tải lên >8 MB bị từ chối (413); tối đa 2 phiên đăng ký, hết hạn 10 phút, ảnh tạm 640 px, dọn bộ nhớ sau mỗi lần lưu; `memguard` mỗi 15 giây (≥380 MB dọn bộ nhớ, ≥440 MB bỏ phiên treo, ≥480 MB ba lần liên tiếp → thoát để Render khởi động lại sạch — dữ liệu ở Neon nên không mất). Chỉnh ngưỡng bằng `MEM_SOFT_MB`, `MEM_HARD_MB`, `MEM_KILL_MB`; lịch sử cũ hơn 180 ngày tự xoá (`EVENT_KEEP_DAYS`).

| Triệu chứng | Nguyên nhân thường gặp → cách xử |
|---|---|
| Build lỗi khi cài `insightface` | Cần `build-essential` (đã có trong `Dockerfile.render`); xem log build, thử *Clear build cache & deploy* |
| Log: `Out of memory` / dịch vụ restart liên tục | Có mã nguồn/biến làm tăng RAM: kiểm tra `LITE_MODE=1`, `MODEL_NAME=buffalo_s`; xem `rss_mb` ở `/health`; **đừng** dùng `buffalo_l` ở gói free |
| `RuntimeError: CSDL đang chứa vector của model 'buffalo_l'…` | Neon đang có vector cũ. Xoá vector cũ (nạp lại bằng `--no-embeddings --replace`) hoặc dùng project/schema Neon mới. Không nên dùng `ALLOW_MODEL_MISMATCH=1` |
| `Không kết nối được database` | Sai `DATABASE_URL`; thiếu `?sslmode=require`; mật khẩu có ký tự đặc biệt (mã hoá URL); Neon đang ngủ (server tự thử lại 3 lần) |
| UI báo 401/403 | Sai token → bấm *Token*, nhập đúng `API_TOKEN` |
| UI báo lỗi CORS | Chỉ xảy ra khi UI ở tên miền khác; đặt `CORS_ORIGINS=https://tên-ui` |
| Trang mở rất chậm lần đầu | Dịch vụ đang ngủ (≈1 phút) — bình thường ở gói free |
| `/api/checkin` trả 404 | Đang ở giai đoạn 1 (`APP_MODE=enroll`); sang mục 8 |
| Đăng ký mặt chậm/lag | CPU gói free yếu; để một người đăng ký mỗi lần, đóng các tab khác |
| `413 Yêu cầu quá lớn` | Gửi ít ảnh mỗi lần hơn (`MAX_UPLOAD_MB` tăng được nhưng tốn RAM) |

## 12. Chưa kiểm chứng
Chưa chạy thử: Render thật, Neon thật (SQL đã kiểm trên Postgres 16 cục bộ, luồng kết nối kiểm bằng psycopg giả), `docker build` của `Dockerfile.render`, tốc độ trên CPU gói free, độ chính xác góc đầu bằng người thật quay 45°, độ chính xác nhận diện của `buffalo_s` trên dữ liệu CLB.
