from __future__ import annotations

from surveycore.providers.answering import AnswerAction
from surveycore.providers.contracts import SurveyQuestionMeta

from .parser import supports_reverse_fill_runtime
from .schema import (
    REVERSE_FILL_KIND_CHOICE,
    REVERSE_FILL_KIND_MATRIX,
    REVERSE_FILL_KIND_MULTI_TEXT,
    REVERSE_FILL_KIND_TEXT,
    ReverseFillAnswer,
)


def build_reverse_fill_action(
    answer: ReverseFillAnswer, question: SurveyQuestionMeta, question_type: str
) -> AnswerAction:
    current = question.num
    if answer.question_num != current or not supports_reverse_fill_runtime(question_type, question):
        raise ValueError(f"第{current}题与反填答案不匹配")
    option_count = len(question.option_texts) or question.options
    if question_type in {"single", "dropdown", "scale", "score"}:
        index = answer.choice_index
        if answer.kind != REVERSE_FILL_KIND_CHOICE or index is None or not 0 <= index < option_count:
            raise ValueError(f"第{current}题反填选项超出范围或类型不匹配")
        return AnswerAction(
            question_num=current,
            kind="select" if question_type == "dropdown" else "choice",
            input_type="" if question_type == "dropdown" else "radio",
            selected_indices=(index,),
            selected_texts=(question.option_texts[index] if question.option_texts else "",),
            record_type=question_type,
        )
    if question_type in {"text", "multi_text"}:
        if answer.kind == REVERSE_FILL_KIND_TEXT:
            values = (answer.text_value,)
        elif answer.kind == REVERSE_FILL_KIND_MULTI_TEXT:
            values = tuple(answer.text_values)
        else:
            raise ValueError(f"第{current}题反填文本类型不匹配")
        if len(values) != max(1, question.text_inputs):
            raise ValueError(f"第{current}题反填填空数量不匹配")
        return AnswerAction(
            question_num=current, kind="text", text_values=values, record_type="text"
        )
    indexes = tuple(answer.matrix_choice_indexes)
    if (
        answer.kind != REVERSE_FILL_KIND_MATRIX
        or len(indexes) != max(1, question.rows)
        or any(not 0 <= index < option_count for index in indexes)
    ):
        raise ValueError(f"第{current}题反填矩阵行数、选项或类型不匹配")
    return AnswerAction(
        question_num=current, kind="matrix", matrix_indices=indexes, record_type="matrix"
    )
