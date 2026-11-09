from __future__ import annotations

import asyncio
import random
import time
from collections.abc import AsyncIterator
from contextlib import aclosing
from dataclasses import replace
from typing import Any

import httpx

from .core.questions.config import (
    QuestionEntry,
    build_default_question_entries,
    configure_probabilities,
)
from .core.task import ExecutionConfig, ExecutionState
from .errors import SurveyParseError, SurveyUnavailableError, UnsupportedSurveyError
from .models import (
    RunConfig,
    SubmissionRequest,
    SubmissionResult,
    SurveyDefinition,
    SurveyQuestion,
)
from .network.http import bind
from .providers.common import (
    detect_survey_provider,
    normalize_survey_parse_url,
)
from .providers.registry import fill_survey_http, parse_survey
from .runtime import completed_results
from .transport import require_async_client


def _question_from_meta(item: Any) -> SurveyQuestion:
    def dicts(value: Any) -> tuple[dict[str, Any], ...]:
        return tuple(dict(entry) for entry in list(value or []) if isinstance(entry, dict))

    return SurveyQuestion(
        num=int(getattr(item, "num", 0) or 0),
        title=str(getattr(item, "title", "") or ""),
        type_code=str(getattr(item, "type_code", "0") or "0"),
        provider_question_id=str(getattr(item, "provider_question_id", "") or ""),
        provider_page_id=str(getattr(item, "provider_page_id", "") or ""),
        options=int(getattr(item, "options", 0) or 0),
        rows=int(getattr(item, "rows", 1) or 1),
        option_texts=tuple(str(value or "") for value in list(getattr(item, "option_texts", []) or [])),
        row_texts=tuple(str(value or "") for value in list(getattr(item, "row_texts", []) or [])),
        page=int(getattr(item, "page", 1) or 1),
        required=bool(getattr(item, "required", False)),
        display_num=getattr(item, "display_num", None),
        description=str(getattr(item, "description", "") or ""),
        forced_option_index=getattr(item, "forced_option_index", None),
        forced_option_text=str(getattr(item, "forced_option_text", "") or ""),
        forced_texts=tuple(str(v or "") for v in (getattr(item, "forced_texts", []) or [])),
        fillable_options=tuple(int(v) for v in (getattr(item, "fillable_options", []) or [])),
        attached_option_selects=dicts(getattr(item, "attached_option_selects", [])),
        has_attached_option_select=bool(getattr(item, "has_attached_option_select", False)),
        rating_max=int(getattr(item, "rating_max", 0) or 0),
        text_inputs=int(getattr(item, "text_inputs", 0) or 0),
        text_input_labels=tuple(str(v or "") for v in (getattr(item, "text_input_labels", []) or [])),
        is_multi_text=bool(getattr(item, "is_multi_text", False)),
        question_media=dicts(getattr(item, "question_media", [])),
        slider_min=getattr(item, "slider_min", None),
        slider_max=getattr(item, "slider_max", None),
        slider_step=getattr(item, "slider_step", None),
        multi_min_limit=getattr(item, "multi_min_limit", None),
        multi_max_limit=getattr(item, "multi_max_limit", None),
        provider_type=str(getattr(item, "provider_type", "") or ""),
        provider_page_raw=getattr(item, "provider_page_raw", None),
        is_text_like=bool(getattr(item, "is_text_like", False)),
        is_location=bool(getattr(item, "is_location", False)),
        is_description=bool(getattr(item, "is_description", False)),
        is_rating=bool(getattr(item, "is_rating", False)),
        is_slider_matrix=bool(getattr(item, "is_slider_matrix", False)),
        has_jump=bool(getattr(item, "has_jump", False)),
        jump_rules=dicts(getattr(item, "jump_rules", [])),
        has_display_condition=bool(getattr(item, "has_display_condition", False)),
        display_conditions=dicts(getattr(item, "display_conditions", [])),
        has_dependent_display_logic=bool(getattr(item, "has_dependent_display_logic", False)),
        controls_display_targets=dicts(getattr(item, "controls_display_targets", [])),
        logic_parse_status=str(getattr(item, "logic_parse_status", "unknown") or "unknown"),
        unsupported=bool(getattr(item, "unsupported", False)),
        unsupported_reason=str(getattr(item, "unsupported_reason", "") or ""),
    )


