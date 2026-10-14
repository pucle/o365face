# Kiến trúc

```
 cam cửa ──(burst 4 khung)──►┐                         ┌──► SQLite (/data/club.db): thành viên, vector mặt,
                             │   FastAPI + InsightFace │     ca trực, sự kiện, vắng mặt, cài đặt
 cam trần ─(crop người lạ)──►├─►  SCRFD + ArcFace      │
          ◄─(chờ gán track)──┤    + landmark 3D (góc)  └──► Giao diện web /ui/
 trình duyệt (đăng ký CLB, thử) ────►┘
```
Chỉ **vector 512 chiều** của khuôn mặt được lưu; không lưu ảnh.

## Vì sao danh tính đến chủ yếu từ cam cửa
Nhận diện mặt nhìn từ trên cao (cúi ≥ 22°) hoặc nghiêng (≥ 40°) kém hẳn so với mặt thẳng. Vì vậy:
1. Cam cửa thấy mặt thẳng → check-in chắc chắn → server ghi "chờ gán" (60 s).
2. Cam trần: khi **đúng một** track mới xuất hiện trong vùng cửa (`--door-zone`) trong lúc có người chờ gán → gán danh tính (nguồn `handoff`).
3. Sau đó mặt trên cao vẫn được dùng để **bỏ phiếu sửa sai** (cần `room_votes` = 2 lượt; ngưỡng thấp hơn `room_threshold_high` cho góc cao) và để nhận người chưa check-in.
4. Một người chỉ gắn với một track; track trùng bị gỡ.

## Nhận diện (server/face_engine.py, common/matching.py)
* SCRFD phát hiện + 5 điểm → ArcFace `w600k_r50` → vector chuẩn hoá L2.
* Góc đầu từ `landmark_3d_68`: `pitch<0` cúi, `yaw>0` quay sang **trái của chính người đó**.
* Thư viện nhiều vector/người; điểm = cosine lớn nhất; chấp nhận khi `điểm ≥ ngưỡng` **và** hơn người thứ hai ≥ `margin`.
* Mỗi mẫu đăng ký còn lưu **bản lật ngang** (yaw đổi dấu) → chỉ cần quay một bên.
* Ảnh quá nhỏ không bị phóng to lên `det_size` (làm SCRFD bỏ sót mặt).

## Hiện diện & vắng mặt (common/presence.py)
`PRESENT → AWAY` khi không thấy quá `grace_s`; thời điểm vắng được **lùi về lần cuối thấy**. Khi thấy lại: đóng khoảng vắng; chỉ ghi nếu ≥ `min_absence_s` và chỉ phần **nằm trong ca**. Trạng thái được lưu mỗi 15 s và khôi phục sau khi server khởi động lại (cùng ngày, ≤ 6 giờ).
