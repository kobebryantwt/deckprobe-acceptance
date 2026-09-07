# 新增边界语料审批单

来源目录：`/Users/tong/Downloads/benchmark素材文件`

扫描到 30 个文件、无重复哈希。本轮选出 20 个能增加新能力维度的 case；其余 10 个普通变体保留在 corpus 中，不重复生成同类题目。

新增 Suite：`deckprobe-edge-corpus-v1`。E01–E20 的问题与答案已经批准并有历史运行；Suite 当前因 Core 2 角色与评分政策迁移回到 `draft`，需要批准 `QUALITY-POLICY.zh-CN.md` 后再建立新基线。

| ID | 文件特点 | 判定重点 | 类型 |
| --- | --- | --- | --- |
| E01 | `.pdf` 实为 HTML | MALFORMED_INPUT/4 | 门禁 |
| E02 | `.docx` 实为 64 页 PPTX | 类型错配 MALFORMED_INPUT/4 | 门禁 |
| E03 | CSV | UNSUPPORTED_FORMAT/3 | 门禁 |
| E04 | 密码 1234 的 PPTX | encrypted-ooxml、密码保护、禁止正文探测 | 门禁 |
| E05 | 2 页已签名 PDF | 签名、Widget、表单字段正例 | 门禁 |
| E06 | 34 个链接的中文 PDF | 标题、内部/外部链接、`pdf.link_count=34` | 门禁 |
| E07 | xref stream PDF | xref_type=stream | 门禁 |
| E08 | 29.6 MB / 142 页 PDF | 大文件页数、对象数、XMP | 门禁 |
| E09 | 需要容错修复的 PDF | repaired=true 后仍应为 4 页 | 门禁 |
| E10 | 合法 0 页 PPTX | 零值不能变未知/错误 | 门禁 |
| E11 | PNG/JPEG/SVG/WebP PPTX | 唯一图片应为 31 | 门禁 |
| E12 | 含 embeddings 的 PPTX | 嵌入文件正例 | 门禁 |
| E13 | 含 p:timing 动画的 PPTX | 当前无动画 canonical target | 观察 |
| E14 | 中文 sheet + 12 图片 XLSX | sheet、图片、外部关系 | 门禁 |
| E15 | 定义名称 XLSX | defined_name_count=1 | 门禁 |
| E16 | 14 页、0 词、19 图 DOCX | 合法零词数与图片资产 | 门禁 |
| E17 | 批注/表格/图片/mailto DOCX | comments、结构和外链 | 门禁 |
| E18 | 中文 Legacy DOC | CFB=6、空标题、保存页数及抽取统计 | 门禁 + 段落观察 |
| E19 | 较旧 Keynote + 4 页转场 | Apple Keynote 独立确认页面/备注/转场 | 门禁 |
| E20 | 较旧 Numbers | ZIP/plist/preview 门禁，sheet/公式仅观察 | 混合 |

完整问题、答案和断言见 [questions.jsonl](/Users/tong/Documents/ChatGPT/deckprobe/benchmark/suites/deckprobe-edge-corpus-v1/questions.jsonl)，独立事实见 [source-facts-edge-20260814.json](/Users/tong/Documents/ChatGPT/deckprobe/benchmark/oracles/source-facts-edge-20260814.json)。

## Dry run 发现的高概率问题

以下仅来自诊断调用，不是正式 benchmark 结论；批准后才生成正式 Finding：

1. E06：仍没有 `pdf.link_count`，34 个链接预计返回 `null`。
2. E09：Poppler 返回 4 页，当前修复路径返回 0 页。
3. E11：源包有 31 个图片资产，当前返回 29，恰好漏掉 2 个 WebP。
4. E18：独立 CFB 有效项为 6，当前返回 8；空 SummaryInformation 标题被错误替换为乱码字符串。

E13 和 E20 中标注的观察项不会生成 Finding。

## 未单独出题的 10 个文件

以下文件仍保留为后续扩容候选，但其当前特点已被更强的选中 case 覆盖：

- XLSX：十五至尊图、软考高级课表；
- PDF：20180301 华创证券、DocLayNet、论文必胜、邢不行新手代码运行流程；
- PPTX：电商运营排期规划数据图表PPT；
- DOCX：量化交易策略合集、带图片的 docx、高管时间分析测试报告。

## 审批回复方式

如无修改，可以回复：

> E01–E20 全部批准；E13、E18 段落项和 E20 的 sheet/公式继续只观察。

如需调整，只需列出例外编号和修改意见。
