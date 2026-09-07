# DeckProbe 验证基准

审批者建议先阅读：[DeckProbe v1 验证标准审批单](APPROVAL.zh-CN.md)。新增 PDF 全量覆盖请阅读：[PDF 全量探测新增标准审批单](APPROVAL-PDF.zh-CN.md)。全格式与 CLI 扩展请阅读：[扩展标准审批单](APPROVAL-EXPANSION.zh-CN.md)。下载目录新增的边界语料见：[新增边界语料审批单](APPROVAL-EDGE-CORPUS.zh-CN.md)。Core 2 的角色和评分阈值请单独审批：[质量政策 v1](QUALITY-POLICY.zh-CN.md)。

全格式与 CLI 的当前覆盖率、缺口和后续 Suite 拆分见：[验证覆盖审计](COVERAGE.zh-CN.md)。本次正式结果见：[Core 2.1 质量基线](BASELINE-CORE21-20260814.zh-CN.md)。

可用 live target catalog 重新计算格式覆盖：

```sh
python3 benchmark/tools/audit_target_coverage.py
```

这套基准验证 DeckProbe 是否实现了“按目标选择路径、工作量有界的文档事实探测器”这一业务目标。DeckProbe 不承诺渲染、OCR、全文抽取或语义理解，因此这些能力不在本基准的判定范围内。

## v1 业务质量契约

v1 将以下行为定义为必须满足的产品要求：

1. 探测结果必须符合 DeckProbe 公布的 Schema v2 成功、部分成功或错误信封。canonical target ID、状态、置信度分值、证据路径与来源、未解决 target 和确定性成本计数必须内部一致。
2. 系统先按扩展名选择格式路径，再验证容器和实际文档类型。支持的 PDF、OOXML、Legacy Office 和现代 iWork 文件必须进入预期 driver/profile；加密 OOXML 必须停在加密包边界；不支持的扩展名必须返回稳定错误。
3. 标准答案必须来自源文件本身或独立工具的交叉验证，禁止使用待测 DeckProbe 的输出作为自身 Oracle。
4. 在本版本固定的 corpus 上，metadata 级别的 `@summary,@security` 探测，每个受支持 case 的物理读取量不得超过 1 MiB，累计解压量不得超过 2 MiB。这是已批准的 corpus 级验收阈值，不代表对任意文档大小的普遍承诺。
5. 对固定 PPTX 请求精确幻灯片数量时，记录实际 driver、幻灯片数量、置信度、执行路径和 I/O 成本，作为观察指标；v1 不为该项设置通过/失败阈值。
6. 在 1 KiB 物理读取预算下，固定 DOCX 摘要探测必须返回 `BUDGET_EXCEEDED`，进程退出码为 4。
7. 对相同输入和相同参数执行两次不带 telemetry 的请求，默认 JSON 输出必须逐字节一致。

当前 Suite 固定使用 Core 2 角色/评分契约对应的 `benchmark/evaluators/document-probe-contract/2/` 或 `benchmark/evaluators/cli-contract/2/`；v1 Evaluator 仅保留用于审计历史运行。如果上述语义或阈值改变，必须创建新的 Evaluator 版本，不能直接修改既有版本来迎合运行结果。

## Suite 与覆盖范围

| Suite | 业务目标 | Case 数 | Target |
| --- | --- | ---: | --- |
| `deckprobe-summary-security-v1` | 跨格式事实、格式路由、安全信号、错误契约、证据一致性与聚焦读取成本 | 15 | `deckprobe-summary-security` |
| `deckprobe-exact-slide-count-v1` | 观察精确计数请求的返回值、置信度、Planner 路径和 I/O 成本 | 1 | `deckprobe-exact-slide-count` |
| `deckprobe-budget-v1` | 物理读取硬预算与稳定失败语义 | 1 | `deckprobe-budget-1k` |
| `deckprobe-determinism-v1` | 相同请求的默认输出确定性 | 1 | `deckprobe-repeat-exact-slide-count` |
| `deckprobe-pdf-deep-v1` | PDF Header、Info、结构、安全、附件、表单、批注、XMP 与修复状态 | 1 | `deckprobe-pdf-deep` |
| `deckprobe-cli-contract-v1` | stdin、JSONL、视图、规划、strict、piggyback、discovery、输出和生成命令 | 17 | `deckprobe-cli-contract` |
| `deckprobe-ooxml-deep-v1` | DOCX/XLSX/PPTX 身份、元数据、安全、结构和资产 | 3 | `deckprobe-ooxml-deep` |
| `deckprobe-legacy-deep-v1` | Legacy DOC/PPT 的 CFB、属性、安全边界和可交叉验证结构 | 2 | `deckprobe-legacy-deep` |
| `deckprobe-iwork-deep-v1` | Keynote/Numbers/Pages 的 ZIP/plist/preview/asset 与有限语义 | 3 | `deckprobe-iwork-deep` |
| `deckprobe-runtime-parity-v1` | Native、Node、WASM main thread 与 Worker 一致性 | 3 | `deckprobe-runtime-parity` |
| `deckprobe-edge-corpus-v1` | 伪装/损坏/加密/签名/链接/修复/零值/WebP/动画/中文 Legacy/旧 iWork | 20 | `deckprobe-edge-corpus-deep` |

