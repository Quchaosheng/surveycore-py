---
name: question-parser-rules
description: 面向 surveycore-py 的题型解析、字段映射与 provider parser 规则技能。用于修改 `src/surveycore/wjx/`、`src/surveycore/tencent/`、`src/surveycore/credamo/`、`src/surveycore/core/` 中的题目结构解析、元数据字段、题型识别、逻辑规则标记和最小兼容适配。
---

# Question Parser Rules

这个 skill 处理题目如何被识别、落成什么字段以及后续如何消费，重点是保持 parser 输出稳定并隔离平台差异。

## must_read

- `src/surveycore/providers/contracts.py`
- `src/surveycore/core/questions/`
- 目标平台的 `src/surveycore/<platform>/provider/`
- 对应 `tests/` 测试文件

## workflow

1. 先定范围：入口字段、题型识别、选项/行/填空字段、逻辑规则或答案构造是否发生变化。
2. 先收事实：HTML、JSON、现有 parser 输出和失败日志。
3. 把平台专属解析留在 `src/surveycore/<platform>/provider/`，通用题目字段留在 `src/surveycore/core/questions/`，契约留在 `src/surveycore/providers/contracts.py`。
4. 做最小适配，优先补具体题型规则和回归测试，不顺手重写 parser。
5. 如果 parser 输出字段改变，检查 provider answering builders、runtime preparation 以及根包模型与 `providers.contracts` 的转换。

## field_rules

重点检查 `type_code`、`option_texts`、`rows`、`row_texts`、`text_inputs`、`text_input_labels`、`fillable_options`、`attached_option_selects`、`is_location`、`is_rating`、`multi_min_limit`、`multi_max_limit`、`has_jump`、`jump_rules`、`has_display_condition`、`display_conditions`、`has_dependent_display_logic`、`controls_display_targets` 和 `logic_parse_status`。

这些字段的语义变化会影响答案构造、反填和运行时，不能只改解析器而不看消费方。

## boundaries

- 平台差异留在 `src/surveycore/wjx/`、`src/surveycore/tencent/`、`src/surveycore/credamo/`。
- 通用层不要出现平台私有字段判断。
- 题型解析和 HTTP 调度分开；提交并发、超时和重试留在 provider runtime 与 network 层。
- 接口事实提取和签名字段归类使用 `survey-platform-reverse-analysis`，本 skill 只负责把题目结构落成可消费数据。

## validation_checklist

仓库 `AGENTS.md` 当前要求把测试、构建和静态检查交给远端 CI。可以在本地补测试并检查源码、差异和 Git 状态，但不能将未运行的测试描述为通过。

- 是否先拿到了 HTML、接口 payload 或失败日志。
- 规则是否落在对应平台目录，没有把平台逻辑塞进通用层。
- parser 输出字段语义是否仍符合现有契约。
- 改了字段后是否检查消费方。
- 是否补了有价值的 provider 或 `tests/` 边界测试。
- 是否避免了无关重构并遵守 `AGENTS.md` 的验证和提交边界。
