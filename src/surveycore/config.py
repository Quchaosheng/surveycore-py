from __future__ import annotations

import json
from dataclasses import fields
from typing import Any

from .errors import ConfigError
from .models import QuestionConfig, RunConfig

SCHEMA_VERSION = 1
_RUN_FIELDS = {field.name for field in fields(RunConfig) if field.name != "answer_generator"}
_QUESTION_FIELDS = {
    field.name for field in fields(QuestionConfig)
    if field.name != "ai_enabled"
}


def _reject_unknown(payload: dict[str, Any], allowed: set[str], label: str) -> None:
    unknown = sorted(set(payload) - allowed)
    if unknown:
        raise ConfigError(f"{label}包含未知字段：{', '.join(unknown)}")


def _range(value: Any, label: str) -> tuple[int, int]:
    if not isinstance(value, list) or len(value) != 2:
        raise ConfigError(f"{label}必须是两个整数组成的数组")
    if any(isinstance(item, bool) or not isinstance(item, int) for item in value):
        raise ConfigError(f"{label}必须是整数")
    low, high = value
    if low < 0 or high < low:
        raise ConfigError(f"{label}范围无效")
    return low, high


def _string_range(value: Any, label: str) -> tuple[str, str]:
    if not isinstance(value, list) or len(value) != 2 or any(not isinstance(item, str) for item in value):
        raise ConfigError(f"{label}必须是两个字符串组成的数组")
    return value[0], value[1]


def _strict_bool(value: Any, label: str) -> bool:
    if not isinstance(value, bool):
        raise ConfigError(f"{label}必须是布尔值")
    return value


def _strict_float(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(f"{label}必须是数字")
    return float(value)


def _mapping(value: Any, label: str) -> dict[str, int]:
    if not isinstance(value, dict) or any(not isinstance(key, str) or isinstance(item, bool) or not isinstance(item, int) for key, item in value.items()):
        raise ConfigError(f"{label}必须是字符串到整数的对象")
    return dict(value)


def _list_of_dicts(value: Any, label: str) -> list[dict[str, Any]]:
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise ConfigError(f"{label}必须是对象数组")
    return [dict(item) for item in value]


def serialize_config(config: RunConfig) -> dict[str, Any]:
    if not isinstance(config, RunConfig):
        raise ConfigError("只支持序列化 RunConfig")
    return {
        "schema_version": SCHEMA_VERSION,
        "url": str(config.url),
        "questions": [{key: getattr(item, key) for key in sorted(_QUESTION_FIELDS)} for item in config.questions],
        "target": int(config.target),
        "concurrency": int(config.concurrency),
        "provider": config.provider,
        "answer_duration": list(config.answer_duration),
        "submit_interval": list(config.submit_interval),
        "answer_datetime_window": list(config.answer_datetime_window),
        "random_user_agent": bool(config.random_user_agent),
        "user_agent_ratios": dict(config.user_agent_ratios),
        "reliability_mode": bool(config.reliability_mode),
        "target_alpha": float(config.target_alpha),
        "answer_rules": list(config.answer_rules),
    }


def deserialize_config(payload: Any) -> RunConfig:
    if not isinstance(payload, dict):
        raise ConfigError("配置顶层必须是对象")
    version = payload.get("schema_version")
    if version != SCHEMA_VERSION:
        raise ConfigError(f"不支持的配置 schema 版本：{version!r}")
    _reject_unknown(payload, {"schema_version", *_RUN_FIELDS}, "配置")
    raw_questions = payload.get("questions", [])
    if not isinstance(raw_questions, list):
        raise ConfigError("questions 必须是数组")
    questions: list[QuestionConfig] = []
    for index, raw in enumerate(raw_questions, start=1):
        if not isinstance(raw, dict):
            raise ConfigError(f"questions[{index}] 必须是对象")
        _reject_unknown(raw, _QUESTION_FIELDS, f"questions[{index}]")
        if "question_type" not in raw:
            raise ConfigError(f"questions[{index}] 缺少 question_type")
        if not isinstance(raw["question_type"], str) or not raw["question_type"].strip():
            raise ConfigError(f"questions[{index}].question_type 必须是非空字符串")
        if "probabilities" in raw and raw["probabilities"] is not None and not isinstance(raw["probabilities"], (list, int, float)):
            raise ConfigError(f"questions[{index}].probabilities 类型无效")
        questions.append(QuestionConfig(**raw))
    target = payload.get("target", 1)
    concurrency = payload.get("concurrency", 1)
    if any(isinstance(value, bool) or not isinstance(value, int) for value in (target, concurrency)):
        raise ConfigError("target 和 concurrency 必须是整数")
    if target < 1 or concurrency < 1:
        raise ConfigError("target 和 concurrency 必须大于 0")
    provider = payload.get("provider")
    if provider is not None and (not isinstance(provider, str) or provider not in {"wjx", "qq", "credamo"}):
        raise ConfigError("provider 必须是 wjx、qq 或 credamo")
    return RunConfig(
        url=_required_string(payload.get("url", ""), "url"),
        questions=questions,
        target=target,
        concurrency=concurrency,
        provider=provider,
        answer_duration=_range(payload.get("answer_duration", [60, 120]), "answer_duration"),
        submit_interval=_range(payload.get("submit_interval", [0, 0]), "submit_interval"),
        answer_datetime_window=_string_range(payload.get("answer_datetime_window", ["", ""]), "answer_datetime_window"),
        random_user_agent=_strict_bool(payload.get("random_user_agent", False), "random_user_agent"),
        user_agent_ratios=_mapping(payload.get("user_agent_ratios", {"wechat": 33, "mobile": 33, "pc": 34}), "user_agent_ratios"),
        reliability_mode=_strict_bool(payload.get("reliability_mode", True), "reliability_mode"),
        target_alpha=_strict_float(payload.get("target_alpha", 0.85), "target_alpha"),
        answer_rules=_list_of_dicts(payload.get("answer_rules", []), "answer_rules"),
    )


def _required_string(value: Any, label: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        raise ConfigError(f"{label}必须是字符串")
    return value.strip()


def dumps_config(config: RunConfig, *, indent: int = 2) -> str:
    return json.dumps(serialize_config(config), ensure_ascii=False, indent=indent)


def loads_config(value: str) -> RunConfig:
    try:
        payload = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ConfigError(f"配置 JSON 无效：{exc}") from exc
    return deserialize_config(payload)


__all__ = ["SCHEMA_VERSION", "deserialize_config", "dumps_config", "loads_config", "serialize_config"]
