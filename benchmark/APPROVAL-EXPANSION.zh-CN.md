# DeckProbe 全格式与 CLI 扩展标准审批单

本轮原始提案包含 5 个 Suite、28 个 case、54 个审批问题。CLI、OOXML、Legacy Office 和 iWork 共 51 题的问题与答案已经批准，旧 Evaluator 下已有历史运行；多运行时一致性的 3 题仍为 draft。所有 Suite 现已迁移到 Core 2 的显式角色和 Evaluator v2，但新质量政策仍需单独批准，不能把历史运行当成 Core 2 评分基线。所有标准答案来自公开 CLI 合同、源 ZIP/XML/plist、独立 CFB 目录解析、file/libmagic、LibreOffice 异构转换或既有 PDF Oracle；没有把 DeckProbe 当前输出反写成标准答案。

在你批准前只允许执行结构验证，不运行正式质量判定，也不会把 `reviewStatus` 改成 `approved`。

## 一览

| Suite | Case / 问题 | 新覆盖 | 特殊处理 |
| --- | ---: | --- | --- |
| `deckprobe-cli-contract-v1` | 17 / 17 | stdin、JSONL、view、plan、strict、piggyback、discovery、输出与生成命令 | 全部为门禁 |
| `deckprobe-ooxml-deep-v1` | 3 / 12 | DOCX/XLSX/PPTX 身份、元数据、安全、结构、资产 | 全部为门禁 |
| `deckprobe-legacy-deep-v1` | 2 / 10 | DOC/PPT CFB、属性、安全边界、可交叉验证结构 | 3 组内部计数为观察项 |
| `deckprobe-iwork-deep-v1` | 3 / 12 | Keynote/Numbers/Pages 包、预览、资产和有限语义 | 3 组 IWA 内部指标为观察项 |
| `deckprobe-runtime-parity-v1` | 3 / 3 | Native、Node、WASM、Worker | 需先构建 JS/WASM/release 产物 |

## CLI：C01–C17

| ID | 审批点 | 期望 |
| --- | --- | --- |
| C01 | formats | Schema v2，8 个 driver 边界 |
| C02 | targets pdf | targets、selectors、format options 均可发现 |
| C03 | schema | 根对象、`$defs`、version const=2 |
| C04 | raw stdin | `source_kind=stdin`，PDF 仍为 21 页 |
| C05 | JSONL 错误后继续 | 三行均为 JSON，`ok/error/ok`，退出 1 |
| C06 | values view | 有 values、无完整 results |
| C07 | plan-only | target=planned、path=plan-only、只读 8 字节头 |
| C08 | strict | partial 报告仍输出，进程退出 5 |
| C09 | optional piggyback | object_count 零额外路径返回 |
| C10 | no-piggyback | 可选 object_count 被抑制 |
| C11 | level 别名 | `--level metadata` 与 `-l m` 语义相同 |
| C12 | input-format 不匹配 | PDF 不会被强制按 PPTX 解析，返回 INVALID_REQUEST/1 |
| C13 | 未知 format option | INVALID_REQUEST/1 |
| C14 | pretty | 只改变空白，不改变 JSON 语义 |
| C15 | telemetry | 默认无 elapsed，显式启用后才有 |
| C16 | completion zsh | 生成非空补全脚本 |
| C17 | generate man | 生成含标题与 SYNOPSIS 的 man 页面 |

完整措辞和断言见 [CLI questions.jsonl](/Users/tong/Documents/ChatGPT/deckprobe/benchmark/suites/deckprobe-cli-contract-v1/questions.jsonl)。

## OOXML：O01–O12

每种格式分成“身份与包、元数据、安全、结构”四题：

- O01–O04 DOCX：34/35 个 catalog target 已形成确定性检查；JavaScript 只检查 `unsupported` 能力边界。
- O05–O08 XLSX：36/38 个 target 已检查；空 keywords 和 JavaScript 不冒充事实正例。
- O09–O12 PPTX：38/40 个 target 已检查；空 keywords 和 JavaScript 不冒充事实正例。

