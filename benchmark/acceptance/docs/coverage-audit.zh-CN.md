# DeckProbe 验收覆盖审计

审计日期：2026-09-05

## 结论

GT 的总体能力边界应当覆盖 DeckProbe 发布版本公开的全部可探测 target，但不应要求每一份样本机械维护全部 target。声明矩阵负责“大而全”，每份样本的 GT 负责证明该样本有区分度的事实、限制和边界行为。

第三方工具的原始输出不要求伪装成 DeckProbe 输出，也不直接成为 GT。适配器将独立观测转成 `benchmark-gt.schema.json` 的 `normalizedRecord`；人工审批把其中可采信的 `fieldObservation` 冻结为 GT；比较器再根据 `target_mapping` 和 `ground_truth.comparator` 与 DeckProbe 结果比较。

## 实际发布契约核对

使用 DeckProbe v2.5.0 发布二进制执行 `schema` 和 catalog 核对：

- live catalog：124 个 target；
- `benchmark-gt.schema.json`：124 个 target；
- 缺失 target：0；
- 多余 target：0；
- target schema 类型差异：0；
- 内嵌 DeckProbe report schema：与发布二进制完全一致；
- 三份 GT v2 示例产物：均通过 Draft 2020-12 校验。

验证入口：

```bash
python3 格式测试数据集/验证benchmark契约.py --deckprobe /path/to/released/deckprobe
```

## 声明矩阵

当前声明矩阵由 live catalog 和扩展名到 profile 的解析关系生成：

| 维度 | 当前数量 |
|---|---:|
| 扩展名 | 26 |
| resolved profile | 23 |
| unique target | 124 |
| profile-target 对 | 823 |
| profile-target-level 声明行 | 2,104 |
| encrypted-ooxml 声明行 | 162 |
| encrypted-ooxml unique target 对 | 22 |

请求级别覆盖 `header`、`metadata` 和 `deep`。矩阵不能通过删除产品 target 自动提高覆盖率；所有声明行必须按同一摘要人工批准。

必须另行绑定并审核六类场景：身份识别、扩展名与内容错配、缺失与零值、安全特征正反样本、已声明限制、预算边界。场景未绑定答案时，快照不能生成 `READY`。

## 独立审计问题及修复

| 审计问题 | 当前实现 |
|---|---|
| GT v2 未接入维护和比较链路 | Casework 使用事实模型 v2；独立证据经规范化导入，事实与产品映射分离，比较器支持八种比较方式。 |
| 缺少 encrypted-ooxml profile | DOCX、XLSX、PPTX 已补入该 profile，共 22 个 unique target 对。 |
| requiredScenarios 没有参与执行 | 快照导出、校验和 R03 判定都会读取六个必须场景；缺失、未批准或未执行均不能 PASS。 |
| 空声明矩阵也能 READY | 已改为 fail-closed：空矩阵、草案行、未绑定场景、待审 GT 均拒绝 READY。 |
| R03 无条件 BLOCKED | 改为按批准矩阵、场景、执行结果和缺口共同判定。 |
| R05 只执行不判断 | 已检查 no-piggyback target 集合、exact 路径/值、optional 共享成本以及 budget 错误和退出码。路径与成本必须有批准的 oracle。 |
| candidate 与 previous 没有同条件比较 | R04 增加兼容性差异检查；R06 在同一 runner 中逐点交错执行新旧版本。 |
| R02/R06/R07/R08 缺 hosted runner 证据 | 工作流和采集器已经实现；正式证据只能在公开仓库启用 `READY` 后由 GitHub-hosted runner 产生，当前不得声明已覆盖。 |

## 当前门禁状态

声明矩阵的 2,104 行仍为草案，六个必须场景尚未绑定答案，当前公开快照含 33 条待审核 GT，因此 `READY` 不存在。该状态是输入审批尚未完成，不是 schema 或执行器错误。

GitHub 首轮正式运行后还需检查：Ubuntu 网络隔离控制、Worker 心跳与阻塞对照、MCP good-bad-good 隔离、七个平台的实际架构以及配对性能原始点。上述证据不能由本机单元测试替代。
