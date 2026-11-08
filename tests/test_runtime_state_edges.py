import asyncio
import threading
import time

import pytest

from surveycore.core.engine.async_wait import is_stop_requested, sleep_or_stop
from surveycore.core.engine.runtime_actions import (
    RuntimeActionKind,
    RuntimeActionRequest,
    RuntimeActionResult,
    ensure_runtime_action_result,
)
from surveycore.core.task import ExecutionState
from surveycore.logging import log_utils


class BrokenStopSignal:
    def is_set(self):
        raise RuntimeError("broken")

    def wait(self, _timeout):
        raise RuntimeError("broken")


@pytest.mark.asyncio
async def test_sleep_or_stop_supports_async_threading_and_broken_signals() -> None:
    assert not is_stop_requested(None)
    assert not is_stop_requested(object())
    assert not is_stop_requested(BrokenStopSignal())
    assert not await sleep_or_stop(None, 0)

    async_event = asyncio.Event()
    async_event.set()
    assert await sleep_or_stop(async_event, 1)

    timeout_event = asyncio.Event()
    assert not await sleep_or_stop(timeout_event, 0.001)

    thread_event = threading.Event()
    thread_event.set()
    assert await sleep_or_stop(thread_event, 0.01)
    assert not await sleep_or_stop(BrokenStopSignal(), 0.001)


def test_runtime_action_result_normalizes_callback_outputs() -> None:
    message = RuntimeActionRequest(
        RuntimeActionKind.SHOW_MESSAGE,
        title="提示",
        message="已暂停",
    )
    result = RuntimeActionResult.from_actions([message], should_stop=True)

    assert result.actions == (message,)
    assert result.should_stop is True
    assert ensure_runtime_action_result(result) is result
    assert ensure_runtime_action_result(message).actions == (message,)
    assert ensure_runtime_action_result([message, object()]).actions == (message,)
    assert ensure_runtime_action_result(None) == RuntimeActionResult.empty()
    assert ensure_runtime_action_result(object()) == RuntimeActionResult.empty()


def test_suppressed_exception_logging(caplog) -> None:
    with caplog.at_level("INFO"):
        log_utils.log_suppressed_exception("解析失败", ValueError("bad"))

    assert "[Suppressed] 解析失败: bad" in caplog.text


def test_thread_progress_lifecycle_and_display_names() -> None:
    state = ExecutionState()
    state.ensure_worker_threads(2, prefix="Slot")
    state.update_thread_step("Slot-1", 1, 2, running=True)
    state.increment_thread_success("Slot-1")
    state.increment_thread_fail("Slot-2", status_text="网络失败")
    state.mark_thread_finished("Slot-2")
    state.update_thread_status("custom7", "运行中", running=True)

    rows = state.snapshot_thread_progress()
    by_name = {row["thread_name"]: row for row in rows}
    assert by_name["Slot-1"]["thread_display_name"] == "会话 1"
    assert by_name["Slot-1"]["success_count"] == 1
    assert by_name["Slot-1"]["step_percent"] == 100
    assert by_name["Slot-2"]["fail_count"] == 1
    assert by_name["Slot-2"]["running"] is False
    assert by_name["custom7"]["thread_index"] == 7
    assert state._resolve_thread_index("Worker-x") == 0
    assert state._resolve_thread_index("plain") == 0
    assert state._format_thread_display_name("Slot-?", 0) == "会话 ?"


def test_distribution_state_rejects_invalid_choices_and_tracks_joint_samples(monkeypatch) -> None:
    state = ExecutionState()
    state.append_pending_distribution_choice("q1", 0, 0, "Worker-1")
    state.append_pending_distribution_choice("q1", -1, 3, "Worker-1")
    state.append_pending_distribution_choice("q1", 3, 3, "Worker-1")
    assert state.commit_pending_distribution("Worker-1") == 0
    assert state.snapshot_distribution_stats("missing", 3) == (0, [0, 0, 0])
    assert state.reserve_joint_sample(0, "Worker-1") is None

    assert state.reserve_joint_sample(2, "Worker-1") == 0
    assert state.peek_reserved_joint_sample("Worker-1") == 0
    assert state.reserve_joint_sample(2, "Worker-1") == 0
    assert not state.mark_joint_sample_answering("Worker-2")
    assert state.commit_joint_sample("Worker-1") == 0
    assert state.commit_joint_sample("Worker-1") is None
    assert state.reserve_joint_sample(2, "Worker-2") == 1
    assert state.commit_joint_sample("Worker-2") == 1
    assert state.is_joint_sample_quota_exhausted(2)
    assert not state.is_joint_sample_quota_exhausted(0)
    assert state.release_joint_sample("missing") is None

    stopped = threading.Event()
    stopped.set()
    assert state.wait_for_joint_sample(2, thread_name="Worker-3", stop_signal=stopped) is None


def test_stale_joint_reservations_expire_but_answering_samples_survive() -> None:
    state = ExecutionState()
    assert state.reserve_joint_sample(3, "Worker-1") == 0
    assert state.reserve_joint_sample(3, "Worker-2") == 1
    assert state.mark_joint_sample_answering("Worker-2")
    state.joint_reserved_sample_started_at_by_thread["Worker-1"] = time.monotonic() - 100
    state.joint_reserved_sample_started_at_by_thread["Worker-2"] = time.monotonic() - 100

    assert state.expire_stale_joint_sample_reservations(10) == 1
    assert state.peek_reserved_joint_sample("Worker-1") is None
    assert state.peek_reserved_joint_sample("Worker-2") == 1
    assert state.expire_stale_joint_sample_reservations(0) == 0
