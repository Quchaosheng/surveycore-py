from pathlib import Path

import pytest
from openpyxl import Workbook

from surveycore.core.reverse_fill.actions import build_reverse_fill_action
from surveycore.core.reverse_fill.parser import (
    parse_multiple_row_answer,
    supports_reverse_fill_runtime,
)
from surveycore.core.reverse_fill.schema import (
    REVERSE_FILL_FORMAT_WJX_SCORE,
    REVERSE_FILL_FORMAT_WJX_SEQUENCE,
    REVERSE_FILL_FORMAT_WJX_TEXT,
    ReverseFillAnswer,
    ReverseFillColumn,
    ReverseFillRawRow,
    ReverseFillSampleRow,
    ReverseFillSpec,
)
from surveycore.core.task import ExecutionConfig, ExecutionState
from surveycore.io.spreadsheets.wjx_excel import load_wjx_excel_export
from surveycore.providers.contracts import SurveyQuestionMeta
from surveycore.wjx.provider.answering_builders import build_answer_action
from surveycore.wjx.provider.http_runtime import _submitdata_from_actions


@pytest.fixture
def multiple_columns() -> list[ReverseFillColumn]:
    return [
        ReverseFillColumn(1, "5、标题(选项1)", 5, "标题(选项1)"),
        ReverseFillColumn(2, "5、(选项2)", 5, "(选项2)"),
        ReverseFillColumn(3, "5、(选项3)", 5, "(选项3)"),
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("export_format", [REVERSE_FILL_FORMAT_WJX_SEQUENCE, REVERSE_FILL_FORMAT_WJX_TEXT])
async def test_excel_multiple_formats_reach_wjx_submission_payload(tmp_path: Path, export_format) -> None:
    path = tmp_path / "multiple.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    assert sheet is not None
    if export_format == REVERSE_FILL_FORMAT_WJX_SEQUENCE:
        sheet.append(["序号", "4、啥？", "5、标题(选项1)", "5、(选项2)", "5、(选项3)"])
    else:
        sheet.append(["序号", "4、啥？", "5、标题"])
    cases = [
        ([1, 0, 0], "5$1"),
        ([0, 1, 0], "5$2"),
        ([0, 0, 1], "5$3"),
        ([1, 1, 0], "5$1|2"),
        ([1, 0, 1], "5$1|3"),
        ([0, 1, 1], "5$2|3"),
        ([1, 1, 1], "5$1|2|3"),
    ]
    for number, (values, _) in enumerate(cases, start=1):
        if export_format == REVERSE_FILL_FORMAT_WJX_SEQUENCE:
            sheet.append([number, f"SCX-1109-{number:02d}", *values])
        else:
            text = "┋".join(f"选项{index + 1}" for index, selected in enumerate(values) if selected)
            sheet.append([number, f"SCX-1109-{number:02d}", text])
    workbook.save(path)
    workbook.close()
    export = load_wjx_excel_export(str(path))
    assert export.selected_format == export_format
    question = SurveyQuestionMeta(
        num=5, title="标题", type_code="4", required=True,
        option_texts=["选项1", "选项2", "选项3"],
    )
    samples = []
    for row in export.raw_rows:
        answer = parse_multiple_row_answer(
            question_num=5, ordered_columns=export.question_columns[5], raw_row=row,
            export_format=export.selected_format, option_texts=question.option_texts,
        )
        assert answer is not None
        samples.append(ReverseFillSampleRow(row.data_row_number, row.worksheet_row_number, {5: answer}))
    spec = ReverseFillSpec(
        source_path=str(path), selected_format=export.selected_format,
        detected_format=export.detected_format, start_row=1, total_samples=7,
        available_samples=7, target_num=7, samples=samples,
    )
    state = ExecutionState(config=ExecutionConfig(
        reverse_fill_spec=spec, target_num=7, question_config_index_map={5: ("multiple", 0)},
        multiple_prob=[[0.0, 0.0, 100.0]],
    ))
    state.initialize_reverse_fill_runtime()
    for number, (_, expected) in enumerate(cases, start=1):
        acquired = state.acquire_reverse_fill_sample("slot")
        assert acquired.sample is not None
        assert acquired.sample.data_row_number == number
        action = await build_answer_action(None, question, state, psycho_plan=None, thread_name="slot")
        assert action is not None
        assert action.input_type == "checkbox"
        assert not action.pending_distribution_choices
        assert _submitdata_from_actions([action]) == expected
        assert state.commit_reverse_fill_sample("slot") == number


def test_multiple_columns_map_by_option_number_after_reordering(multiple_columns) -> None:
    answer = parse_multiple_row_answer(
        question_num=5, ordered_columns=list(reversed(multiple_columns)),
        raw_row=ReverseFillRawRow(1, 2, {1: "1", 2: 0.0, 3: 1.0}),
        export_format=REVERSE_FILL_FORMAT_WJX_SEQUENCE, option_texts=["甲", "乙", "丙"],
    )
    assert answer is not None
    assert answer.kind == "choices"
    assert answer.choice_indexes == [0, 2]


@pytest.mark.parametrize("export_format", [REVERSE_FILL_FORMAT_WJX_TEXT, REVERSE_FILL_FORMAT_WJX_SCORE])
def test_multiple_columns_match_exact_option_labels(export_format) -> None:
    answer = parse_multiple_row_answer(
        question_num=5,
        ordered_columns=[
            ReverseFillColumn(1, "5、标题（乙）", 5, "标题（乙）"),
            ReverseFillColumn(2, "5、(甲)", 5, "(甲)"),
        ],
        raw_row=ReverseFillRawRow(1, 2, {1: 1, 2: 0}),
        export_format=export_format, option_texts=["甲", "乙"],
    )
    assert answer is not None
    assert answer.choice_indexes == [1]


@pytest.mark.parametrize("value", [True, 2, -1, "yes", None, ""])
def test_multiple_columns_reject_invalid_or_partial_blank_flags(multiple_columns, value) -> None:
    with pytest.raises(ValueError, match="0 或 1"):
        parse_multiple_row_answer(
            question_num=5, ordered_columns=multiple_columns,
            raw_row=ReverseFillRawRow(1, 2, {1: 1, 2: value, 3: 0}),
            export_format=REVERSE_FILL_FORMAT_WJX_SEQUENCE, option_texts=["甲", "乙", "丙"],
        )


@pytest.mark.parametrize("suffixes", [
    ["(选项1)", "(选项2)"],
    ["(选项1)", "(选项1)", "(选项3)"],
    ["(选项0)", "(选项2)", "(选项3)"],
    ["(选项1)", "(选项2)", "(选项4)"],
    ["甲", "乙", "丙"],
])
def test_multiple_columns_reject_incomplete_or_ambiguous_mapping(suffixes) -> None:
    with pytest.raises(ValueError, match="多选题"):
        parse_multiple_row_answer(
            question_num=5,
            ordered_columns=[ReverseFillColumn(i, f"5、{suffix}", 5, suffix)
                             for i, suffix in enumerate(suffixes, start=1)],
            raw_row=ReverseFillRawRow(1, 2, {1: 1, 2: 0, 3: 0}),
            export_format=REVERSE_FILL_FORMAT_WJX_SEQUENCE, option_texts=["甲", "乙", "丙"],
        )


def test_blank_multiple_row_keeps_missing_answer_contract(multiple_columns) -> None:
    assert parse_multiple_row_answer(
        question_num=5, ordered_columns=multiple_columns,
        raw_row=ReverseFillRawRow(1, 2, {1: None, 2: "", 3: " "}),
        export_format=REVERSE_FILL_FORMAT_WJX_SEQUENCE, option_texts=["甲", "乙", "丙"],
    ) is None


def test_zero_flags_are_an_empty_selection_instead_of_a_missing_answer(multiple_columns) -> None:
    answer = parse_multiple_row_answer(
        question_num=5, ordered_columns=multiple_columns,
        raw_row=ReverseFillRawRow(1, 2, {1: 0, 2: 0, 3: 0}),
        export_format=REVERSE_FILL_FORMAT_WJX_SEQUENCE, option_texts=["甲", "乙", "丙"],
    )
    assert answer is not None
    assert answer.choice_indexes == []
    with pytest.raises(ValueError, match="第5题"):
        build_reverse_fill_action(answer, SurveyQuestionMeta(num=5, title="标题", options=3), "multiple")


def test_single_option_multiple_export_detects_sequence_format(tmp_path: Path) -> None:
    path = tmp_path / "single_option.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    assert sheet is not None
    sheet.append(["5、标题(选项1)"])
    sheet.append([1])
    workbook.save(path)
    workbook.close()
    export = load_wjx_excel_export(str(path))
    assert export.selected_format == REVERSE_FILL_FORMAT_WJX_SEQUENCE
    answer = parse_multiple_row_answer(
        question_num=5, ordered_columns=export.question_columns[5], raw_row=export.raw_rows[0],
        export_format=export.selected_format, option_texts=["甲"],
    )
    assert answer is not None
    assert answer.choice_indexes == [0]


@pytest.mark.parametrize(("indexes", "minimum", "maximum"), [
    ([], None, None), ([0], 2, 3), ([0, 1, 2], 1, 2),
    ([0, 0], None, None), ([-1], None, None), ([3], None, None),
])
def test_multiple_action_rejects_invalid_selection(indexes, minimum, maximum) -> None:
    question = SurveyQuestionMeta(
        num=5, title="标题", type_code="4", required=True, option_texts=["甲", "乙", "丙"],
        multi_min_limit=minimum, multi_max_limit=maximum,
    )
    with pytest.raises(ValueError, match="第5题"):
        build_reverse_fill_action(ReverseFillAnswer(5, "choices", choice_indexes=indexes), question, "multiple")


def test_multiple_action_preserves_exact_selection_at_count_limits() -> None:
    question = SurveyQuestionMeta(
        num=5, title="标题", option_texts=["甲", "乙", "丙"], multi_min_limit=2, multi_max_limit=2,
    )
    action = build_reverse_fill_action(
        ReverseFillAnswer(5, "choices", choice_indexes=[0, 2]), question, "multiple",
    )
    assert action.selected_indices == (0, 2)
    assert action.selected_texts == ("甲", "丙")


def test_multiple_with_attached_inputs_stays_unsupported() -> None:
    assert supports_reverse_fill_runtime("multiple", {})
    assert not supports_reverse_fill_runtime("multiple", {"fillable_options": [0]})
    assert not supports_reverse_fill_runtime("multiple", {"attached_option_selects": [{"index": 0}]})
