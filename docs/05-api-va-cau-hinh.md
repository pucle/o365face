# API & cấu hình

Mọi API (trừ `/health`) cần header `X-API-Token: <API_TOKEN>`. Thiếu `API_TOKEN` trên server = từ chối tất cả (an toàn mặc định). Tài liệu tương tác: `/docs`.

## Biến môi trường (server)
`API_TOKEN` (bắt buộc) · `DATA_DIR` (mặc định `/data` nếu có, ngược lại `./data`) · `INSIGHTFACE_HOME` · `TZ_NAME` (mặc định Asia/Ho_Chi_Minh; thiếu tzdata → UTC+7) · `CHECKIN_THRESHOLD`, `CHECKIN_MARGIN`, `CHECKIN_VOTES`, `ROOM_THRESHOLD`, `GRACE_S`, `MIN_ABSENCE_S` (giá trị khởi tạo; cài đặt lưu trong UI ưu tiên hơn).

## Endpoint chính
| | |
|---|---|
| `GET /health` | tình trạng |
| `GET/POST /api/members`, `GET/DELETE /api/members/{id}`, `DELETE /api/members/{id}/embeddings` | thành viên; có thêm `real`, `flips`, `aug`, `club` (số mẫu mỗi hướng), `target`, `progress`, `complete`, `club_missing` |
| `POST /api/pose` (ảnh) | phát hiện nhanh + góc đầu, không embedding |
| `POST /api/enroll/session` {member_id, name?, mode=add\|replace, kind=live\|dataset, source} | mở phiên đăng ký CLB → `sid` |
| `POST /api/enroll/session/{sid}/frames` (`files`, 1 hoặc nhiều ảnh) | mỗi ảnh: `state` (ok, no_face, multi, far, blurry, between…), `dir`, `pitch`, `yaw`, `box`, `kept`, `fid`; kèm `counts`, `warning` |
| `POST /api/enroll/session/{sid}/reset?direction=` | xoá ứng viên của một hướng (hoặc tất cả) |
| `POST /api/enroll/session/{sid}/finish` {target 20-30, flip, augment=auto\|off\|force, verify, commit} | chọn mẫu + báo cáo; commit=true ghi luôn |
| `POST /api/enroll/session/{sid}/commit`, `DELETE /api/enroll/session/{sid}` | ghi DB một lần / huỷ phiên |
| `POST /api/enroll/undo` {member_id, img_ids} | hoàn tác một lần lưu |
| `POST /api/enroll/dataset` | nhập dataset trong một yêu cầu (dùng chung bộ chọn mẫu) |
| `POST /api/enroll/frame` | lưu 1 khung (member_id, source=door\|room, step, flip, dedup) |
| `POST /api/enroll/batch` | nhiều ảnh (max_keep, dedup) |
| `POST /api/recognize` | nhận diện mọi mặt, trả lý do; `stranger=true` lưu mẫu người lạ |
| `POST /api/checkin` | burst nhiều ảnh → bỏ phiếu → check-in |
| `POST /api/room/frame` | cả khung cam trần |
| `POST /api/room/identify` | crop theo track (`track_ids` + `files`) |
| `POST /api/room/update` | báo số người/ai đang thấy, trả danh sách chờ gán |
| `GET /api/status` | tổng quan |
| `GET/POST /api/shifts`, `DELETE /api/shifts/{id}` | ca trực |
| `GET /api/report`, `/api/report.csv` | báo cáo ngày (`?day=YYYY-MM-DD`) |
| `GET /api/calibration`, `GET/POST /api/settings`, `DELETE /api/strangers`, `GET /api/backup` | hiệu chỉnh, cài đặt |
Các đường dẫn cũ (`/members`, `/enroll`, `/checkin`, `/observe`, `/shifts`, `/report`, `/backup`) vẫn dùng được.

## Cấu hình đăng ký (Cài đặt hoặc `POST /api/settings`)
| Khoá | Mặc định | Ý nghĩa |
|---|---|---|
| `enroll_target` | 24 (20–30) | số mẫu gốc giữ lại mỗi lần đăng ký |
| `enroll_min_per_dir` | 2 | tối thiểu mỗi hướng |
| `enroll_min_real` | 20 | ít hơn mức này = "chưa đủ" (dataset: bật augmentation) |
| `enroll_min_det`, `enroll_min_width`, `enroll_min_blur` | 0,55 · 70 px · 12 | ngưỡng tối thiểu của một mẫu |
| `enroll_outlier_cos` | 0,30 | cosine tới tâm phiên thấp hơn = loại |
| `enroll_w_det/size/blur/light/pose` | 0,15/0,15/0,25/0,10/0,35 | trọng số điểm chất lượng |
| `aug_min_cos` / `aug_max_ratio` / `aug_cap_total` | 0,60 / 0,5 / 60 | kiểm soát augmentation |
| `det_size_enroll` | 320 | cỡ phát hiện mặt khi đăng ký bằng camera (dataset dùng `det_size_door`) |
Server làm nóng model khi khởi động. Phiên đăng ký lưu trong RAM: khởi động lại server thì mất phiên đang dở (không mất dữ liệu đã lưu).
