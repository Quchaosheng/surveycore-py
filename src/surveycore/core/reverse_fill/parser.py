from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional

from surveycore.core.questions.meta_helpers import infer_question_entry_type
from surveycore.core.questions.schema import QuestionEntry
from surveycore.core.reverse_fill.schema import (
    REVERSE_FILL_FORMAT_WJX_SCORE,
    REVERSE_FILL_FORMAT_WJX_SEQUENCE,
    REVERSE_FILL_FORMAT_WJX_TEXT,
    REVERSE_FILL_KIND_CHOICE,
    REVERSE_FILL_KIND_CHOICES,
    REVERSE_FILL_KIND_MATRIX,
    REVERSE_FILL_KIND_MULTI_TEXT,
    REVERSE_FILL_KIND_TEXT,
    REVERSE_FILL_RUNTIME_SUPPORTED_TYPES,
    ReverseFillAnswer,
    ReverseFillColumn,
    ReverseFillRawRow,
)
from surveycore.providers.contracts import SurveyQuestionMeta

_LEADING_INDEX_RE = re.compile(r"^[\(\[（【]?\s*\d+\s*[\)\]）】]?\s*")
_NUMBER_TEXT_RE = re.compile(r"^\d+(?:\.0+)?$")
_MULTIPLE_COLUMN_INDEX_RE = re.compile(r"[（(]\s*选项\s*(\d+)\s*[)）]\s*$")


def normalize_reverse_fill_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if float(value).is_integer():
            return str(int(value))
        text = f"{value:.12f}".rstrip("0").rstrip(".")
        return text or "0"
    return str(value).strip()


def normalize_reverse_fill_key(value: Any) -> str:
    text = normalize_reverse_fill_text(value)
    if not text:
        return ""
    text = text.replace("（", "(").replace("）", ")")
    text = text.replace("【", "[").replace("】", "]")
    text = text.replace("—", "-").replace("–", "-").replace("－", "-")
    text = text.replace("：", ":")
    text = re.sub(r"\s+", "", text)
    return text.casefold()


def label_variants(value: Any) -> List[str]:
    text = normalize_reverse_fill_text(value)
    if not text:
        return []
    variants: List[str] = []

    def _append(candidate: str) -> None:
        normalized = normalize_reverse_fill_key(candidate)
        if normalized and normalized not in variants:
            variants.append(normalized)

    _append(text)
    stripped = _LEADING_INDEX_RE.sub("", text).strip().strip("_")
    _append(stripped)
    normalized_stripped = stripped.replace("—", "-").replace("–", "-").replace("－", "-")
    for separator in ("-", ":", "丨", "|", "/", "／"):
        if separator in normalized_stripped:
            _append(normalized_stripped.rsplit(separator, 1)[-1].strip().strip("_"))
    return variants


def is_reverse_fill_blank(value: Any) -> bool:
    return not normalize_reverse_fill_text(value)


def infer_reverse_fill_question_type(info: SurveyQuestionMeta | Dict[str, Any], entry: Optional[QuestionEntry] = None) -> str:
    return infer_question_entry_type(info)


def supports_reverse_fill_runtime(question_type: str, info: SurveyQuestionMeta | Dict[str, Any]) -> bool:
    normalized = question_type.strip().lower()
    if normalized not in REVERSE_FILL_RUNTIME_SUPPORTED_TYPES:
        return False
    if normalized == "text" and bool(info.get("is_location")):
        return False
    if normalized in {"single", "dropdown", "multiple"}:
        if info.get("fillable_options") or info.get("attached_option_selects"):
            return False
    return True


def resolve_question_entry(info: SurveyQuestionMeta | Dict[str, Any], entries: List[QuestionEntry]) -> Optional[QuestionEntry]:
    raw_question_num = info.get("num")
    question_num = int(raw_question_num) if raw_question_num is not None else None
    title_key = normalize_reverse_fill_key(info.get("title"))
    matched_by_title: Optional[QuestionEntry] = None
    for entry in entries:
        entry_num = entry.question_num
        if entry_num is not None and question_num is not None and question_num == entry_num:
            return entry
        if matched_by_title is None and title_key and normalize_reverse_fill_key(entry.question_title) == title_key:
            matched_by_title = entry
    return matched_by_title


def resolve_ordered_columns(columns: List[ReverseFillColumn], expected_labels: Iterable[Any]) -> List[ReverseFillColumn]:
    ordered_columns = sorted(columns, key=lambda item: item.column_index)
    labels = list(expected_labels)
    if not ordered_columns or not labels or len(ordered_columns) != len(labels):
        return ordered_columns

    label_index_map: Dict[str, int] = {}
    for index, label in enumerate(labels):
        for variant in label_variants(label):
            label_index_map.setdefault(variant, index)

    resolved: List[Optional[ReverseFillColumn]] = [None] * len(labels)
    leftovers: List[ReverseFillColumn] = []
    used_indexes = set()
    for column in ordered_columns:
        matched = False
        for variant in label_variants(column.suffix):
            target_index = label_index_map.get(variant)
            if target_index is None or target_index in used_indexes:
                continue
            resolved[target_index] = column
            used_indexes.add(target_index)
            matched = True
            break
        if not matched:
            leftovers.append(column)

    if leftovers:
        return ordered_columns
    if any(column is None for column in resolved):
        return ordered_columns
    return [column for column in resolved if column is not None]


