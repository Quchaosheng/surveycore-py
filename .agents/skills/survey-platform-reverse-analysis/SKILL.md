---
name: survey-platform-reverse-analysis
description: 面向 surveycore-py 的问卷平台链路分析与适配技能。用于梳理问卷星、腾讯问卷、Credamo 见数等平台的入口页、初始化接口、题目结构、提交接口、校验字段、签名字段和页面解析流程，结合页面、日志、HAR、请求响应做合规调试与适配。
---

# survey-platform-reverse-analysis

这个 skill 处理问卷平台的请求流程、参数来源、签名字段、页面解析和 provider 适配，只做事实提取、参数归类和合规调试。

## when_to_use

- 有页面、抓包、HAR、请求响应或日志，需要分析平台流程。
- 需要区分固定值、动态值、环境值和用户输入值。
- 需要把平台解析、提交或校验逻辑落到 `src/surveycore/wjx/provider/`、`src/surveycore/tencent/provider/` 或 `src/surveycore/credamo/provider/`。
- 平台改版导致解析或提交失败，需要从当前证据定位差异。

不要用于绕过验证码、风控、频控或付费限制，也不要把真实 cookie、token、账号密码或代理密钥写入代码、日志或测试。

## workflow

1. 先收页面源码、请求响应、HAR、运行日志和配置样本。
2. 按入口页、初始化接口、题目结构、提交接口和校验接口拆分流程。
3. 对每个参数标记固定值、动态值、环境值或用户输入值，并区分已确认、推测和待验证。
4. 先读 `src/surveycore/providers/` 与目标平台 provider，再做最小适配；不要把平台字段放进通用网络层。
5. 日志脱敏，普通测试不访问真实问卷或账号。

## project_conventions

- 平台代码位于 `src/surveycore/wjx/`、`src/surveycore/tencent/` 和 `src/surveycore/credamo/`。
- 通用 provider 契约位于 `src/surveycore/providers/`。
- 测试位于 `tests/`，以真实代码和当前样本为准。
- 不确定的接口行为标记为“待验证”。

## validation_checklist

- 是否基于页面、日志、HAR 或请求响应提取事实。
- 流程是否拆清入口、初始化、题目、提交和校验。
- 参数是否区分固定、动态、环境和用户输入。
- 结论是否明确标注已确认、推测或待验证。
- 平台逻辑是否仍隔离在对应 provider。
- 是否避免敏感信息和越权的反爬绕过。
- 测试、构建和静态检查是否遵循仓库 `AGENTS.md`，未运行的检查是否明确标注。
