# Kiểm thử — đã làm và chưa làm

## Đã chạy thật (trong môi trường phát triển, Linux, Python 3.13, CPU)
* 108 unit test (hiện diện/vắng mặt, ghép mặt, góc, hiệu chỉnh, định danh theo track, pipeline cam trần, cấu hình, **chọn mẫu 20–30/hạn mức hướng/ngoại lai/đa dạng, quyết định augmentation, trần 50%, bỏ bản cosine thấp, đánh dấu `+aug-`, phiên RAM/TTL, kiểm tra chéo**): `python -m unittest discover -s tests -p "test_*.py"`.
* 21 nhóm test Node (cò check-in, Sweep cũ, **ClubScan 5 chặng, mũi tên theo màn hình lật gương, cửa sổ hướng khớp Python**), đối chiếu phân ô góc và hướng CLB với Python trên 2074 điểm: `node tests/guide.test.js`.
* `tools/integration_real.py`: server thật + **InsightFace 0.7.3 buffalo_l thật** — tạo thành viên, góc đầu, đăng ký (frame + batch), nhận diện với ảnh bị mờ/tối/lật/thu nhỏ/nén dẹt, check-in burst (từ chối góc quá lệch), cam trần, hiệu chỉnh, cài đặt, ca trực, báo cáo, sao lưu, xác thực: **tất cả đạt**.
* `tests/e2e/ui_e2e.py`: Chromium thật + camera giả + server/model thật: đăng ký CLB (cần đồng ý, chặng chính diện tự chụp liên tục, hết giờ các chặng sau thì báo yếu, kết quả, Lưu, tiến độ ở trang Thành viên), Thử nhận diện nhận đúng người, check-in cửa, ca trực, tổng quan, cài đặt; không lỗi JS.
* `client/door_client.py` và `client/room_client.py --mode frame` chạy với video thật.

## Chưa kiểm chứng
* **Chưa thử với camera, người và phòng thật của CLB** — đặc biệt độ chính xác ở góc cao/nghiêng. Số liệu mặc định là điểm khởi đầu; hãy hiệu chỉnh.
* Dữ liệu thử chỉ có vài khuôn mặt từ ảnh mẫu; quy trình xoay đầu được thử logic và chặng thẳng, **chưa thử cúi/nghiêng bằng người thật** (cần camera thật).
* `room_client.py --mode yolo` (ultralytics/ByteTrack) **chưa chạy** (sandbox không cài được); phần logic gán/bỏ phiếu đã có unit test.
* Chưa deploy lên Hugging Face thật; Dockerfile chưa build; môi trường Windows/Python 3.11/OpenCV 4.x chưa thử (môi trường dev khác).
* Tốc độ trên CPU của Hugging Face chưa đo.

## Bổ sung (quét Face ID, deploy)
* `tests/guide.test.js` có 15 nhóm test, gồm Sweep (vòng tròn, nhiều tầng, từ chối, duplicate). (đã thay bằng `club_e2e.py`; trước đây `sweep_e2e.py` giả lập pose đi theo vòng tròn) (camera giả chỉ là ảnh tĩnh), phần lưu ảnh dùng server thật → xác nhận logic quét/tổng kết, **chưa** xác nhận cảm giác quét bằng đầu người thật.
* Mẫu "khuất mặt" là mô phỏng (che nửa dưới/thu nhỏ); lợi ích thực tế phải đo bằng người thật trong phòng.
* `tools/smoke_test.py` chạy thật với server local. `deploy/vercel/test_proxy.mjs` chạy thật với hàm proxy Node. **`tools/deploy_hf.py` mới chạy `--dry-run`** (không có mạng/token Hugging Face ở đây); **Vercel CLI chưa chạy**.

## Nhập dataset
* Chạy thật với dataset tổng hợp: thư mục có/không khớp theo tên bỏ dấu, ảnh nhầm người, ảnh 2 mặt, ảnh không mặt, HEIC; CLI (`tools/import_dataset.py`) và trang UI (`tests/e2e/import_e2e.py`, chọn thư mục thật trong Chromium), kể cả cắt khung video .webm trên trình duyệt.
* **Chưa thử với dataset thật của CLB** (ảnh/video điện thoại, ±45°): dữ liệu thử chỉ là vài khuôn mặt tĩnh, nên chưa đo được tỉ lệ ảnh được giữ ở các góc 45°. Video mp4/H.264 phụ thuộc trình duyệt; nếu không đọc được UI sẽ báo và hãy dùng CLI.

## Đăng ký kiểu CLB (bản này)
* **Đã chạy thật** (server + InsightFace buffalo_l thật, CPU 2 vCPU): `tools/integration_real.py` (phiên dataset: bổ sung vào người đã có, chặn ảnh người khác, augmentation tự bật khi thiếu và có trần, aug=off, hoàn tác, 404 phiên hết hạn, `/api/enroll/dataset` cũ), `tests/e2e/ui_e2e.py`, `tests/e2e/import_e2e.py`, `tools/smoke_test.py`, CLI `tools/import_dataset.py`.
* `tests/e2e/club_e2e.py` (thay `sweep_e2e.py`): **chặng chính diện chạy server thật; các chặng quay trái/phải/ngẩng/cúi dùng phản hồi giả lập** (camera giả chỉ là ảnh tĩnh): kiểm đếm ngược, chuyển chặng, "Làm lại bước này", "Làm lại hướng yếu", Lưu, Hoàn tác, giao diện điện thoại dọc không tràn ngang. **Không chứng minh** cảm giác quay đầu thật.
* **Đo thời gian** (sandbox 2 vCPU, không GPU, ảnh 640 px; `tools/bench_enroll.py`): đường cũ mỗi khung lưu = `/api/pose` ~175 ms + `/api/enroll/frame` ~840 ms (trung vị) ≈ 1 s server cho một khung; đường mới `/session/frames` ~435 ms trung vị (p95 ~475 ms) gồm phát hiện + góc + embedding, rồi chốt (chọn, bản lật, ghi DB) ~220 ms. Camera giả trong Chromium: chặng chính diện xong sau ~12 s kể từ lúc bấm (gồm 3 s đếm ngược); từ lúc bấm đến màn kết quả ~50 s (4 chặng sau chờ hết giờ vì camera chỉ nhìn thẳng). **Chưa đạt** mục tiêu phản hồi < 300 ms/khung trên máy này (phần nặng là ước lượng góc 3D ~150 ms và embedding ~220 ms trên 2 CPU); máy mạnh/GPU chưa đo. Mẫu cũ không đo được "thời gian cả quy trình với người thật".
* **Chưa kiểm chứng**: người thật quay đầu 45°/ngẩng/cúi (cửa sổ góc `CLUB_WINDOWS` là giá trị khởi đầu, có thể cần chỉnh); độ tin cậy của góc ước lượng khi quay > 45°; lợi ích thực tế của augmentation với dataset thật của CLB; Docker build, deploy Hugging Face/Vercel thật; Windows/Python 3.11; `buffalo_s` (chưa thử); thiết bị di động thật (chỉ giả lập khung nhìn điện thoại trong Chromium).
* Mã Sweep/Session cũ vẫn còn trong `guide.js` (có test) nhưng **không còn dùng trong giao diện**; API `/api/enroll/frame`, `/batch` còn nguyên.
