import asyncio
import threading
from contextlib import aclosing

import httpx
import pytest

from surveycore import RunConfig, SubmissionResult, SurveyClient, SurveyDefinition
from surveycore.core.engine.async_scheduler import AsyncScheduler
from surveycore.core.engine.provider_common import provider_run_context
from surveycore.core.persona.context import get_answered, record_answer
from surveycore.core.persona.generator import get_current_persona
from surveycore.core.questions import tendency
from surveycore.core.questions.consistency import apply_single_like_consistency
from surveycore.core.questions.utils import OPTION_FILL_AI_TOKEN
from surveycore.core.task import ExecutionConfig, ExecutionState
from surveycore.network.http import bind
from surveycore.providers.contracts import SurveyQuestionMeta
from surveycore.tencent.provider import answering_builders as qq_builders
from surveycore.tencent.provider import http_runtime as qq_http
from surveycore.wjx.provider import answering_builders as wjx_builders
from surveycore.wjx.provider import http_runtime as wjx_http


@pytest.mark.asyncio
async def test_overlapping_runs_keep_persona_answers_rules_and_tendencies_separate(
    monkeypatch,
) -> None:
    entered = [asyncio.Event(), asyncio.Event()]
    resume = [asyncio.Event(), asyncio.Event()]

    def base_ratio(*_args):
        persona = get_current_persona()
        assert persona is not None
        return persona.satisfaction_tendency

    monkeypatch.setattr(tendency, "_generate_base_ratio", base_ratio)
    monkeypatch.setattr(tendency, "_apply_consistency", lambda base, *_args: base)

    async def run(index: int) -> None:
        config = ExecutionConfig(answer_rules=[{
            "id": f"rule-{index}",
            "condition_question_num": 1,
            "condition_mode": "selected",
            "condition_option_indices": [index],
            "target_question_num": 2,
            "action_mode": "must_select",
            "target_option_indices": [index],
        }])
        with provider_run_context(config, psycho_plan=object()):
            persona = get_current_persona()
            assert persona is not None
            persona.satisfaction_tendency = float(index)
            record_answer(1, "single", selected_indices=[index])
            assert tendency.get_tendency_index(5, -1, dimension="shared") == index * 4
            entered[index].set()
            await resume[index].wait()
            assert get_current_persona() is persona
            assert get_answered()[1].selected_indices == [index]
            assert apply_single_like_consistency([1, 1], 2) == (
                [1.0, 0.0] if index == 0 else [0.0, 1.0]
            )
            assert tendency.get_tendency_index(5, -1, dimension="shared") == index * 4

    async with asyncio.TaskGroup() as group:
        first = group.create_task(run(0))
        await asyncio.wait_for(entered[0].wait(), timeout=1)
        group.create_task(run(1))
        await asyncio.wait_for(entered[1].wait(), timeout=1)
        resume[0].set()
        await first
        resume[1].set()


@pytest.mark.asyncio
async def test_run_close_awaits_pending_submission_cleanup(monkeypatch) -> None:
    pending = asyncio.Event()
    cleaned = asyncio.Event()

    async def parse(url):
        return SurveyDefinition(provider="wjx", title="test", url=url, questions=())

    calls = 0

    async def submit(_request):
        nonlocal calls
        calls += 1
        if calls == 1:
            await pending.wait()
            return SubmissionResult(0, "wjx", True, 0)
        pending.set()
        try:
            await asyncio.Event().wait()
        finally:
            cleaned.set()

    async with httpx.AsyncClient() as http_client:
        client = SurveyClient(http_client)
        monkeypatch.setattr(client, "parse", parse)
        monkeypatch.setattr(client, "submit", submit)
        async with aclosing(client.run(RunConfig(
            url="https://www.wjx.cn/vm/test.aspx", target=3, concurrency=2
        ))) as results:
            assert (await anext(results)).success
        assert cleaned.is_set()
        assert not http_client.is_closed


@pytest.fixture
def http_survey(monkeypatch):
    def setup(provider: str, config: ExecutionConfig) -> str:
        if provider == "wjx":
            config.url = "https://www.wjx.cn/vm/test.aspx"

            async def load(*_args, **_kwargs):
                return "<html></html>"

            monkeypatch.setattr(wjx_http, "_load_wjx_page", load)
        else:
            config.url = "https://wj.qq.com/s2/123/hash/"
            raw_questions = [
                {
                    "id": f"q{num}",
                    "title": question.title,
                    "type": "text" if question.type_code == "1" else "radio",
                    "options": [
                        {"id": "o1", "text": "A {fillblank-1}"},
                        {"id": "o2", "text": "B"},
                    ],
                    "page_id": "p1",
                }
                for num, question in config.questions_metadata.items()
            ]

            async def fetch(*_args, **_kwargs):
                return "", {}, raw_questions

            monkeypatch.setattr(qq_http, "_fetch_submit_source", fetch)
        return config.url

    return setup


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ["wjx", "qq"])
async def test_http_ai_answers_reach_payload_and_failures_can_be_retried(
    provider, http_survey,
) -> None:
    generated = []
    config = ExecutionConfig(
        survey_provider=provider,
        text_ai_flags=[True, True],
        single_prob=[[1, 0]],
        single_option_fill_texts=[[OPTION_FILL_AI_TOKEN, None]],
        question_config_index_map={1: ("text", 0), 2: ("text", 1), 3: ("single", 0)},
        questions_metadata={
            1: SurveyQuestionMeta(num=1, title="城市", type_code="1", text_inputs=1),
            2: SurveyQuestionMeta(num=2, title="爱好", type_code="1", text_inputs=1),
            3: SurveyQuestionMeta(
                num=3, title="补充", type_code="3", options=2, option_texts=["A", "B"]
            ),
        },
    )

    async def generate(prompt, **_kwargs):
        generated.append(prompt)
        await asyncio.sleep(0)
        return "生成答案"

    config.answer_generator = generate
    http_survey(provider, config)
    state = ExecutionState(config=config)
    requests = []

    def handle(request):
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(503)
        return httpx.Response(200, text="success") if provider == "wjx" else httpx.Response(
            200, json={"code": "OK", "data": {"answer_hash": "stored"}}
        )

    brush = wjx_http.brush_wjx_http if provider == "wjx" else qq_http.brush_qq_http
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client, bind(client):
        with provider_run_context(config, psycho_plan=object()):
            with pytest.raises(httpx.HTTPStatusError):
                await brush(config, state, thread_name="Slot-1")
        with provider_run_context(config, psycho_plan=object()):
            assert await brush(config, state, thread_name="Slot-1")
    assert len(requests) == 2
    assert len(generated) == 6
    for request in requests:
        body = request.content.decode()
        assert "__FREE_AI_" not in body
        if provider == "qq":
            assert "生成答案" in body
        else:
            assert "%E7%94%9F%E6%88%90" in body
    assert state.get_free_ai_prefill_answer("Slot-1", 1) is None
    assert state.get_free_ai_option_fill_prefill_answer("Slot-1", 3, 0) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ["wjx", "qq"])
