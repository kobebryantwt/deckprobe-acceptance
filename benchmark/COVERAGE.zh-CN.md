# DeckProbe 验证覆盖审计

本文件区分三类业务覆盖和四层执行状态，避免把“写了题”或“某个文档能返回 JSON”误认为产品已经验证：

1. **格式事实覆盖**：某个 profile 的具体 canonical target 是否被固定 case 和独立 Oracle 断言。
2. **特征方向覆盖**：布尔/风险能力是否同时有正例和负例。
3. **接口合同覆盖**：CLI、JSONL、stdin、discovery、WASM 等调用方式是否按公开契约工作。

## 格式 target 覆盖

统计口径：读取 `deckprobe targets --format <profile>` 的 live catalog，并分别统计：Suite 中已有确定性断言（设计）、Suite 与问题已批准（批准）、当前源 SHA 对应的最新运行包含该断言（运行）、该断言在最新运行通过（通过）。公共 target 在 PDF 通过，不会自动算成 DOCX 或 Keynote 已覆盖。完整机器结果见 `COVERAGE.generated.json`。

| Profile | Live | 设计 | 批准 | 运行 | 通过 | 主要缺口 |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| PDF | 34 | 94.1% | 94.1% | 94.1% | 94.1% | `document.application/description`；`pdf.link_count` 仍是缺失产品 target |
| DOCX | 35 | 100% | 100% | 100% | 94.3% | author/description 截断 |
| XLSX | 38 | 97.4% | 97.4% | 97.4% | 97.4% | `document.keywords` 尚未设计 |
| PPTX | 40 | 97.5% | 97.5% | 97.5% | 97.5% | `document.keywords` 尚未设计 |
| Legacy DOC | 27 | 88.9% | 88.9% | 88.9% | 85.2% | 时间、段落独立 Oracle；CFB 项计数差异 |
| Legacy PPT | 25 | 88.0% | 88.0% | 88.0% | 84.0% | 时间、备注独立 Oracle；CFB 项计数差异 |
| Keynote | 42 | 69.0% | 69.0% | 69.0% | 66.7% | IWA 深层语义；external/missing-data 为 null |
| Numbers | 40 | 65.0% | 65.0% | 65.0% | 62.5% | IWA 表格/公式；external/missing-data 为 null |
| Pages | 42 | 64.3% | 64.3% | 64.3% | 61.9% | IWA 正文/章节；external/missing-data 为 null |

当前 corpus 没有普通 `.xls` case，因此 Legacy Excel 还没有可计算的业务覆盖。

## 2026-08-14 新增边界语料

`/Users/tong/Downloads/benchmark素材文件` 当前保留 20 个非冗余文件，均已纳入并运行 `deckprobe-edge-corpus-v1`，新增了此前缺少的：

- PDF 签名正例、xref stream、修复路径、链接密集、大型与伪装 HTML；
- OOXML 扩展名/内部类型错配、密码 PPTX、0 页 PPTX、WebP/SVG、动画 timing、嵌入对象；
- XLSX 定义名称、中文 sheet、图片与外部关系；
- DOCX 合法零词数、批注/图片/外链，及中文 Legacy DOC；
- 较旧 Keynote/Numbers 包，Keynote 转场与备注由 Apple Keynote 应用独立交叉确认。

E01–E20 的问题和答案及评分政策均已批准；`core21-policy-v1-20260814-r2` 是完成率 100% 的 Core 2.1 正式运行。结果为 FAIL：一个 Legacy title 状态 Gate 失败，质量分 90.79；大 PDF 返回产品内部预算错误，不再是基准超时阻塞。

## 各格式下一步 Suite

| Suite | 重点能力 | 当前 Oracle 可行性 |
| --- | --- | --- |
| Word deep | core/app properties、页/词/字符/段落/表格、评论、图片、安全关系 | OOXML ZIP/XML 可独立验证大部分 |
| Excel deep | sheet/name/visibility、shared strings、table/chart/pivot、图片、外部关系、安全 | OOXML ZIP/XML 可独立验证大部分 |
| PowerPoint deep | slide/hidden/master/layout/notes/size、chart/comment/image/media、安全 | OOXML ZIP/XML 可独立验证大部分 |
| Legacy Office deep | CFB 身份、SummaryInformation、核心统计、宏与嵌入对象 | `file(1)`、LibreOffice、独立 CFB 库；需要更多正例 |
| iWork deep | IWA 数量、预览、资产、Keynote/Numbers/Pages 语义结构 | ZIP/plist 可验证包级事实；深层 Protobuf 需要第二实现或人工标注 |

每个安全能力需要正例和负例。例如“当前 DOCX 没有宏”只能验证不误报，不能证明 `.docm` 宏检测有效。

## CLI 合同覆盖

当前 benchmark 已覆盖：

- 本地文件输入；
- `@summary,@security` 与 `@all` 的部分使用；
- `--minimum-confidence exact` 的一次调用；
- 物理读取预算错误；
- 默认输出确定性；
- `UNSUPPORTED_FORMAT` 错误。

`deckprobe-cli-contract-v1` 的 17 个问题和答案及评分政策已批准；`core21-policy-v1-20260814` 正式运行结果为 16 通过、1 失败。失败项是 `schema` discovery 输出的根对象类型未满足合同。CLI 检查全部归为 Gate。

- raw stdin、JSONL 错误后继续、values、plan-only、strict/exit 5；
- optional/piggyback、`--no-piggyback`、level 别名；
- input-format 不匹配、未知 format option；
- formats/targets/schema、pretty、telemetry、completion、generate man。

以下 CLI 能力仍未独立覆盖：

| CLI 能力 | 为什么不能由现有 case 结果推断 |
| --- | --- |
| 重复 `-t` 与逗号 selector 的等价性 | 当前只覆盖 level 别名，未单独比较所有 selector 写法 |
| 全局/单 target confidence override | 需要选择能稳定改变路径或 unresolved 结果的样本 |
| format-option 合法值和 last-wins | 当前只覆盖未知 key 的拒绝路径 |
| raw stdin 超预算 | 需要验证 CLI 边界在完整缓冲前拒绝 |
| JSONL path/name override/base64 alias | 当前覆盖 data_base64 与坏记录继续，尚未覆盖全部 record 形态 |
| CLI syntax/source I/O/internal exit codes | 退出码 1–6 需要各自的代表场景 |
| Bash/Fish/PowerShell 等其他 completion | 当前只固定 zsh 代表样本 |

`deckprobe-runtime-parity-v1` 仍保留 Node file、Node 三种 byte shape、Browser main-thread/Worker 三个 draft case。仓库当前缺 `dist/`、WASM 和 release binary；按本轮范围不运行，也不把缺少构建产物解释为产品缺陷。

结论：文档 case 主要验证“引擎对文档事实的最终判断”；CLI Suite 必须另外验证“用户如何请求这些事实以及错误如何表现”。二者不能互相替代。

## 建议的版本拆分

1. 处理正式基线暴露的 CLI Schema、PDF Unicode/链接、OOXML 字段截断、Legacy CFB 计数和 iWork external/missing-data Findings。
2. 修复后使用相同 Evaluator、政策 SHA 和源 cohort 重跑，才可把差异归因于产品改进。
3. 保留 `.xls`、宏、加密/JavaScript PDF、签名/损坏 OOXML 等素材缺口，不在缺少可信 fixture 时编造门禁答案。
4. 获得第二 IWA 解码实现或人工标注后，把当前 IWA 观察项升级为门禁。
5. 本地具备 JS/WASM/release 构建产物后，再审批并运行 `deckprobe-runtime-parity-v1`。
