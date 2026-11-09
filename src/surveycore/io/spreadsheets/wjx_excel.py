from __future__ import annotations

import os
import re
from typing import Any, Dict, List

from surveycore.core.reverse_fill.schema import (
    REVERSE_FILL_FORMAT_AUTO,
    REVERSE_FILL_FORMAT_WJX_SCORE,
    REVERSE_FILL_FORMAT_WJX_SEQUENCE,
    REVERSE_FILL_FORMAT_WJX_TEXT,
    ReverseFillColumn,
    ReverseFillRawRow,
    WjxExcelExport,
)

_QUESTION_HEADER_RE = re.compile(r"^\s*(\d+)\s*[、,.，．]\s*(.*?)\s*$")
_SEQUENCE_SUFFIX_RE = re.compile(r"[（(]\s*选项\s*\d+\s*[)）]\s*$")


def _cell_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return text


def _detect_wjx_export_format(question_columns: Dict[int, List[ReverseFillColumn]], raw_rows: List[ReverseFillRawRow]) -> str:
    for columns in question_columns.values():
        if any(_SEQUENCE_SUFFIX_RE.search(column.suffix) for column in columns):
            return REVERSE_FILL_FORMAT_WJX_SEQUENCE

    for row in raw_rows[:5]:
        for columns in question_columns.values():
            for column in columns:
                value = row.values_by_column[column.column_index]
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    return REVERSE_FILL_FORMAT_WJX_SCORE
    return REVERSE_FILL_FORMAT_WJX_TEXT


def load_wjx_excel_export(source_path: str, *, preferred_format: str = REVERSE_FILL_FORMAT_AUTO) -> WjxExcelExport:
    from openpyxl import load_workbook

    raw_path = str(source_path or "").strip()
    if not raw_path:
        raise ValueError("未提供 Excel 文件路径")
    path = os.path.abspath(raw_path)
    if not os.path.exists(path):
        raise ValueError(f"Excel 文件不存在：{path}")

    workbook = load_workbook(path, read_only=True, data_only=True)
    try:
        if not workbook.sheetnames:
            raise ValueError("Excel 中没有可读取的工作表")
        worksheet = workbook[workbook.sheetnames[0]]
        rows_iter = worksheet.iter_rows(values_only=True)
        header_cells = next(rows_iter, None)
        if not header_cells:
            raise ValueError("Excel 缺少表头，无法识别问卷列")

        question_columns: Dict[int, List[ReverseFillColumn]] = {}
        for column_index, value in enumerate(header_cells, start=1):
            header = _cell_text(value)
            match = _QUESTION_HEADER_RE.match(header)
            if not match:
                continue
            question_num = int(match.group(1))
            suffix = str(match.group(2) or "").strip()
            question_columns.setdefault(question_num, []).append(
                ReverseFillColumn(
                    column_index=column_index,
                    header=header,
                    question_num=question_num,
                    suffix=suffix,
                )
            )

        raw_rows: List[ReverseFillRawRow] = []
        for data_row_number, row_cells in enumerate(rows_iter, start=1):
            values_by_column: Dict[int, Any] = {}
            for column_list in question_columns.values():
                for column in column_list:
                    position = column.column_index - 1
                    values_by_column[column.column_index] = row_cells[position] if position < len(row_cells) else None
            raw_rows.append(
                ReverseFillRawRow(
                    data_row_number=data_row_number,
                    worksheet_row_number=data_row_number + 1,
                    values_by_column=values_by_column,
                )
            )

        detected_format = _detect_wjx_export_format(question_columns, raw_rows)
        selected_format = str(preferred_format or REVERSE_FILL_FORMAT_AUTO).strip().lower()
        if selected_format == REVERSE_FILL_FORMAT_AUTO:
            selected_format = detected_format
        return WjxExcelExport(
            source_path=path,
            detected_format=detected_format,
            selected_format=selected_format,
            header_row_number=1,
            total_data_rows=len(raw_rows),
            question_columns=question_columns,
            raw_rows=raw_rows,
        )
    finally:
        workbook.close()
