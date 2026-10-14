"""Giữ RAM dưới trần của gói free (Render: 512 MB). Ba bậc, kiểm tra định kỳ:
  mềm  (MEM_SOFT_MB, mặc định 380): gc + trả bộ nhớ rảnh cho hệ điều hành (malloc_trim)
  cứng (MEM_HARD_MB, mặc định 440): bỏ các phiên đăng ký đang treo (RAM tạm), gc + trim
  tới hạn (MEM_KILL_MB, mặc định 480) 3 lần liên tiếp: thoát tiến trình để Render tự khởi động lại
        (dữ liệu nằm ở Neon nên không mất; tốt hơn để Linux OOM-kill giữa lúc đang ghi).
Chỉ đọc /proc nên không tốn thêm thư viện; không có /proc (Windows/macOS) thì không làm gì.
"""
from __future__ import annotations

import ctypes
import gc
import logging
import os
from typing import Callable, Optional

log = logging.getLogger("memguard")


def rss_mb() -> Optional[float]:
    try:
        with open("/proc/self/status") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) / 1024.0
    except OSError:
        pass
    return None


def trim() -> None:
    gc.collect()
    try:
        ctypes.CDLL("libc.so.6").malloc_trim(0)
    except Exception:
        pass


class MemGuard:
    def __init__(self, on_hard: Optional[Callable[[], None]] = None, exit_fn: Callable[[int], None] = os._exit):
        self.soft = float(os.getenv("MEM_SOFT_MB", "380"))
        self.hard = float(os.getenv("MEM_HARD_MB", "440"))
        self.kill = float(os.getenv("MEM_KILL_MB", "480"))
        self.on_hard, self.exit_fn, self.strikes = on_hard, exit_fn, 0
        self.last: Optional[float] = None

    def check(self, rss: Optional[float] = None) -> str:
        """Trả về 'ok' | 'trim' | 'shed' | 'exit' (để test và ghi log)."""
        rss = rss_mb() if rss is None else rss
        self.last = rss
        if rss is None:
            return "ok"
        if rss >= self.kill:
            self.strikes += 1
            trim()
            if self.strikes >= 3:
                log.error("RAM %.0f MB >= %.0f MB 3 lần liên tiếp: thoát để được khởi động lại sạch", rss, self.kill)
                self.exit_fn(3)
                return "exit"
            return "shed"
        self.strikes = 0
        if rss >= self.hard:
            log.warning("RAM %.0f MB: bỏ phiên đăng ký đang treo", rss)
            if self.on_hard:
                self.on_hard()
            trim()
            return "shed"
        if rss >= self.soft:
            trim()
            return "trim"
        return "ok"
