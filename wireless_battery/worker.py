# -*- coding: utf-8 -*-
"""后台 HID 异步轮询线程，避免阻塞界面事件循环。"""

from __future__ import annotations

import threading

from PySide6.QtCore import QThread, Signal

from .protocols import PollResult, poll_all_devices


class PollThread(QThread):
    """单次后台轮询工作线程。"""

    poll_finished = Signal(list)

    def run(self) -> None:
        results: list[PollResult] = poll_all_devices()
        self.poll_finished.emit(results)


class PollCoordinator(QThread):
    """带防重入锁的轮询调度器（对外暴露统一信号接口）。"""

    poll_started = Signal()
    poll_finished = Signal(list)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._lock = threading.Lock()
        self._active_thread: PollThread | None = None

    def is_polling(self) -> bool:
        """当前是否正在执行 HID 轮询。"""
        return self._active_thread is not None and self._active_thread.isRunning()

    def trigger_poll(self) -> bool:
        """触发一次后台异步轮询；若已有轮询在运行则忽略本次请求。"""
        if not self._lock.acquire(blocking=False):
            return False

        if self._active_thread is not None and self._active_thread.isRunning():
            self._lock.release()
            return False

        self.poll_started.emit()
        worker = PollThread(self)
        worker.poll_finished.connect(self._on_worker_finished)
        worker.finished.connect(worker.deleteLater)
        self._active_thread = worker
        worker.start()
        return True

    def _on_worker_finished(self, results: list) -> None:
        try:
            self._active_thread = None
        finally:
            if self._lock.locked():
                self._lock.release()
        self.poll_finished.emit(results)

    def stop_and_wait(self, timeout_ms: int = 2000) -> None:
        """退出应用时等待后台轮询线程安全结束。"""
        if self._active_thread is not None and self._active_thread.isRunning():
            self._active_thread.wait(timeout_ms)