class SurveyClient:
    """Async survey parser and HTTP submitter using a caller-owned client."""

    def __init__(self, http_client: httpx.AsyncClient) -> None:
        self.http_client = require_async_client(http_client)

    @staticmethod
    def _resolve_provider(config: RunConfig) -> str:
        detected = detect_survey_provider(config.url, default="")
        provider = config.provider or detected
        if provider not in {"wjx", "qq", "credamo"}:
            raise UnsupportedSurveyError(f"不支持的问卷平台：{provider or config.url}")
        if config.provider and detected and config.provider != detected:
            raise UnsupportedSurveyError(f"问卷链接平台与配置不一致：{config.provider} != {detected}")
        return provider

    async def parse(self, url: str) -> SurveyDefinition:
        normalized = normalize_survey_parse_url(url)
        provider = detect_survey_provider(normalized, default="")
        if not provider:
            raise UnsupportedSurveyError(f"不支持的问卷链接：{url}")
        try:
            async with bind(self.http_client):
                definition = await parse_survey(normalized)
        except (UnsupportedSurveyError, SurveyUnavailableError):
            raise
        except Exception as exc:
            message = str(exc) or "问卷解析失败"
            if any(marker in message for marker in ("未开放", "已停止", "已暂停", "到期")):
                raise SurveyUnavailableError(message) from exc
            raise SurveyParseError(message) from exc
        questions = tuple(_question_from_meta(item) for item in definition.questions)
        return SurveyDefinition(provider=definition.provider, title=definition.title, url=normalized, questions=questions)

    def _execution_config(self, config: RunConfig, survey: SurveyDefinition | None) -> ExecutionConfig:
        provider = self._resolve_provider(config)
        from ._question_metas import to_question_metas
        legacy_questions = to_question_metas(survey.questions if survey else ())
        entries: list[QuestionEntry] = [QuestionEntry(**{
            key: getattr(item, key) for key in QuestionEntry.__dataclass_fields__
            if hasattr(item, key)
        }) for item in config.questions]
        if not entries and legacy_questions:
            entries = list(build_default_question_entries(legacy_questions, survey_url=config.url, existing_entries=[]))
        execution = ExecutionConfig(
            url=str(config.url or ""),
            survey_provider=provider,
            target_num=max(1, int(config.target)),
            num_threads=max(1, int(config.concurrency)),
            answer_duration_range_seconds=(config.answer_duration[0], config.answer_duration[1]),
            submit_interval_range_seconds=(config.submit_interval[0], config.submit_interval[1]),
            random_user_agent_enabled=bool(config.random_user_agent),
            user_agent_ratios=dict(config.user_agent_ratios),
            answer_rules=list(config.answer_rules),
            psycho_target_alpha=float(config.target_alpha),
            stop_on_fail_enabled=False,
            pause_on_aliyun_captcha=False,
        )
        execution.answer_generator = config.answer_generator
        execution.question_entries = entries
        execution.questions_metadata = {int(item.num): item for item in legacy_questions if int(getattr(item, "num", 0) or 0) > 0}
        configure_probabilities(entries, execution, reliability_mode_enabled=bool(config.reliability_mode))
        return execution

    async def submit(self, request: SubmissionRequest | RunConfig) -> SubmissionResult:
        config = request.config if isinstance(request, SubmissionRequest) else request
        survey = request.survey if isinstance(request, SubmissionRequest) else None
        started = time.perf_counter()
        provider = self._resolve_provider(config)
        execution = self._execution_config(config, survey)
        state = ExecutionState(config=execution)
        try:
            async with bind(self.http_client):
                success = await fill_survey_http(
                    execution,
                    state,
                    stop_signal=asyncio.Event(),
                    thread_name="surveycore",
                    provider=provider,
                )
        except Exception as exc:
            return SubmissionResult(0, provider, False, time.perf_counter() - started, str(exc) or "提交失败")
        return SubmissionResult(0, provider, bool(success), time.perf_counter() - started, None if success else "平台未确认提交成功")

    async def run(self, config: RunConfig) -> AsyncIterator[SubmissionResult]:
        survey = await self.parse(config.url)
        async def attempt(index: int) -> SubmissionResult:
            if index > 1:
                low, high = config.submit_interval
                if high > 0:
                    await asyncio.sleep(random.uniform(low, high))
            result = await self.submit(SubmissionRequest(config=replace(config, target=1), survey=survey))
            return replace(result, attempt=index)

        async with aclosing(completed_results(config.target, config.concurrency, attempt)) as results:
            async for result in results:
                yield result


__all__ = ["SurveyClient"]
