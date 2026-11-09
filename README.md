# surveycore-py

[![Python](https://img.shields.io/badge/python-3.11%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/downloads/release/python-3110/)
[![Async](https://img.shields.io/badge/async-httpx-2C5BB4?logo=python&logoColor=white)](https://www.python-httpx.org/async/)
[![Ruff](https://img.shields.io/badge/lint-Ruff-D7FF64?logo=ruff&logoColor=261230)](https://docs.astral.sh/ruff/)
[![ty](https://img.shields.io/badge/types-ty-D7FF64)](https://docs.astral.sh/ty/)

[![CI](https://github.com/SurveyController/surveycore-py/actions/workflows/ci.yml/badge.svg)](https://github.com/SurveyController/surveycore-py/actions/workflows/ci.yml)

纯 HTTP 异步提交问卷的 Python 工具包，支持问卷星、腾讯问卷、 Credamo 见数三大平台

> [!CAUTION]
>
> **本项目仅可用于已授权问卷的学习与测试。严禁用于污染他人问卷数据！**

## 支持平台

- [x] 问卷星
- [x] 腾讯问卷
- [x] Credamo 见数
- [ ] 其他平台（欢迎贡献）

## 准备

### 环境要求

- Python 3.11+ （推荐 Python 3.13.17）

### 安装

[![uv](https://img.shields.io/badge/managed%20with-uv-DE5FE9?logo=astral&logoColor=white)](https://docs.astral.sh/uv/)

```bash
uv add surveycore-py
```

或

![pip](https://img.shields.io/badge/managed%20with-pip-3776AB?logo=pypi&logoColor=white)

```bash
python -m pip install surveycore-py
```

## 示例

### 解析问卷

示例：

```python
import asyncio

import httpx

from surveycore import SurveyClient


async def main() -> None:
    async with httpx.AsyncClient() as http_client:
        client = SurveyClient(http_client)
        survey = await client.parse("https://www.wjx.cn/vm/example.aspx")
        print(survey.title)
        print(survey.questions)


asyncio.run(main())
```

### 运行提交任务

示例：

```python
import asyncio

import httpx

from surveycore import RunConfig, SurveyClient


async def main() -> None:
    config = RunConfig(
        url="https://www.wjx.cn/vm/example.aspx",
        target=3,
        concurrency=2,
    )

    async with httpx.AsyncClient() as http_client:
        client = SurveyClient(http_client)
        async for result in client.run(config):
            print(result.attempt, result.success, result.error)


asyncio.run(main())
```

## 公开接口

| 接口 | 作用 |
|---|---|
| `SurveyClient.parse()` | 识别平台并解析问卷结构 |
| `SurveyClient.submit()` | 提交一次问卷尝试 |
| `SurveyClient.run()` | 按 `target` 和 `concurrency` 调度提交 |
| `AnswerGenerator` | 定义可选的同步或异步答案生成器协议 |
| `SurveyDefinition` / `SurveyQuestion` | 表示解析后的问卷和题目结构 |
| `QuestionConfig` / `RunConfig` | 定义题目策略和调度参数 |
| `SubmissionRequest` / `SubmissionResult` | 表示单次提交请求和结果 |
| `serialize_config()` / `deserialize_config()` | 在配置对象与字典之间转换 |
| `dumps_config()` / `loads_config()` | 在配置对象与 JSON 之间转换 |
| `surveycore.__version__` | 返回已安装发行版版本 |

公开异常包括：

- `SurveyCoreError`：所有公开异常的基类
- `UnsupportedSurveyError`：链接或平台不受支持
- `SurveyUnavailableError`：问卷未开放、暂停或到期
- `SurveyParseError`：问卷解析失败
- `ConfigError`：配置无效或 schema 不兼容
- `SubmissionError`：已导出的提交异常类型；`SurveyClient.submit()` 当前将单次提交异常写入 `SubmissionResult.error`

## Excel 反填集成

安装可选的 Excel 读取依赖：

```bash
uv add "surveycore-py[excel]"
```

反填通过独立的应用集成接口提供，不在 `RunConfig` 中保存文件路径，也不由 `SurveyClient` 隐式读取文件。

```python
from surveycore.core.reverse_fill.parser import parse_choice_answer
from surveycore.io.spreadsheets.wjx_excel import load_wjx_excel_export

export = load_wjx_excel_export("answers.xlsx", preferred_format="auto")
column = export.question_columns[1][0]
row = export.raw_rows[0]
answer = parse_choice_answer(
    question_num=1,
    question_type="single",
    raw_value=row.values_by_column[column.column_index],
    export_format=export.selected_format,
    option_texts=["差", "中", "好"],
)
```

读取器识别首张工作表中的题号列，支持问卷星序号、分数和文本导出格式。异步程序应通过 `asyncio.to_thread()` 调用 Excel 读取器，避免阻塞事件循环。

应用将解析结果按行组装为 `ReverseFillSampleRow` 和 `ReverseFillSpec`，传入 `ExecutionConfig.reverse_fill_spec`，再调用 `ExecutionState.initialize_reverse_fill_runtime()`。提交前通过 `acquire_reverse_fill_sample(slot)` 领取整行；确认成功后调用 `commit_reverse_fill_sample(slot)`，取消时通过 `release_reverse_fill_sample(slot)` 归还。失败重试仅由调用方显式调用 `mark_reverse_fill_submission_failed()` 决定。

样本队列也可直接通过 `surveycore.core.reverse_fill.runtime` 使用，不依赖任务状态、HTTP 客户端或 Excel 读取器。问卷星答案入口统一将已领取的样本转换为 `AnswerAction`，缺少答案的题目沿用常规配置。支持单选、下拉、量表、评分、文本、多项填空和矩阵；多选、排序、位置及带附加输入的选择题仍由应用预检决定如何使用常规配置。题号、选项范围或行数与当前问卷不符时抛出错误。

开发与 CI 使用 `uv sync --locked --extra excel` 安装反填测试所需依赖。

## GPL-3.0 License

您有权免费使用、修改和分发该软件。

但若将程序或其衍生作品对外发布，则**必须同样以 `GPL-3.0` 许可开源，完整公开所有修改后的源代码，并保留原始版权声明与免责条款**，确保所有使用者都能平等地获得并回馈软件的自由，而不论其分发方式为何。
