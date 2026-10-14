"""Liệt kê camera USB/webcam trên máy này (chỉ số 0,1,2...) và chụp thử, để biết điền số nào vào trang Camera.

    python client/camera_list.py            # dò chỉ số 0..9, báo độ phân giải
    python client/camera_list.py --save     # lưu ảnh chụp thử camera-<n>.jpg để xem camera nào là camera nào
    python client/camera_list.py --rtsp rtsp://user:pass@192.168.1.50:554/stream1   # thử một camera mạng
"""
import argparse
import sys


def probe(src, save=False, name=""):
    import cv2
    cap = cv2.VideoCapture(int(src) if str(src).isdigit() else src)
    if not cap.isOpened():
        return False
    ok, frame = cap.read()
    cap.release()
    if not ok or frame is None:
        return False
    h, w = frame.shape[:2]
    print(f"  [{name or src}] mở được, {w}x{h}")
    if save:
        fn = f"camera-{name or src}.jpg"
        cv2.imwrite(fn, frame)
        print(f"      đã lưu {fn}")
    return True


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--max", type=int, default=10)
    ap.add_argument("--save", action="store_true")
    ap.add_argument("--rtsp", help="thử một URL camera mạng")
    a = ap.parse_args()
    if a.rtsp:
        sys.exit(0 if probe(a.rtsp, a.save, "rtsp") else print("Không mở được URL này (sai IP/user/mật khẩu/đường dẫn, hoặc khác mạng).") or 1)
    found = [i for i in range(a.max) if probe(i, a.save)]
    print("Camera tìm thấy ở chỉ số:", found or "không có")
    print("Dùng số này trong trang Camera (mục 'Nguồn cho client Python') hoặc --source <số>.")


if __name__ == "__main__":
    main()
