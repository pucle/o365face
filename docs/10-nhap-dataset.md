# Nhập dataset đã thu sẵn của CLB

Dành cho trường hợp CLB đã nhờ từng thành viên tự quay/chụp theo hướng dẫn: **nhìn chính diện → quay trái ~45° → quay phải ~45° → ngẩng ~45° → cúi ~45°** (ảnh hoặc video, mỗi người một bộ).

## Cấu trúc thư mục
```
dataset/
  Nguyen Van An/   chinh_dien.jpg  trai.jpg  phai.jpg  video_xoay.mp4
  Tran Binh/       ...
```
Tên thư mục = **tên hoặc mã** thành viên (không phân biệt hoa/thường và dấu: `Tran Binh` khớp `Trần Bình`). Không khớp ai → tạo thành viên mới (mã = tên bỏ dấu, gạch dưới). Có thể chọn thư mục gốc chứa các thư mục thành viên, hoặc chính thư mục của một người.

## Cách 1 — Giao diện: trang **Nhập dataset**
1. Chọn thư mục dataset (Chrome/Edge/Firefox/Safari trên máy tính). Bảng xem trước cho biết mỗi thư mục khớp ai, bao nhiêu ảnh/video, cảnh báo HEIC/ít dữ liệu; sửa lại thành viên ở menu từng dòng nếu khớp sai.
2. Bấm **Nhập vào hệ thống**. Video được cắt khung ngay trên trình duyệt (~0,3 s/khung, tối đa 40).
3. Kết quả từng người: số ảnh lưu, lý do ảnh bị bỏ, độ phủ góc và các góc còn thiếu.
Chọn nhiều file của **một** người: ô "chọn nhiều file cho một người", rồi chọn thành viên ở bảng.

## Cách 2 — Dòng lệnh (thư mục hoặc .zip, video lớn, nhiều người)
```bash
python tools/import_dataset.py dataset/ --dry-run                       # xem mapping trước
python tools/import_dataset.py dataset.zip --url https://USER-SPACE.hf.space --token MAT_KHAU
# tuỳ chọn: --target 24 (20-30)  --mode add|replace  --augment auto|off
```
(Space private: đặt `HF_TOKEN`.) Dùng cách này khi video khó đọc trên trình duyệt.

## Hệ thống xử lý gì để dataset sạch
Dùng **đúng bộ chọn mẫu** như đăng ký bằng camera (docs/03): mỗi ảnh/khung video đi qua một lượt phân tích, rồi giữ **20–30 ảnh gốc** (mặc định 24) cân bằng 5 hướng.
| Tình huống | Xử lý |
|---|---|
| Không có mặt / mờ / quá nhỏ / mặt bị cắt khỏi ảnh / độ tin cậy thấp | bỏ (báo lý do) |
| Ảnh có **2 mặt lớn** | bỏ |
| **Ảnh của người khác bỏ nhầm thư mục** (giống thành viên khác ≥ 0,5 và hơn người này ≥ 0,1) | bỏ + cảnh báo nêu tên |
| Ngoại lai so với tâm của cả thư mục | bỏ |
| Quá nhiều ảnh cùng một hướng/gần trùng | giữ mẫu tốt và khác nhau nhất theo hạn mức mỗi hướng |
| Ảnh HEIC | không đọc được: xuất sang JPG |
| Thư mục không lưu được ảnh nào | không tạo thành viên rỗng |
| Người đã có mẫu | mặc định **bổ sung** (đổi sang *Thay thế* nếu muốn) |

### Augmentation: khi nào và làm gì
Chỉ bật **khi chưa đủ dữ liệu**: ít hơn `enroll_min_real` (20) ảnh gốc, hoặc thiếu hướng (< 2 mẫu), hoặc các mẫu thiếu nhất quán. Chỉ áp dụng cho **ảnh đã được chọn**, biến đổi nhẹ: đổi sáng/tối, xoay ±5–10°, dịch/phóng nhẹ, nhiễu + nén JPEG, thu nhỏ rồi phóng lại, mờ nhẹ, che một phần. **Không** bẻ hình học để giả góc quay, **không** chỉnh trực tiếp vector. Ràng buộc: hạt giống cố định (cùng dữ liệu → cùng kết quả); mỗi bản phải có cosine ≥ `aug_min_cos` (0,6) với ảnh gốc và không được giống thành viên khác ≥ 0,5, nếu không bị bỏ; tối đa `aug_max_ratio` (50%) số mẫu gốc và tổng ≤ `aug_cap_total` (60); lưu với `step` có hậu tố `+aug-<loại>`; **không tính** vào độ phủ/tiến độ. Có thể tắt: ô *Augmentation* hoặc `--augment off`.

### Báo cáo mỗi người
Số mẫu gốc giữ, bản lật, bản augmentation (và bản bị bỏ + lý do), lý do bỏ ảnh, mẫu theo 5 hướng, kết luận **"Đủ tin cậy"** hoặc **"Nên bổ sung: <hướng>"** (kèm lời khuyên quay thêm ở hướng nào), kiểm tra chéo.

## Mẹo
* Cam trần hay thấy mặt cúi từ trên xuống, nên bộ **cúi ~45°** quan trọng nhất.
* Người "Nên bổ sung": dùng **Đăng ký mặt** (bổ sung) hoặc nhập thêm video ở hướng đó.
* API dành cho dataset lớn: `POST /api/enroll/session` (kind=dataset) → `/frames` (nhiều ảnh mỗi lần) → `/finish` (commit=true). `POST /api/enroll/dataset` vẫn nhận tất cả ảnh trong một yêu cầu (tương thích; `per_cell`, `max_keep`, `occ`, `dedup` không còn tác dụng).
* Quy định dữ liệu sinh trắc: docs/07. Lưu bằng chứng đồng ý ngoài hệ thống.
