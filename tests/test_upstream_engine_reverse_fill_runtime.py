from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from surveycore.core.reverse_fill import runtime
from surveycore.core.reverse_fill.runtime import resolve_current_reverse_fill_answer
from surveycore.core.reverse_fill.schema import (
    REVERSE_FILL_KIND_CHOICE,
    ReverseFillAnswer,
    ReverseFillSampleRow,
    ReverseFillSpec,
)
from surveycore.core.task import ExecutionConfig, ExecutionState


class TestReverseFillRuntimeState:
    def _build_state(self) -> ExecutionState:
        spec = ReverseFillSpec(
            source_path="demo.xlsx",
            selected_format="wjx_sequence",
            detected_format="wjx_sequence",
            start_row=1,
            total_samples=2,
            available_samples=2,
            target_num=2,
            samples=[
                ReverseFillSampleRow(
                    data_row_number=1,
                    worksheet_row_number=2,
                    answers={
                        1: ReverseFillAnswer(
                            question_num=1,
                            kind=REVERSE_FILL_KIND_CHOICE,
                            choice_index=0,
                        )
                    },
                ),
                ReverseFillSampleRow(
                    data_row_number=2,
                    worksheet_row_number=3,
                    answers={
                        1: ReverseFillAnswer(
                            question_num=1,
                            kind=REVERSE_FILL_KIND_CHOICE,
                            choice_index=1,
                        )
                    },
                ),
            ],
        )
        state = ExecutionState(config=ExecutionConfig(reverse_fill_spec=spec, target_num=2))
        state.initialize_reverse_fill_runtime()
        return state

    def test_acquire_commit_and_requeue_reverse_fill_rows(self) -> None:
        state = self._build_state()
        first = state.acquire_reverse_fill_sample("Worker-1")
        second = state.acquire_reverse_fill_sample("Worker-2")

        assert first.status == "acquired"
        assert second.status == "acquired"
        assert first.sample and first.sample.data_row_number == 1
        assert second.sample and second.sample.data_row_number == 2
        assert state.commit_reverse_fill_sample("Worker-1") == 1
        assert state.mark_reverse_fill_submission_failed("Worker-2", max_retries=1) == (2, False)
        retried = state.acquire_reverse_fill_sample("Worker-2")
        assert retried.sample and retried.sample.data_row_number == 2

    def test_discarded_row_can_make_target_unreachable(self) -> None:
        state = self._build_state()
        state.acquire_reverse_fill_sample("Worker-1")
        state.commit_reverse_fill_sample("Worker-1")
        state.acquire_reverse_fill_sample("Worker-2")
        state.mark_reverse_fill_submission_failed("Worker-2", max_retries=1)
        state.acquire_reverse_fill_sample("Worker-2")

        assert state.mark_reverse_fill_submission_failed("Worker-2", max_retries=1) == (2, True)
        assert state.is_reverse_fill_target_unreachable()

    def test_acquire_returns_disabled_when_runtime_not_initialized(self) -> None:
        result = ExecutionState(config=ExecutionConfig()).acquire_reverse_fill_sample("Worker-1")
        assert result.status == "disabled"
        assert result.message == "reverse_fill_disabled"

    def test_release_without_requeue_drops_reserved_row(self) -> None:
        state = self._build_state()
        first = state.acquire_reverse_fill_sample("Worker-1")
        released_row = state.release_reverse_fill_sample("Worker-1", requeue=False)
        second = state.acquire_reverse_fill_sample("Worker-2")
        exhausted = state.acquire_reverse_fill_sample("Worker-3")

        assert first.sample and first.sample.data_row_number == 1
        assert released_row == 1
        assert second.sample and second.sample.data_row_number == 2
        assert exhausted.status == "exhausted"

    def test_get_reverse_fill_answer_uses_thread_reserved_sample(self) -> None:
        state = self._build_state()
        state.acquire_reverse_fill_sample("Worker-1")
        state.acquire_reverse_fill_sample("Worker-2")

        answer = state.get_reverse_fill_answer(1, "Worker-2")
        assert answer and answer.choice_index == 1
        assert state.get_reverse_fill_answer(1, "Worker-3") is None

    def test_resolve_current_reverse_fill_answer_uses_explicit_thread(self) -> None:
        expected = ReverseFillAnswer(
            question_num=1,
            kind=REVERSE_FILL_KIND_CHOICE,
            choice_index=1,
        )
        calls: list[tuple[int, str]] = []

        class _Context:
            def get_reverse_fill_answer(
                self,
                question_num: int,
                thread_name: str | None = None,
            ) -> ReverseFillAnswer:
                calls.append((question_num, thread_name or ""))
                return expected

        assert (
            resolve_current_reverse_fill_answer(_Context(), 1, thread_name="Slot-2") is expected
        )
        assert calls == [(1, "Slot-2")]

    def test_standalone_runtime_reserves_each_row_once_across_workers(self) -> None:
        spec = self._build_state().config.reverse_fill_spec
        pool = runtime.create_reverse_fill_runtime_state(spec)
        assert pool is not None
        with ThreadPoolExecutor(max_workers=3) as executor:
            results = list(executor.map(
                lambda worker: runtime.acquire_sample(pool, worker, target=2),
                ["a", "b", "c"],
            ))
        rows = [result.sample.data_row_number for result in results if result.sample]
        assert sorted(rows) == [1, 2]
        assert [result.status for result in results].count("waiting") == 1

    def test_committed_rows_count_without_external_progress_and_are_not_counted_twice(self) -> None:
        state = self._build_state()
        state.acquire_reverse_fill_sample("a")
        state.commit_reverse_fill_sample("a")
        assert not state.is_reverse_fill_target_unreachable()
        state.cur_num = 1
        state.acquire_reverse_fill_sample("b")
        state.mark_reverse_fill_submission_failed("b", max_retries=0)
        assert state.is_reverse_fill_target_unreachable()

    def test_release_and_exhaustion_do_not_implicitly_retry(self) -> None:
        state = self._build_state()
        state.acquire_reverse_fill_sample("a")
        assert state.release_reverse_fill_sample("a") == 1
        assert state.release_reverse_fill_sample("a") is None
        first = state.acquire_reverse_fill_sample("b")
        assert first.sample and first.sample.data_row_number == 1
        state.commit_reverse_fill_sample("b")
        state.acquire_reverse_fill_sample("b")
        state.commit_reverse_fill_sample("b")
        assert state.acquire_reverse_fill_sample("c").status == "exhausted"

    def test_expired_joint_reservation_returns_its_excel_row(self, monkeypatch) -> None:
        state = self._build_state()
        state.acquire_reverse_fill_sample("slot")
        state.reserve_joint_sample(2, "slot")
        state.joint_reserved_sample_started_at_by_thread["slot"] = 1.0
        monkeypatch.setattr(
            "surveycore.core.task.distribution_state.time.monotonic", lambda: 100.0
        )

        assert state.expire_stale_joint_sample_reservations(10.0) == 1
        result = state.acquire_reverse_fill_sample("other")
        assert result.sample and result.sample.data_row_number == 1

    def test_waiting_for_reserved_rows_can_be_cancelled(self) -> None:
        state = self._build_state()
        state.acquire_reverse_fill_sample("a")
        state.acquire_reverse_fill_sample("b")
        stopped = threading.Event()
        stopped.set()

        result = state.wait_for_reverse_fill_sample(thread_name="c", stop_signal=stopped)

        assert result.status == "waiting"
        assert result.message == "stopped"

    def test_stopped_wait_does_not_reserve_an_available_row(self) -> None:
        state = self._build_state()
        stopped = threading.Event()
        stopped.set()

        result = state.wait_for_reverse_fill_sample(thread_name="a", stop_signal=stopped)

        assert result.message == "stopped"
        acquired = state.acquire_reverse_fill_sample("b")
        assert acquired.sample and acquired.sample.data_row_number == 1

    def test_answer_lookup_exposes_internal_errors(self) -> None:
        class BrokenSource:
            def get_reverse_fill_answer(
                self, question_num: int, thread_name: str | None = None
            ) -> ReverseFillAnswer | None:
                raise RuntimeError("broken source")

        with pytest.raises(RuntimeError, match="broken source"):
            resolve_current_reverse_fill_answer(BrokenSource(), 1)
