from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Protocol

from surveycore.core.reverse_fill import runtime
from surveycore.core.reverse_fill.schema import (
    ReverseFillAcquireResult,
    ReverseFillAnswer,
    ReverseFillRuntimeState,
)

if TYPE_CHECKING:
    from .task_context import ExecutionConfig

    class _ReverseFillHost(Protocol):
        config: ExecutionConfig
        cur_num: int
        reverse_fill_runtime: ReverseFillRuntimeState | None

        def acquire_reverse_fill_sample(
            self, thread_name: str | None = None
        ) -> ReverseFillAcquireResult: ...
        def notify_runtime_change(self) -> None: ...
        def wait_for_runtime_change(
            self, *, stop_signal: threading.Event | None = None, timeout: float | None = None
        ) -> bool: ...


def _worker_key(thread_name: str | None) -> str:
    return thread_name or threading.current_thread().name


class ReverseFillRuntimeMixin:
    def initialize_reverse_fill_runtime(self: _ReverseFillHost) -> None:
        self.reverse_fill_runtime = runtime.create_reverse_fill_runtime_state(
            self.config.reverse_fill_spec
        )
        self.notify_runtime_change()

    def acquire_reverse_fill_sample(
        self: _ReverseFillHost, thread_name: str | None = None
    ) -> ReverseFillAcquireResult:
        if self.reverse_fill_runtime is None:
            return ReverseFillAcquireResult(status="disabled", message="reverse_fill_disabled")
        return runtime.acquire_sample(
            self.reverse_fill_runtime,
            _worker_key(thread_name),
            target=self.config.target_num,
            completed=self.cur_num,
        )

    def release_reverse_fill_sample(
        self: _ReverseFillHost, thread_name: str | None = None, *, requeue: bool = True
    ) -> int | None:
        if self.reverse_fill_runtime is None:
            return None
        row = runtime.release_sample(self.reverse_fill_runtime, _worker_key(thread_name), requeue=requeue)
        self.notify_runtime_change()
        return row

    def commit_reverse_fill_sample(
        self: _ReverseFillHost, thread_name: str | None = None
    ) -> int | None:
        if self.reverse_fill_runtime is None:
            return None
        row = runtime.commit_sample(self.reverse_fill_runtime, _worker_key(thread_name))
        self.notify_runtime_change()
        return row

    def mark_reverse_fill_submission_failed(
        self: _ReverseFillHost, thread_name: str | None = None, *, max_retries: int = 1
    ) -> tuple[int | None, bool]:
        if self.reverse_fill_runtime is None:
            return None, False
        result = runtime.fail_sample(
            self.reverse_fill_runtime, _worker_key(thread_name), max_retries=max_retries
        )
        self.notify_runtime_change()
        return result

    def wait_for_reverse_fill_sample(
        self: _ReverseFillHost,
        *,
        thread_name: str | None = None,
        stop_signal: threading.Event | None = None,
        timeout_seconds: float = 0.5,
    ) -> ReverseFillAcquireResult:
        while True:
            if stop_signal is not None and stop_signal.is_set():
                return ReverseFillAcquireResult(status="waiting", message="stopped")
            result = self.acquire_reverse_fill_sample(thread_name)
            if result.status != "waiting":
                return result
            if stop_signal is not None and stop_signal.is_set():
                return ReverseFillAcquireResult(status="waiting", message="stopped")
            if self.wait_for_runtime_change(stop_signal=stop_signal, timeout=timeout_seconds):
                return ReverseFillAcquireResult(status="waiting", message="stopped")

    def get_reverse_fill_answer(
        self: _ReverseFillHost, question_num: int, thread_name: str | None = None
    ) -> ReverseFillAnswer | None:
        if self.reverse_fill_runtime is None:
            return None
        return runtime.get_answer(self.reverse_fill_runtime, _worker_key(thread_name), question_num)

    def is_reverse_fill_target_unreachable(self: _ReverseFillHost) -> bool:
        return self.reverse_fill_runtime is not None and runtime.is_target_unreachable(
            self.reverse_fill_runtime, target=self.config.target_num, completed=self.cur_num
        )
