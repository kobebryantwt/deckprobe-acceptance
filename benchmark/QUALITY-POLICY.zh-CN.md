# DeckProbe Benchmark 质量政策 v1（已批准）

本政策补齐 Benchmark Core 2 所要求的门禁、评分和观察项分层。它不修改任何已经审批的标准答案，只改变断言如何参与发布判定。

## 三类角色

| 角色 | DeckProbe 中的适用范围 | 失败影响 |
| --- | --- | --- |
| `gate` | Schema v2、driver/profile 路由、格式与容器一致性、错误码、security/quality 边界、预算、确定性、CLI/API 合同 | 任一失败即 `FAIL` |
| `scored` | 有独立 Oracle 的元数据、页/幻灯片/对象/资产/结构计数、名称、尺寸和应用属性 | 进入 feature 评分，不由单个普通事实直接否决整个 Suite |
| `observation` | B1、IWA 深层对象/公式/正文以及 Legacy 内部统计等缺少独立 Oracle 的指标 | 只记录，不影响 Gate、分数或 Finding |

`target_status_equals` 用于验证产品是否诚实表达 `unknown/unsupported`，属于能力边界合同，因此归入 `gate`。安全和完整性 target 即使是普通布尔值，也属于 `gate`。

## 评分政策

- 评分模式：确定性事实使用 binary score，通过为 `1.0`，失败为 `0.0`。
- 检查权重：v1 中每个 scored 检查在所属 feature 内权重均为 `1.0`。
- 聚合顺序：先在每个 feature 内按权重平均，再对所有有 scored 检查的 feature 做宏平均。
- 分数尺度：`0..100`。
- `PASS`：无 Gate 失败、无阻塞、scored coverage 为 100%、质量分数不低于 95，且没有 scored 检查失败。
- `REVIEW`：无 Gate 失败和阻塞，但质量分数在 `[80, 95)`、scored coverage 不足 100%，或仍有任一 scored 检查失败。最后一项是标准 Core 2.1 的固定发布语义，因此即使总分达到 95，仍不会把已知普通事实差异标记为完全通过。
- `FAIL`：任一 Gate 失败，或质量分数低于 80。
- `INCOMPLETE`：运行环境、素材或 Evaluator 阻塞，导致完整判定无法完成。
- 没有 scored 检查的纯合同 Suite（CLI、预算、确定性）质量分数显示为 N/A，只根据 Gate 判定。
- 没有 Gate/scored 的纯观察 Suite 发布判定为 `PASS`，案例状态仍显示 `review`，避免把观察结果误写成事实通过。

95/80 阈值适用于结构化事实探测：目标整体应接近完全正确，但一个普通元数据差异不应与 Schema、路由或安全合同破坏等价。feature 宏平均用于防止检查数量较多的格式压倒其他业务能力。

## 严重级别

- Gate Finding：`major`。
- Scored Finding：`minor`，但当 feature 聚合导致 Suite 低于 80 时，发布判定仍为 `FAIL`。
- Observation：`minor`（标准 Core 仅接受 `critical / major / minor`），且不得生成 actionable Finding；此严重度只用于报告展示，不参与门禁或评分。

## 审批影响

现有问题和答案继续保持原审批结论。本政策已于 2026-08-14 获用户批准；此前已批准问题的 Suite 恢复为 `approved` 并可建立 Core 2.1 评分基线。`runtime-parity` 的 3 个问题仍为 draft，不随本次政策审批自动批准。

## 历史结果重放预览

以下仅用旧运行的原始 target 输出重放 Evaluator v2，帮助审批政策；不是新的正式运行。

| Suite | Gate | 质量分 | 评分覆盖 | 预览判定 | 解释 |
| --- | --- | ---: | ---: | --- | --- |
| summary/security | 65/65 通过 | 91.67 | 100% | REVIEW | 一个 PDF title 普通事实差异 |
| PDF deep | 17/17 通过 | 89.29 | 100% | REVIEW | title 与 link_count 两个评分差异 |
| edge corpus | 47 通过/1 失败 | 90.79 | 100% | FAIL | Legacy 空标题能力边界是 Gate；其余普通事实进入评分 |
| OOXML deep | 51/51 通过 | 98.40 | 100% | REVIEW | DOCX author/description 两个评分差异；标准 Core 对仍有 scored 失败的 Suite 保持 REVIEW |
| Legacy deep | 31/31 通过 | 83.33 | 100% | REVIEW | 两个 CFB 计数差异进入评分 |
| iWork deep | 33 通过/3 失败 | 100.00 | 100% | FAIL | external/missing-data 完整性 Gate 缺失；普通评分事实全对 |
| CLI contract | 61 通过/1 失败 | N/A | N/A | FAIL | Schema discovery 根对象合同 Gate 失败 |
| budget | 2/2 通过 | N/A | N/A | PASS | 纯 Gate Suite |
| determinism | 2/2 通过 | N/A | N/A | PASS | 纯 Gate Suite |
| exact slide observation | 无 Gate | N/A | N/A | PASS | 案例仍标记 review，只记录 B1 |
| runtime parity | 未运行 | N/A | N/A | 无预览 | 缺 JS/WASM/release 构建产物 |
