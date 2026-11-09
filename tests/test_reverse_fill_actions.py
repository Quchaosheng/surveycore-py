from pathlib import Path

import pytest
from openpyxl import Workbook

from surveycore.core.reverse_fill.actions import build_reverse_fill_action
from surveycore.core.reverse_fill.parser import parse_choice_answer
from surveycore.core.reverse_fill.schema import (
    ReverseFillAnswer,
    ReverseFillSampleRow,
    ReverseFillSpec,
)
from surveycore.core.task import ExecutionConfig, ExecutionState
from surveycore.io.spreadsheets.wjx_excel import load_wjx_excel_export
from surveycore.providers.contracts import SurveyQuestionMeta
from surveycore.wjx.provider.answering_builders import build_answer_action
from surveycore.wjx.provider.http_runtime import _submitdata_from_actions


def _state_with_answer(answer: ReverseFillAnswer, question_type: str) -> ExecutionState:
    spec = ReverseFillSpec(
        source_path="export.xlsx",
        selected_format="wjx_sequence",
        detected_format="wjx_sequence",
        start_row=1,
        total_samples=1,
        available_samples=1,
        target_num=1,
        samples=[ReverseFillSampleRow(1, 2, {1: answer})],
    )
    state = ExecutionState(config=ExecutionConfig(
        reverse_fill_spec=spec, question_config_index_map={1: (question_type, 0)}
    ))
    state.initialize_reverse_fill_runtime()
    state.acquire_reverse_fill_sample("slot")
    return state


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("question_type", "answer", "expected"),
    [
        ("single", ReverseFillAnswer(1, "choice", choice_index=1), "1$2"),
        ("dropdown", ReverseFillAnswer(1, "choice", choice_index=1), "1$2"),
        ("scale", ReverseFillAnswer(1, "choice", choice_index=1), "1$2"),
        ("score", ReverseFillAnswer(1, "choice", choice_index=1), "1$2"),
        ("text", ReverseFillAnswer(1, "text", text_value="张三"), "1$张三"),
        ("multi_text", ReverseFillAnswer(1, "multi_text", text_values=["张三", ""]), "1$张三^"),
        ("matrix", ReverseFillAnswer(1, "matrix", matrix_choice_indexes=[1, 2]), "1$1!2,2!3"),
        ("multiple", ReverseFillAnswer(1, "choices", choice_indexes=[0, 2]), "1$1|3"),
    ],
)
async def test_reverse_fill_overrides_generation_and_builds_submitdata(
    question_type: str, answer: ReverseFillAnswer, expected: str
) -> None:
    state = _state_with_answer(answer, question_type)
    state.config.text_ai_flags = [True]
    question = SurveyQuestionMeta(
        num=1,
        title="问题",
        options=3,
        option_texts=["差", "中", "好"],
        rows=2,
        text_inputs=2 if question_type == "multi_text" else 1,
        forced_option_index=0,
    )

    action = await build_answer_action(None, question, state, psycho_plan=None, thread_name="slot")

    assert action is not None
    assert not action.pending_distribution_choices
    assert _submitdata_from_actions([action]) == expected


@pytest.mark.asyncio
async def test_missing_reverse_answer_uses_regular_question_config() -> None:
    state = _state_with_answer(ReverseFillAnswer(1, "text", text_value="来自Excel"), "text")
    state.config.question_config_index_map[2] = ("text", 0)
    state.config.texts = [["常规答案"]]
    state.config.texts_prob = [[1.0]]
    question = SurveyQuestionMeta(num=2, title="没有映射的题目", type_code="1")

    action = await build_answer_action(None, question, state, psycho_plan=None, thread_name="slot")

    assert action is not None
    assert action.text_values == ("常规答案",)


@pytest.mark.parametrize(
    ("question_type", "answer"),
    [
        ("single", ReverseFillAnswer(1, "choice", choice_index=3)),
        ("single", ReverseFillAnswer(1, "text", text_value="错误类型")),
        ("text", ReverseFillAnswer(1, "multi_text", text_values=["多了", "一个"])),
        ("matrix", ReverseFillAnswer(1, "matrix", matrix_choice_indexes=[0])),
        ("matrix", ReverseFillAnswer(1, "matrix", matrix_choice_indexes=[0, 3])),
        ("multiple", ReverseFillAnswer(1, "choice", choice_index=0)),
        ("multiple", ReverseFillAnswer(1, "choices", choice_indexes=[])),
        ("multiple", ReverseFillAnswer(1, "choices", choice_indexes=[0, 3])),
    ],
)
def test_changed_question_shape_or_unsupported_type_is_rejected(
    question_type: str, answer: ReverseFillAnswer
) -> None:
    question = SurveyQuestionMeta(num=1, title="问题", options=3, rows=2)
    with pytest.raises(ValueError, match="第1题"):
        build_reverse_fill_action(answer, question, question_type)


@pytest.mark.asyncio
async def test_excel_row_reaches_wjx_submission_payload(tmp_path: Path) -> None:
    path = tmp_path / "answers.xlsx"
    workbook = Workbook()
    worksheet = workbook.active
    assert worksheet is not None
    worksheet.append(["序号", "1、满意度"])
    worksheet.append([1, "好"])
    workbook.save(path)
    workbook.close()
    export = load_wjx_excel_export(str(path))
    row = export.raw_rows[0]
    answer = parse_choice_answer(
        question_num=1,
        question_type="single",
        raw_value=row.values_by_column[export.question_columns[1][0].column_index],
        export_format=export.selected_format,
        option_texts=["差", "中", "好"],
    )
    assert answer is not None
    state = _state_with_answer(answer, "single")
    question = SurveyQuestionMeta(num=1, title="满意度", option_texts=["差", "中", "好"])

    action = await build_answer_action(None, question, state, psycho_plan=None, thread_name="slot")

    assert action is not None
    assert _submitdata_from_actions([action]) == "1$3"
    assert state.commit_reverse_fill_sample("slot") == 1
