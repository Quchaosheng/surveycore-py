from __future__ import annotations

from typing import Protocol

from .schema import (
    ReverseFillAcquireResult,
    ReverseFillAnswer,
    ReverseFillRuntimeState,
    ReverseFillSpec,
)


class ReverseFillAnswerSource(Protocol):
    def get_reverse_fill_answer(
        self, question_num: int, thread_name: str | None = None
    ) -> ReverseFillAnswer | None: ...


def create_reverse_fill_runtime_state(spec: ReverseFillSpec | None) -> ReverseFillRuntimeState | None:
    if spec is None:
        return None
    runtime = ReverseFillRuntimeState(spec=spec)
    for sample in spec.samples:
        runtime.samples_by_row_number[sample.data_row_number] = sample
        runtime.queued_row_numbers.append(sample.data_row_number)
    return runtime


def _possible_total(runtime: ReverseFillRuntimeState, completed: int) -> int:
    return (
        max(completed, len(runtime.committed_row_numbers))
        + len(runtime.queued_row_numbers)
        + len(runtime.reserved_row_by_thread)
    )


def acquire_sample(
    runtime: ReverseFillRuntimeState,
    worker: str,
    *,
    target: int,
    completed: int = 0,
) -> ReverseFillAcquireResult:
    with runtime.lock:
        existing = runtime.reserved_row_by_thread.get(worker)
        if existing is not None:
            return ReverseFillAcquireResult(
                status="acquired",
                sample=runtime.samples_by_row_number[existing],
                message="already_reserved",
            )
        if runtime.queued_row_numbers:
            row = runtime.queued_row_numbers.popleft()
            runtime.reserved_row_by_thread[worker] = row
            return ReverseFillAcquireResult(
                status="acquired", sample=runtime.samples_by_row_number[row], message="reserved"
            )
        if target > 0 and _possible_total(runtime, completed) < target:
            return ReverseFillAcquireResult(
                status="exhausted", message="reverse_fill_target_unreachable"
            )
        if not runtime.reserved_row_by_thread:
            return ReverseFillAcquireResult(status="exhausted", message="reverse_fill_completed")
        return ReverseFillAcquireResult(status="waiting", message="reverse_fill_waiting")


def release_sample(
    runtime: ReverseFillRuntimeState, worker: str, *, requeue: bool = True
) -> int | None:
    with runtime.lock:
        row = runtime.reserved_row_by_thread.pop(worker, None)
        if row is not None:
            if requeue:
                runtime.queued_row_numbers.appendleft(row)
            else:
                runtime.discarded_row_numbers.add(row)
        return row


def commit_sample(runtime: ReverseFillRuntimeState, worker: str) -> int | None:
    with runtime.lock:
        row = runtime.reserved_row_by_thread.pop(worker, None)
        if row is not None:
            runtime.committed_row_numbers.add(row)
            runtime.failure_count_by_row.pop(row, None)
        return row


def fail_sample(
    runtime: ReverseFillRuntimeState, worker: str, *, max_retries: int = 1
) -> tuple[int | None, bool]:
    with runtime.lock:
        row = runtime.reserved_row_by_thread.pop(worker, None)
        if row is None:
            return None, False
        failures = runtime.failure_count_by_row.get(row, 0) + 1
        runtime.failure_count_by_row[row] = failures
        discarded = failures > max_retries
        if discarded:
            runtime.discarded_row_numbers.add(row)
        else:
            runtime.queued_row_numbers.appendleft(row)
        return row, discarded


def get_answer(
    runtime: ReverseFillRuntimeState, worker: str, question_num: int
) -> ReverseFillAnswer | None:
    with runtime.lock:
        row = runtime.reserved_row_by_thread.get(worker)
        if row is None:
            return None
        return runtime.samples_by_row_number[row].answers.get(question_num)


def is_target_unreachable(
    runtime: ReverseFillRuntimeState, *, target: int, completed: int = 0
) -> bool:
    with runtime.lock:
        return target > 0 and _possible_total(runtime, completed) < target


def resolve_current_reverse_fill_answer(
    task_ctx: ReverseFillAnswerSource,
    question_num: int,
    *,
    thread_name: str = "",
) -> ReverseFillAnswer | None:
    return task_ctx.get_reverse_fill_answer(question_num, thread_name or None)
