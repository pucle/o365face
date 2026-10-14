# Deploy thử: Hugging Face và Vercel

## Chọn cách nào?
| | Chạy được backend (InsightFace)? | Dùng cho |
|---|---|---|
| **Hugging Face Space (Docker)** | **Có** | Backend + UI (khuyến nghị, cách rẻ/dễ nhất) |
| **Vercel** | **Không** (hàm serverless: giới hạn kích thước ~250 MB, thời gian, không có ổ đĩa bền; model ONNX + SQLite không phù hợp) | Chỉ **UI** + proxy tới Space. Có ích khi muốn địa chỉ riêng/HTTPS của bạn |

Vì vậy: **backend luôn ở Hugging Face** (hoặc máy của CLB), Vercel chỉ là mặt tiền tuỳ chọn.

## A. Hugging Face (một lệnh)
```bash
pip install huggingface_hub
export HF_TOKEN=hf_xxx               # Git Bash; PowerShell: $env:HF_TOKEN="hf_xxx"; cmd: set "HF_TOKEN=hf_xxx"  (token quyền write)
python tools/deploy_hf.py USER/club-attendance --api-token MAT_KHAU_CUA_BAN --dry-run   # xem kế hoạch
python tools/deploy_hf.py USER/club-attendance --api-token MAT_KHAU_CUA_BAN             # chạy thật
```
Lệnh tạo Space Docker **private**, đặt secret `API_TOKEN`, bật storage nhỏ (`--storage none` để bỏ) và phần cứng `cpu-upgrade` (`--hardware cpu-basic` = miễn phí, chậm, tự ngủ), rồi đẩy mã. Build ~5–10 phút (tab **Logs**). Sau đó:
```bash
python tools/smoke_test.py https://USER-club-attendance.hf.space --token MAT_KHAU_CUA_BAN --hf-token $HF_TOKEN
```
Smoke test kiểm: health, từ chối thiếu/sai token, nhận token đúng, tạo/xoá thành viên thử, `/api/pose`, UI tải được. Space private: mở URL trên trình duyệt đã đăng nhập Hugging Face. Tắt ngoài giờ: `tools/space_power.py USER/SPACE pause`.
Làm tay thay cho script: xem docs/02 (bước 4).

## B. Vercel (UI + proxy) — tuỳ chọn
1. Space đã chạy (mục A). Biến: `BACKEND_URL=https://USER-club-attendance.hf.space`; nếu Space private thêm `HF_TOKEN` (được gắn ở hàm proxy, không lộ ra trình duyệt).
2. ```bash
   python deploy/vercel/build.py            # chép UI vào deploy/vercel/public
   cd deploy/vercel
   npx vercel                                # lần đầu: đăng nhập, tạo project
   npx vercel env add BACKEND_URL production # dán URL Space
   npx vercel env add HF_TOKEN production     # chỉ khi Space private
   npx vercel --prod
   ```
3. Kiểm: `python tools/smoke_test.py https://TEN-BAN.vercel.app --token MAT_KHAU_CUA_BAN`.
Cách này cùng origin nên **không cần CORS**; camera chạy được vì Vercel là HTTPS. Phương án khác: không proxy — `python deploy/vercel/build.py --api-base https://USER-club-attendance.hf.space` và đặt biến `CORS_ORIGINS=https://TEN-BAN.vercel.app` trên Space (chỉ dùng được khi Space **public**).
Lưu ý: ai biết URL Vercel đều mở được UI; vẫn cần `API_TOKEN` mới dùng được API. Thử proxy không cần CLI: `BACKEND_URL=http://127.0.0.1:7860 API_TOKEN=... node deploy/vercel/test_proxy.mjs`.

## Giới hạn đã biết
Mỗi yêu cầu qua Vercel phải gửi/nhận trong giới hạn kích thước/thời gian của gói Vercel (ảnh JPEG <1 MB thì ổn). Client camera (`client/*.py`) nên gọi **thẳng Space**, không qua Vercel.

## Ghi chú cho đăng ký kiểu CLB
* Phiên đăng ký nằm trong RAM một tiến trình: Space có **một** worker nên ổn; nếu chạy nhiều worker/replica, hãy giữ một worker (phiên không chia sẻ giữa tiến trình). Space ngủ/khởi động lại = mất phiên đang dở (dữ liệu đã lưu thì còn nếu có persistent storage `/data`).
* Qua Vercel mỗi khung gửi ~20–40 KB nên nằm trong giới hạn; nhưng độ trễ qua proxy cộng vào phản hồi hướng dẫn: nếu muốn mượt, mở UI trực tiếp từ Space khi đăng ký.
* CPU miễn phí của Space chậm hơn máy bạn: đo bằng `python tools/bench_enroll.py --url ... --token ... --video clip.mp4`.