外部 corpus 通过绝对本地 URI 和 SHA-256 引用，不复制到本仓库。[Oracle 事实记录](oracles/source-facts.json)保存待审阅的源文件事实，[独立检查工具](tools/inspect_source.py)可重新检查 ZIP/XML/plist、PDF 以及 CFB/容器事实。

摘要与安全 suite 当前覆盖：

- 普通 DOCX、PPTX、XLSX 和 PDF；
- 现代 Keynote、Numbers 和 Pages；
- Legacy DOC 和 PPT；
- 三个加密 OOXML 文件；
- HTML、RTF 和未知扩展名三个负向案例。

应用内 dispatcher 已同步到标准 Benchmark Core 2.1（报告契约 2）并通过标准行为检查。质量政策 v1 已批准，10 个 Suite 已建立 Core 2.1 正式评分基线；`runtime-parity` 因 3 个问题和构建产物仍未就绪而保持 draft。当前语料仍未覆盖 `.xls`、`.xlsb`、启用宏的 OOXML、签名 OOXML、真正损坏的 OOXML、加密/JavaScript PDF、旧版 XML iWork、远程/range source 和浏览器/WASM。

## 机器字段与中文审批内容

为兼顾可维护性和审批体验，以下机器契约继续使用稳定英文：

- suite、case、question、feature 和 assertion ID；
- canonical target，例如 `powerpoint.slide_count`；
- check type，例如 `target_equals`；
- 固定枚举和错误码，例如 `draft`、`approved`、`exact`、`UNSUPPORTED_FORMAT`；
- 源文档中的原始标题、工作表名称等精确期望值。

面向审批者的展示名称、能力说明、问题、答案、证据方法和本文档使用中文。中文不会参与检查分支选择，也不会改变 Evaluator 的判断逻辑。

## 审批门禁

A1–A15、C1、D1、E01–E20，以及 CLI/OOXML/Legacy Office/iWork 扩展中的 51 题，其问题和答案保持已批准；B1 和各 Suite 明确标注的 observation 只记录。role/score 与 95/80 质量政策已批准，10 个 Suite 已完成正式运行。多运行时一致性的 3 题仍为 draft。可执行以下结构验证：

```sh
python3 benchmark/scripts/deck_benchmark.py validate --suite deckprobe-summary-security-v1
python3 benchmark/scripts/deck_benchmark.py validate --suite deckprobe-exact-slide-count-v1
python3 benchmark/scripts/deck_benchmark.py validate --suite deckprobe-budget-v1
python3 benchmark/scripts/deck_benchmark.py validate --suite deckprobe-determinism-v1
python3 benchmark/scripts/deck_benchmark.py validate --suite deckprobe-cli-contract-v1
python3 benchmark/scripts/deck_benchmark.py validate --suite deckprobe-ooxml-deep-v1
python3 benchmark/scripts/deck_benchmark.py validate --suite deckprobe-legacy-deep-v1
python3 benchmark/scripts/deck_benchmark.py validate --suite deckprobe-iwork-deep-v1
python3 benchmark/scripts/deck_benchmark.py validate --suite deckprobe-runtime-parity-v1
python3 benchmark/scripts/deck_benchmark.py validate --suite deckprobe-edge-corpus-v1
```

只有在审批者确认或修改每个问题及其标准答案后，才能把问题与 suite 的 `reviewStatus` 改成 `approved`，然后执行正式质量运行：

```sh
python3 benchmark/scripts/deck_benchmark.py run \
  --suite deckprobe-summary-security-v1 \
  --target deckprobe-summary-security \
  --run-id baseline-001
```

其余 suite 使用各自对应的 target。每次通用引擎运行会在 Git 忽略的 `benchmark/artifacts/runs/<suite>/<target>/<run-id>/` 下生成三类产物：

- `report.html`：给审批者阅读。展示问题、审批答案、预期值、实际值、判定细节和逐案例原始证据链接。
- `agent-report.json`：给项目开发者或修复 Agent 消费。包含根因簇、稳定 finding、复现命令、疑似组件、置信度和证据路径。
- `run.json` 与 `raw/*.json`：未经简化的运行信封和逐案例原始证据，用于审计和重建报告。

HTML 与 Agent 报告是面向不同读者的两份正式报告；`run.json` 不作为人工阅读报告。