def _parse_one_based_index(value: Any) -> Optional[int]:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, float):
        if float(value).is_integer():
            parsed = int(value)
            return parsed if parsed > 0 else None
        return None
    text = normalize_reverse_fill_text(value)
    if not _NUMBER_TEXT_RE.fullmatch(text):
        return None
    parsed = int(float(text))
    return parsed if parsed > 0 else None


def _ensure_supported_choice_value(text: str) -> None:
    if "┋" in text:
        raise ValueError("检测到多选串（┋），V1 不支持")
    if "→" in text:
        raise ValueError("检测到排序串（→），V1 不支持")
    if "〖" in text and "〗" in text:
        raise ValueError("检测到“选项+附加填空”复合值，V1 不支持")


def _option_text_index_map(option_texts: Iterable[Any]) -> Dict[str, Optional[int]]:
    mapping: Dict[str, Optional[int]] = {}
    for index, option_text in enumerate(option_texts):
        for variant in label_variants(option_text):
            if variant in mapping and mapping[variant] != index:
                mapping[variant] = None
            else:
                mapping[variant] = index
    return mapping


def _resolve_choice_index(
    *,
    raw_value: Any,
    export_format: str,
    option_map: Dict[str, Optional[int]],
    option_texts: List[Any],
) -> int:
    text = normalize_reverse_fill_text(raw_value)
    if export_format == REVERSE_FILL_FORMAT_WJX_SEQUENCE:
        one_based = _parse_one_based_index(raw_value)
        if one_based is None:
            raise ValueError(f"无法把值“{text}”解析为序号")
        zero_based = one_based - 1
        if zero_based < 0 or zero_based >= len(option_texts):
            raise ValueError(f"序号 {one_based} 超出选项范围")
        return zero_based

    exact_matches = [
        index for index, label in enumerate(option_texts)
        if normalize_reverse_fill_key(label) == normalize_reverse_fill_key(raw_value)
    ]
    if len(exact_matches) == 1:
        return exact_matches[0]
    if len(exact_matches) > 1:
        raise ValueError(f"值“{text}”匹配到多个题目选项")
    for variant in label_variants(raw_value):
        if variant in option_map:
            index = option_map[variant]
            if index is None:
                raise ValueError(f"值“{text}”匹配到多个题目选项")
            return index

    if export_format in {REVERSE_FILL_FORMAT_WJX_SCORE, REVERSE_FILL_FORMAT_WJX_TEXT}:
        one_based = _parse_one_based_index(raw_value)
        if one_based is not None:
            zero_based = one_based - 1
            if 0 <= zero_based < len(option_texts):
                return zero_based

    raise ValueError(f"无法把值“{text}”匹配到题目选项")


def parse_choice_answer(
    *,
    question_num: int,
    question_type: str,
    raw_value: Any,
    export_format: str,
    option_texts: List[Any],
) -> Optional[ReverseFillAnswer]:
    _ = question_type
    if is_reverse_fill_blank(raw_value):
        return None
    text = normalize_reverse_fill_text(raw_value)
    _ensure_supported_choice_value(text)
    choice_index = _resolve_choice_index(
        raw_value=raw_value,
        export_format=export_format,
        option_map=_option_text_index_map(option_texts),
        option_texts=option_texts,
    )
    return ReverseFillAnswer(
        question_num=question_num, kind=REVERSE_FILL_KIND_CHOICE, choice_index=choice_index
    )


def parse_multiple_answer(
    *,
    question_num: int,
    raw_value: Any,
    export_format: str,
    option_texts: List[Any],
) -> Optional[ReverseFillAnswer]:
    if is_reverse_fill_blank(raw_value):
        return None
    option_map = _option_text_index_map(option_texts)
    indexes: List[int] = []
    for part in str(normalize_reverse_fill_text(raw_value)).split("┋"):
        if not part.strip():
            raise ValueError("多选答案包含空选项")
        _ensure_supported_choice_value(part)
        index = _resolve_choice_index(
            raw_value=part,
            export_format=export_format,
            option_map=option_map,
            option_texts=option_texts,
        )
        if index not in indexes:
            indexes.append(index)
    return ReverseFillAnswer(
        question_num=question_num,
        kind=REVERSE_FILL_KIND_CHOICES,
        choice_indexes=sorted(indexes),
    )