async def test_http_rules_see_prior_answers_and_distribution_commits_to_slot(
    provider, http_survey, monkeypatch,
) -> None:
    config = ExecutionConfig(
        survey_provider=provider,
        single_prob=[[1, 0], [1, 1]],
        question_config_index_map={1: ("single", 0), 2: ("single", 1)},
        question_strict_ratio_map={1: True, 2: True},
        questions_metadata={
            num: SurveyQuestionMeta(
                num=num, title=f"Q{num}", type_code="3", options=2, option_texts=["A", "B"]
            )
            for num in (1, 2)
        },
        answer_rules=[{
            "id": "follow-first",
            "condition_question_num": 1,
            "condition_mode": "selected",
            "condition_option_indices": [0],
            "target_question_num": 2,
            "action_mode": "must_select",
            "target_option_indices": [1],
        }],
    )
    builders = wjx_builders if provider == "wjx" else qq_builders
    monkeypatch.setattr(builders, "weighted_index", lambda weights: weights.index(max(weights)))
    http_survey(provider, config)
    state = ExecutionState(config=config)
    posted = []

    def handle(request):
        posted.append(request)
        return httpx.Response(200, text="success") if provider == "wjx" else httpx.Response(
            200, json={"code": "OK", "data": {"answer_hash": "stored"}}
        )

    brush = wjx_http.brush_wjx_http if provider == "wjx" else qq_http.brush_qq_http
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client, bind(client):
        state.reset_pending_distribution("Slot-2")
        with provider_run_context(config, psycho_plan=object()):
            assert await brush(config, state, thread_name="Slot-2")
            assert get_answered()[2].selected_indices == [1]
        assert state.commit_pending_distribution("Slot-2") == 2
    assert len(posted) == 1
    assert state.snapshot_distribution_stats("q:1", 2) == (1, [1, 0])
    assert state.snapshot_distribution_stats("q:2", 2) == (1, [0, 1])
    assert state.commit_pending_distribution("Slot-2") == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ["wjx", "qq"])
async def test_stop_during_submit_preparation_prevents_post(provider, http_survey) -> None:
    stopped = asyncio.Event()
    config = ExecutionConfig(
        survey_provider=provider,
        single_prob=[[1, 0]],
        question_config_index_map={1: ("single", 0)},
        questions_metadata={1: SurveyQuestionMeta(
            num=1, title="Q1", type_code="3", options=2, option_texts=["A", "B"]
        )},
    )
    http_survey(provider, config)
    state = ExecutionState(config=config)

    async def lease():
        stopped.set()
        await asyncio.sleep(0)

    def handle(_request):
        pytest.fail("stopped attempt must not submit")

    brush = wjx_http.brush_wjx_http if provider == "wjx" else qq_http.brush_qq_http
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client, bind(client):
        with provider_run_context(config, psycho_plan=object()):
            assert not await brush(
                config, state, stop_signal=stopped, submit_proxy_lease_factory=lease
            )


@pytest.mark.parametrize("sample_count", [0, 1])
def test_joint_wait_returns_for_empty_or_completed_quota(sample_count, monkeypatch) -> None:
    state = ExecutionState()
    if sample_count:
        state.reserve_joint_sample(sample_count, "Slot-1")
        state.commit_joint_sample("Slot-1")

    def unexpected_wait(**_kwargs):
        pytest.fail("terminal quota must not wait for a runtime change")

    monkeypatch.setattr(state, "wait_for_runtime_change", unexpected_wait)
    assert state.wait_for_joint_sample(sample_count, thread_name="Slot-2") is None


def test_stopped_joint_wait_does_not_acquire_available_sample() -> None:
    state = ExecutionState()
    stopped = threading.Event()
    stopped.set()
    assert state.wait_for_joint_sample(1, thread_name="Slot-1", stop_signal=stopped) is None
    assert state.reserve_joint_sample(1, "Slot-2") == 0


@pytest.mark.asyncio
async def test_closed_scheduler_does_not_restart_waker() -> None:
    scheduler = AsyncScheduler(concurrency=1)
    await scheduler.start()
    await scheduler.close()
    try:
        assert await scheduler.acquire() is None
        assert scheduler._waker_task is None
    finally:
        await scheduler.close()