独立 Oracle 会让 DOCX 的完整作者与描述按 XML 原文判定。当前实现很可能暴露两项问题：作者被缩成 `Finance`，描述丢失开头。这是预期的 benchmark 发现，不应修改标准去迁就实现。

完整问题见 [OOXML questions.jsonl](/Users/tong/Documents/ChatGPT/deckprobe/benchmark/suites/deckprobe-ooxml-deep-v1/questions.jsonl)。

## Legacy Office：L01–L10

- L01/L06：DOC 与 PPT 的身份、MIME、大小、CFB 和有效目录项。
- L02/L07：SummaryInformation 元数据。
- L03/L08：宏、嵌入对象和加密能力边界；`unknown` 不等同于 `false`。
- L04：DOC 词数 7128；页数保持 unknown，因为 LibreOffice 渲染 14 页不是源文件保存页数。
- L09：PPT 经 LibreOffice 转为 OOXML 后确认 16 张幻灯片。
- L05/L10：字符/段落、PPT 备注仅观察，不判定。

独立 CFB 解析只发现 5 个有效目录项，而当前实现返回 8。两种格式都会把此差异作为 Finding 暴露，疑似把空目录槽计入。

完整问题见 [Legacy questions.jsonl](/Users/tong/Documents/ChatGPT/deckprobe/benchmark/suites/deckprobe-legacy-deep-v1/questions.jsonl)。

## iWork：I01–I12

每种格式分成“身份、包、可交叉佐证语义、IWA 内部观察”四题：

- 包级门禁来自 ZIP、Properties.plist、BuildVersionHistory.plist、Data 条目和预览图片尺寸。
- Keynote 的 16 页、14 页备注、960×540 pt 由配对 PPTX 交叉佐证。
- Numbers 的 14 张 sheet 和顺序由配对 XLSX 交叉佐证。
- Pages 的 14 个缓存页和 612×792 pt 页面由导出/预览信息交叉佐证。
- archive/message/object、Numbers 深层表格/公式、Pages 正文/章节暂时只观察；没有第二套 IWA 解码器前不生成 Finding。

Properties.plist 明确 `hasExternalReferenceOrMissingData=false`，而当前实现很可能返回 `null`；三个 iWork case 会分别暴露这一语义丢失。

完整问题见 [iWork questions.jsonl](/Users/tong/Documents/ChatGPT/deckprobe/benchmark/suites/deckprobe-iwork-deep-v1/questions.jsonl)。

## 运行时：R01–R03

- R01：Node `probeFile` 与 native CLI 的完整报告深比较。
- R02：Buffer、Uint8Array、ArrayBuffer 三种 Node 输入报告一致。
- R03：真实 Chromium 中的 WASM 主线程与 module Worker 报告一致，并通过 Schema v2。

当前仓库缺 `packages/deckprobe-js/dist/`、WASM 和 `target/release/deckprobe`，因此这三题即使批准也要先构建；`ready=false` 时不得进入正式质量解读，更不能当作产品 Finding。

## 仍需新测试文件才能补的范围

这些能力不能靠现有样本合理推断，本轮没有伪造题目：

- 普通 `.xls`、`.xlsb`；
- `.docm/.xlsm/.pptm` 宏正例；
- Office/PDF 数字签名正例；
- 损坏 ZIP/CFB、扩展名与内容错配；
- 外链 Keynote/Pages、带媒体/构建/转场/隐藏结构的 iWork 正例；
- 旧版 XML iWork、远程/range source；
- 合法 format option 的 last-wins、单 target confidence override、CLI exit 6。

## 审批回复方式

可以直接回复：

> C01–C17、O01–O12、L01–L10、I01–I12、R01–R03 全部批准；Legacy/IWA 观察项继续只记录。

也可以只列例外，例如：

> 除 L01/L06 的 CFB 计数需要再确认外，其余批准；R01–R03 暂不批准。