def parse_multiple_row_answer(
    *,
    question_num: int,
    ordered_columns: List[ReverseFillColumn],
    raw_row: ReverseFillRawRow,
    export_format: str,
    option_texts: List[Any],
) -> Optional[ReverseFillAnswer]:
    if len(ordered_columns) == 1:
        column = ordered_columns[0]
        numbered_column = _MULTIPLE_COLUMN_INDEX_RE.search(column.suffix)
        if export_format != REVERSE_FILL_FORMAT_WJX_SEQUENCE or numbered_column is None:
            return parse_multiple_answer(
                question_num=question_num,
                raw_value=raw_row.values_by_column[column.column_index],
                export_format=export_format,
                option_texts=option_texts,
            )
    if not option_texts or len(ordered_columns) != len(option_texts):
        raise ValueError("多选题的选项数量与 Excel 列数不匹配")
    indexes_by_column: Dict[int, int] = {}
    used_indexes: set[int] = set()
    for column in ordered_columns:
        if export_format == REVERSE_FILL_FORMAT_WJX_SEQUENCE:
            match = _MULTIPLE_COLUMN_INDEX_RE.search(column.suffix)
            if match is None:
                raise ValueError(f"多选题列“{column.header}”缺少选项序号")
            index = int(match.group(1)) - 1
        else:
            suffix = normalize_reverse_fill_key(column.suffix)
            matches = [
                index for index, label in enumerate(option_texts)
                if suffix == normalize_reverse_fill_key(label)
                or suffix.endswith(f"({normalize_reverse_fill_key(label)})")
            ]
            if len(matches) != 1:
                raise ValueError(f"多选题列“{column.header}”无法唯一匹配选项")
            index = matches[0]
        if not 0 <= index < len(option_texts) or index in used_indexes:
            raise ValueError(f"多选题列“{column.header}”的选项超出范围或重复")
        indexes_by_column[column.column_index] = index
        used_indexes.add(index)

    values = [raw_row.values_by_column[column.column_index] for column in ordered_columns]
    if all(is_reverse_fill_blank(value) for value in values):
        return None
    selected: List[int] = []
    for column, value in zip(ordered_columns, values, strict=True):
        text = normalize_reverse_fill_text(value)
        if isinstance(value, bool) or text not in {"0", "1"}:
            raise ValueError(f"多选题列“{column.header}”的值必须为 0 或 1")
        if text == "1":
            selected.append(indexes_by_column[column.column_index])
    return ReverseFillAnswer(
        question_num=question_num,
        kind=REVERSE_FILL_KIND_CHOICES,
        choice_indexes=sorted(selected),
    )


def parse_text_answer(*, question_num: int, raw_value: Any) -> Optional[ReverseFillAnswer]:
    if is_reverse_fill_blank(raw_value):
        return None
    return ReverseFillAnswer(
        question_num=question_num,
        kind=REVERSE_FILL_KIND_TEXT,
        text_value=normalize_reverse_fill_text(raw_value),
    )


def parse_multi_text_answer(
    *,
    question_num: int,
    ordered_columns: List[ReverseFillColumn],
    raw_row: ReverseFillRawRow,
) -> Optional[ReverseFillAnswer]:
    values: List[str] = []
    has_value = False
    for column in ordered_columns:
        raw_value = raw_row.values_by_column.get(column.column_index)
        text = normalize_reverse_fill_text(raw_value)
        if text:
            has_value = True
        values.append(text)
    if not has_value:
        return None
    return ReverseFillAnswer(
        question_num=question_num,
        kind=REVERSE_FILL_KIND_MULTI_TEXT,
        text_values=values,
    )


def parse_matrix_answer(
    *,
    question_num: int,
    ordered_columns: List[ReverseFillColumn],
    raw_row: ReverseFillRawRow,
    export_format: str,
    option_texts: List[Any],
) -> Optional[ReverseFillAnswer]:
    values: List[Any] = []
    for column in ordered_columns:
        values.append(raw_row.values_by_column.get(column.column_index))
    if all(is_reverse_fill_blank(value) for value in values):
        return None
    if any(is_reverse_fill_blank(value) for value in values):
        raise ValueError("矩阵题存在部分行为空，V1 不能可靠回放")
    row_indexes: List[int] = []
    for raw_value in values:
        parsed = parse_choice_answer(
            question_num=question_num,
            question_type="matrix",
            raw_value=raw_value,
            export_format=export_format,
            option_texts=option_texts,
        )
        if parsed is None or parsed.choice_index is None:
            raise ValueError("矩阵题行值解析失败")
        row_indexes.append(int(parsed.choice_index))
    return ReverseFillAnswer(
        question_num=question_num,
        kind=REVERSE_FILL_KIND_MATRIX,
        matrix_choice_indexes=row_indexes,
    )
