# Giao diện & đăng ký khuôn mặt (quy trình CLB)

## Một màn hình, 5 động tác
Trang **Đăng ký mặt**: chọn thành viên → **Bắt đầu**. Đếm 3-2-1 rồi hệ thống tự chạy 5 chặng, **chụp liên tục**, không cần bấm:
**nhìn chính diện → quay trái ~45° → quay phải ~45° → ngẩng ~45° → cúi ~45°.**
* Hàng thẻ 5 chặng trên cùng có vòng tiến độ; chặng đang làm được viền đậm, xong thì xanh, hết giờ mà thiếu thì vàng ("yếu").
* **Một dòng chữ lớn + mũi tên** cho biết cần làm gì; khung camera nháy xanh khi giữ được ảnh tốt. Xem trước lật gương: quay sang trái của bạn thì mũi tên/đầu sang trái màn hình.
* Chặng kết thúc khi đủ ảnh tốt (và đã giữ ≥ ~2 s) hoặc hết ~9 s. Nút: **Làm lại bước này**, **Làm lại từ đầu**, **Dừng**.
* Thông báo lỗi dễ hiểu: "Chưa thấy mặt: ngồi chính giữa khung hình", "Lại gần camera hơn", "Hình bị nhòe", "Có 2 người trong khung", "Có vẻ là người khác"…, và "Khuôn mặt này giống <người khác> hơn…" nếu chọn nhầm người.
* **Nâng cao** (đóng sẵn): số mẫu giữ lại 20–30, *Bổ sung/Thay thế* khi đăng ký lại, camera, giọng nói.

## Server làm gì với các khung hình
Mỗi khung (ảnh ≤ 560 px, JPEG 0,75, một yêu cầu tại một thời điểm) được xử lý **một lần**: phát hiện + góc đầu + embedding (chỉ khi đạt chất lượng và nằm trong cửa sổ một hướng). Ứng viên tốt nằm trong **RAM** của phiên (tối đa 30/hướng, hết hạn sau 20 phút, tối đa 8 phiên), không ghi đĩa. Khi kết thúc:
1. Bỏ khung giống thành viên khác hơn người này (cảnh báo), bỏ ngoại lai so với tâm của phiên (và mẫu cũ khi bổ sung).
2. Chọn **20–30 ảnh gốc (mặc định 24)**: 8 chính diện + 4 mỗi hướng, tối thiểu 2 mỗi hướng; chọn tham lam theo điểm chất lượng × độ khác biệt (embedding + góc), bỏ khung gần trùng.
3. Tính bản lật chỉ cho ảnh đã chọn; kiểm tra chéo (leave-one-out: mỗi mẫu có nhận đúng người, hơn người khác ≥ `door_margin`?).
4. Ghi DB **một lần** khi bấm **Lưu**. Điểm chất lượng = độ tin cậy phát hiện, kích thước, độ nét, ánh sáng, gần góc đích (trọng số `enroll_w_*` trong Cài đặt).

**Đăng ký lại là bổ sung**: mẫu cũ giữ nguyên, mẫu mới thêm vào (khung quá giống mẫu cũ bị bỏ). **Hoàn tác** xoá đúng lần lưu vừa rồi (chỉ ở chế độ bổ sung).

## Màn kết quả
Số mẫu theo 5 hướng (hướng < 2 mẫu = "thiếu"), ảnh nhỏ chỉ giữ trong trình duyệt, tỉ lệ kiểm tra chéo, khung bị loại và lý do, kết luận **"Đủ tin cậy"** hoặc **"Nên bổ sung: <hướng>"**. Nút: **Lưu**, **Làm lại hướng yếu** (chỉ chạy lại các hướng thiếu/yếu trong cùng phiên), **Bỏ, làm lại từ đầu**, sau khi lưu: **Đăng ký người tiếp theo**.

## Trang Thành viên
Mỗi người: thanh tiến độ **số mẫu gốc / mục tiêu** (không tính bản lật/augmentation), 5 chip theo hướng, "Cần bổ sung: …". Người chưa đủ nằm đầu danh sách.

## Đặt camera và mẹo
Ngang tầm mắt, cách 50–80 cm, sáng từ phía trước, một người, quay chậm. Cam cửa: ~1,5 m, hướng về người vào, tránh ngược sáng. Cam trần: cao 2,3–2,8 m, nghiêng xuống ~30–45°, mặt ≥ 40 px. Webcam laptop không tái tạo góc nhìn từ trần: nếu cần, quay video bằng chính cam trần và dùng **Nhập dataset**.

## Các trang khác
* **Tổng quan**, **Ca trực**, **Cài đặt** (có nhóm tham số đăng ký `enroll_*`, `aug_*`).
* Menu **Thử nghiệm**: *Thử nhận diện* (xanh = nhận ra, cam = chưa chắc, đỏ = lạ) và *Thử check-in*.
