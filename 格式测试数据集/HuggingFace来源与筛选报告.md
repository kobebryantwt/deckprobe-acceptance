# Hugging Face 来源、替代与精简报告

本报告记录从“parser fixture 为主”转向“真实业务文件为主”的筛选结果。数据集 README 只用于发现候选项；最终判断依据是原始二进制文件、固定 revision、许可信息、DeckProbe `deep + @all` 实测及 OOXML/PDF 内部结构交叉检查。

## 最终结论

- 原 `字段代表样本` 从 **29 个精简到 6 个**。
- 只保留 Hugging Face 真实业务文件仍无法稳定替代的稀有正例：PDF 表单/JavaScript、Word 批注/数字签名、Excel 数字签名、PowerPoint 数字签名。
- 6 个质量较好的原生 iWork 文件不再归为字段 fixture，已移入 `业务代表样本_公开来源`。
- 新增 5 个高信息密度 Hugging Face 文件，同时删减 26 个重复或低质量样本。
- 最终语料从 95 个降为 **74 个**：61 个当前声明支持格式 + 13 个明确未支持格式。

## 本轮额外搜索与实文件扫描

| 来源 | 实际扫描 | 结果 |
|---|---:|---|
| [Forceless/Zenodo10K](https://huggingface.co/datasets/Forceless/Zenodo10K) | 检索 10,448 个 PPTX 的文件名和元数据；额外下载并解包扫描 66 个 CC-BY-4.0 PPTX | 找到真实音频、隐藏页、批注、OMML 公式、切换和动画时序文件 |
| [Microsoft OfficeComprehensionBenchmark](https://huggingface.co/datasets/microsoft/OfficeComprehensionBenchmark) | 扫描仓库托管的 50 XLSX + 1 XLSM | 找到同时含 2 图表、3 透视表、12,844 公式、1 批注和 1 图片的真实工作簿 |
| [OmegaUse-OfficeVal](https://huggingface.co/datasets/baidu-frontier-research/OmegaUse-OfficeVal) | 扫描 63 DOCX、25 XLSX、31 PPTX、14 PDF | 找到长文档、大量表格、多 sheet、视频、嵌入对象与真实业务版式；未发现 Office 数字签名和 Word/PPT 批注正例 |
| [SpreadsheetBench](https://huggingface.co/datasets/KAKA22/SpreadsheetBench) | 扫描 verified-400 归档中 400 个 init XLSX | 保留公式/合并单元格压测与隐藏 sheet 工作簿 |
| DOCX 其他候选 | 审查 `superdoc-dev/docx-corpus`、`document-change-assurance-benchmark`、`DOCXGeneration` | SuperDoc 主要是外部 URL 元数据，单文件再分发权需复核；其他集是合成/专项 fixture 或不含 DOCX 二进制，质量不足以替换保留的 2 个稀有正例 |
| 原生 iWork | 搜索 Keynote/Numbers/Pages/iWork 数据集与仓库文件 | 仍未找到许可、来源和原始二进制都足够清晰的 Hugging Face 替代集 |

## 新增的 5 个替代文件

| 本地文件 | 实文件结构 | 替代的旧样本 |
|---|---|---|
| `Excel_OCB_NBA全赛季_2图表3透视表12844公式.xlsx` | 4 sheets、2 charts、3 pivots、12,844 formulas、299,161 cells、1 comment、1 image、header/footer | Excel 图表、透视表、图片、公式、页眉页脚 fixture |
| `PPT_Zenodo_可穿戴PPG路线图_24音频48切换.pptx` | 24 slides、24 M4A audio、48 transitions、24 timing trees、24 notes | 音视频、切换、动画 3 个 fixture；视频由 OfficeVal 工程 PPT 覆盖 |
| `PPT_Zenodo_哥斯达黎加交通模型_2隐藏页.pptx` | 8 slides、2 hidden slides、13 images、1 table、DOI `10.5281/zenodo.7225825` | 替代 2 页的合成隐藏幻灯片 fixture；同时更清楚地暴露 DeckProbe 2.5.0 隐藏数返回 0 的真实漏报 |
| `PPT_Zenodo_统计学课程_64公式24切换.pptx` | 16 slides、64 OMML equations、24 transitions、15 notes、25 images、DOI `10.5281/zenodo.7816368` | 1 页 OMML fixture |
| `PPT_Zenodo_设计技术教育_批注与备注.pptx` | 14 slides、1 comment part、5 notes、DOI `10.5281/zenodo.4017917` | 1 页批注 fixture |

## 最终保留的 16 个 Hugging Face 业务样本

| 格式 | 保留数 | 核心覆盖 |
|---|---:|---|
| PDF | 2 | 96 页长试题；15 页 + 72 注释论文 |
| DOCX | 3 | 66 页/308 表/115 图目录；55 页运营规划；22 页多 section 评审表 |
| XLSX | 4 | 61 sheet/178 table；13 sheet/4,664 公式/605 合并单元格；8 sheet/6 hidden；NBA 图表+透视表+公式 |
| PPTX | 7 | 视频与 9 表格；49 页/80 图；6 图表/5 嵌入；24 音频；真实隐藏页；64 公式；批注 |

## 仍保留的 6 个字段最小正例

| 样本 | 不能删除的原因 |
|---|---|
| `PDF表单与注释样本.pdf` | 语料中唯一稳定的 PDF AcroForm 正例：5 fields、6 annotations、external relationship |
| `PDF附件外链与JavaScript样本.pdf` | 唯一同时触发 2 attachments、JavaScript、external relationship 和 high risk 的 PDF |
| `Word图文表格批注文档.docx` | Hugging Face 可再分发 DOCX 候选中未找到稳定 Word comment 正例 |
| `Word超链接与数字签名文档.docx` | 唯一 Word package signature 正例 |
| `Excel数字签名工作簿.xlsx` | 唯一 Excel package signature 正例 |
| `PowerPoint数字签名演示文稿.pptx` | 唯一 PowerPoint package signature 正例 |

这 6 个文件不承担“真实业务质量”评估，只作为可机械判定的安全/稀有字段正例。后续准备 GT 时，它们只需各自维护一个布尔值或小整数期望，不需做内容级人工标注。

## 未采用数据集

| 数据集 | 原因 |
|---|---|
| [noxneural/pptx_collection_templates](https://huggingface.co/datasets/noxneural/pptx_collection_templates) | 虽有 1,041 个 PPTX，但数据集卡未明确标注 license，且缺少逐文件授权元数据 |
| [superdoc-dev/docx-corpus](https://huggingface.co/datasets/superdoc-dev/docx-corpus) | 736,706 条记录是很好的发现索引，但主要保存外部 DOCX URL；元数据许可不能自动覆盖每个原文件的再分发权 |
| `SybilGambleyyu/*-change-assurance-benchmark` | 适合 OOXML 安全变更定位，但本质仍是专项 fixture，不解决“业务样本质量”问题 |
| `DOCXGeneration/docx_generation_v0.0.2` | 存储截图、query 和标注，没有可用的 DOCX 二进制 |

## 固定版本

| 来源 | revision | 许可/条件 |
|---|---|---|
| `baidu-frontier-research/OmegaUse-OfficeVal` | `8e19c575b5be64c8a2964a4e28aafb696490c2ae` | Apache-2.0 |
| `Forceless/Zenodo10K` | `e59bf3ec11f7518a6c84dc145d83c0675d412522` | 本语料只取 `pptx/cc-by-4.0/` |
| `KAKA22/SpreadsheetBench` | `ab0b742b0fc95b946f212d80ac7771b5531272e4` | CC-BY-SA-4.0 |
| `microsoft/OfficeComprehensionBenchmark` | `0104ac2f88348ecf1148781b85fdb6a189b59671` | CDLA-Permissive-2.0 |

每个保留文件的原始路径和处理方式见 `来源清单.tsv`；`bash 下载数据.sh` 可按固定 revision 重建语料。
