# PDF 全量探测新增标准审批单

状态：**已审批**  
Suite：`deckprobe-pdf-deep-v1`  
Case：固定 SHA-256 的 Meridian Board Pack PDF  
Target：`deckprobe -l deep -t @all`

## 新增题目

| 编号 | 考察点 | 标准答案摘要 | 独立证据 | 不确定性 |
| --- | --- | --- | --- | --- |
| P1 | Header 与身份 | PDF 1.4、未 linearized、86307 bytes、扩展名/MIME/driver 正确 | 原始 Header、pdfinfo、文件哈希 | 低 |
| P2 | Info 元数据 | 标题、主题、作者、关键词、时间、Creator 与 Oracle 逐字一致，Unicode 不损坏 | Poppler + pypdf | 低；已知当前标题会失败 |
| P3 | 页面、对象、xref | 21 页、146 个对象、classic xref table | pdfinfo + pypdf xref + 原始字节 | 低 |
| P4 | 批注与链接动作 | 44 个批注、18 个内部链接、无外部 URI/GoToR/Launch；缺少 `pdf.link_count` 必须失败 | pypdf 遍历 `/Annots` | 已批准为产品实现缺失 |
| P5 | AcroForm | 按 DeckProbe 当前定义统计 20 个可交互 Widget | pypdf `/Annots` 和字段树 | 已批准；11 个逻辑字段仅作解释性事实 |
| P6 | 附件与 XMP | 3 个附件、嵌入文件为 true、XMP 为 true | pypdf attachments、Names、XMP | 低 |
| P7 | 签名 | 空白签名控件不计作已签名结构；false / 0 | AcroForm 与签名字典检查 | 中；需确认签名 target 语义 |
| P8 | 加密、JavaScript 与风险 | 未加密、无密码、无 JS、无宏；附件使风险为 low | pdfinfo、pypdf 与待审批风险规则 | low 分级需业务确认 |
| P9 | 修复 | xref 完整，不应使用安全修复 | strict 解析 + startxref/xref | 低 |

## 这一个 PDF 能覆盖什么

正向覆盖：

- Info 元数据；
- page/object/xref；
- annotations；
- AcroForm；
- attachments；
- embedded files；
- XMP；
- 内部链接存在这一源事实。

负向覆盖：

- 未加密；
- 未签名；
- 无 JavaScript；
- 无外部动作；
- 未 linearized；
- 未 repaired。

## 仍需新增的 corpus

仅靠当前 PDF 不能证明以下“检测为 true”的能力：

1. 带真实签名字典的 PDF；
2. 带 JavaScript 的 PDF；
3. 带外部 URI、GoToR 或 Launch 动作的 PDF；
4. 加密或密码保护 PDF；
5. linearized PDF；
6. xref stream 和 hybrid xref PDF；
7. xref 损坏但能由 safe repair 恢复的 PDF；
8. 损坏且必须拒绝的 PDF；
9. 没有附件、表单、批注、XMP 的最小负例；
10. 如果“链接”是产品正式承诺，还需要新增 `pdf.link_count` 或等价 target；当前只有外部动作布尔值和总批注数。

## 审批方式

P1–P9 已全部批准；P5 采用 DeckProbe 当前的 20 Widget 定义；P4 缺少 `pdf.link_count` 作为正式失败项。
