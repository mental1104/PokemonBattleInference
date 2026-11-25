"""封装可强制终止的有界 ProcessPoolExecutor。"""

from __future__ import annotations

from concurrent.futures import Future, ProcessPoolExecutor
from typing import Callable, Protocol


class WorkerExecutor(Protocol):
    """定义 coordinator 可替换的有界执行器和强制终止能力。"""

    def submit(self, fn: Callable[..., object], /, *args: object) -> Future[object]:
        """提交一个子进程任务并返回 Future。"""
        ...

    def shutdown(self) -> None:
        """正常等待已提交任务结束并释放资源。"""
        ...

    def terminate(self) -> None:
        """取消排队任务并终止仍在运行的子进程。"""
        ...


class TerminableProcessPool:
    """隔离 ``ProcessPoolExecutor`` 缺少公开强制终止接口的兼容细节。"""

    def __init__(self, max_workers: int) -> None:
        """创建固定大小的进程池。"""
        self._executor = ProcessPoolExecutor(max_workers=max_workers)
        self._terminated = False
        self._shutdown = False

    def submit(self, fn: Callable[..., object], /, *args: object) -> Future[object]:
        """把不可变配置提交给底层进程池。"""
        return self._executor.submit(fn, *args)

    def shutdown(self) -> None:
        """正常关闭进程池；已经释放时保持幂等。"""
        if self._shutdown:
            return
        self._executor.shutdown(wait=not self._terminated, cancel_futures=True)
        self._shutdown = True

    def terminate(self) -> None:
        """在取消宽限期结束后终止仍存活的 worker 进程。"""
        if self._terminated:
            return
        self._terminated = True
        processes = tuple(getattr(self._executor, "_processes", {}).values())
        for process in processes:
            if process.is_alive():
                process.terminate()
        self._executor.shutdown(wait=False, cancel_futures=True)
        self._shutdown = True
