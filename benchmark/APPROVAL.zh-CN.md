# DeckProbe v1 验证标准审批单

状态：**已审批**（B1 为非门禁观察项）  
审批范围：4 个 Suite、18 个 Case、18 个问题  
审批原则：这里只审批“问题是否应该这样问、标准答案是否可信、阈值是否符合产品目标”。ID、target 名和检查类型属于机器实现，不需要审批。

## A. 摘要、格式与安全

| # | Case | 需要确认的标准答案 | 证据与可信度 | 自动检查 |
| ---: | --- | --- | --- | --- |
| A1 | 普通 DOCX 年报 | 22 页、5832 词、指定英文标题、未加密 | OOXML `docProps/app.xml` 和 `document.xml`；高 | driver、标题、页数、词数、安全、契约、成本 |
| A2 | 加密 DOCX | 识别为 `encrypted-ooxml`，加密且受密码保护，不探测正文 | CDFV2 Encrypted 签名；高 | driver、三个安全事实、契约、成本 |
| A3 | Keynote QBR | 16 张幻灯片、有预览、未加密 | 包身份/预览来自 iWork ZIP；页数由配对 PPTX 佐证；中 | driver、页数、预览、安全、契约、成本 |
| A4 | PPTX QBR | 16 张幻灯片、指定英文标题、存在嵌入内容、未加密 | `presentation.xml`、core properties、4 个 embeddings；高 | driver、标题、页数、安全、契约、成本 |
| A5 | Legacy DOC 合同 | 指定英文标题、CFB 容器、无宏 | `file(1)` 与 SummaryInformation；高 | driver、标题、容器、安全、契约、成本 |
| A6 | PDF 董事会材料 | PDF 1.4、指定英文标题、存在附件、未加密 | Poppler `pdfinfo` + pypdf 三附件交叉检查；高 | driver、标题、版本、安全、契约、成本 |
| A7 | Legacy PPT 提案 | 指定英文标题、CFB 容器、无宏 | `file(1)` 与 SummaryInformation；高 | driver、标题、容器、安全、契约、成本 |
| A8 | Numbers 财务模型 | 14 张工作表且顺序固定、有预览、未加密 | 包身份/预览来自 iWork ZIP；表名由配对 XLSX 佐证；中 | driver、表数、表名顺序、预览、安全、契约、成本 |
| A9 | XLSX 财务模型 | 14 张工作表且顺序固定、指定英文标题、存在外部关系 | `workbook.xml`、core properties、10 条 External relationship；高 | driver、标题、表数、表名、安全、契约、成本 |
| A10 | Pages 提案 | 正确识别 Pages、有预览、未加密 | ZIP/plist、`Document.iwa` 与 Preview 条目；高 | driver、预览、安全、契约、成本 |
| A11 | 加密 PPTX | 识别为 `encrypted-ooxml`，加密且受密码保护，不探测正文 | CDFV2 Encrypted 签名；高 | driver、三个安全事实、契约、成本 |
| A12 | 加密 XLSX | 识别为 `encrypted-ooxml`，加密且受密码保护，不探测正文 | CDFV2 Encrypted 签名；高 | driver、三个安全事实、契约、成本 |
| A13 | HTML | `UNSUPPORTED_FORMAT`，退出码 3 | 项目公开支持边界；高 | Schema v2 错误契约 |
| A14 | RTF | `UNSUPPORTED_FORMAT`，退出码 3 | 项目公开支持边界；高 | Schema v2 错误契约 |
| A15 | 未知扩展名 | `UNSUPPORTED_FORMAT`，退出码 3 | 项目公开支持边界；高 | Schema v2 错误契约 |

### A 类统一成本阈值

对受支持 case 的 metadata `@summary,@security` 探测：

- 物理读取量 ≤ 1 MiB；
- 累计解压量 ≤ 2 MiB；
- 随机读取次数 ≤ 10,000。

这是针对当前固定 corpus 的产品验收标准，不是从源文档中提取出来的客观事实，需要产品负责人单独确认。

## B. 精确幻灯片计数路径

| # | 需要确认的标准答案 | 证据 | 自动检查 |
| ---: | --- | --- | --- |
| B1 | 不设置通过/失败标准；记录实际 driver、幻灯片数量、置信度、执行路径、进程状态和 I/O 成本 | 源事实可辅助解释观察值；当前不设置产品阈值 | `probe_observation` 保存完整实际值，状态固定为 `review` |

## C. 预算失败语义

| # | 需要确认的标准答案 | 证据 | 自动检查 |
| ---: | --- | --- | --- |
| C1 | 1 KiB 物理读取预算不足时返回 `BUDGET_EXCEEDED`，进程与报告退出码均为 4 | CLI 资源限制与退出码契约 | Schema v2 错误契约 |

## D. 默认输出确定性

| # | 需要确认的标准答案 | 证据 | 自动检查 |
| ---: | --- | --- | --- |
| D1 | 相同输入和参数、不启用 telemetry 时，两次 JSON 输出逐字节一致；两份报告都满足 Schema 与证据规则 | CLI 默认输出确定性契约 | 双报告契约、原始字节比较 |

## 建议优先补充或调整的项目

审批时请重点考虑：

1. A3 Keynote 当前接受“配对 PPTX”作为独立证据；后续是否增加 Keynote 原生独立 Oracle 或人工标注。
2. A8 Numbers 当前接受“配对 XLSX”作为独立证据；后续是否增加 Numbers 原生独立 Oracle。
3. A 类已批准 1 MiB/2 MiB 的 summary/security corpus 阈值；后续扩大 corpus 时需要重新校准或创建新版本。
4. B1 已确定只记录观察数据，不作为稳定产品承诺，也不参与通过/失败判定。
5. 后续是否补充 `.xls`、宏、签名、损坏 PDF、后缀/容器不匹配、JSONL 和 WASM 等缺口。

## 审批方式

可以直接回复：

- “A1–A15、B1、C1、D1 全部批准”；或
- “A3 改为人工 review，A 类成本改为……，另外补充……”；或
- 按编号逐项给出修改意见。

A1–A15、C1、D1 已批准为质量门禁；B1 已批准为非门禁观察项。
