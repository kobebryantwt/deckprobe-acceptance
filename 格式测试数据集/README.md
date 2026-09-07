# DeckProbe 格式测试数据集

本目录用于验证 DeckProbe v2.5.0 对已声明格式以及明确未支持格式的实际行为。样本优先来自公开 benchmark 或成熟文档解析项目的回归语料，而不是本地生成的空壳文件。

## 数据概况

| 目录 | 文件数 | 扩展名数 | 用途 |
|---|---:|---:|---|
| `01_明确支持` | 61 | 26 | 33 个格式/安全边界样本 + 6 个稀有字段最小正例 + 16 个 Hugging Face 真实业务样本 + 6 个公开 iWork 业务样本 |
| `02_暂未支持` | 13 | 13 | 覆盖旧版 iWork、OpenDocument、RTF、CSV、HTML、EPUB、Visio、OneNote 和 PowerPoint 主题 |

已支持组的 26 种扩展名：

```text
pdf
docx docm dotx dotm
xlsx xlsm xltx xltm xlsb
pptx pptm ppsx ppsm potx potm
doc dot xls xlt ppt pps pot
key numbers pages
```

## 目录结构

```text
格式测试数据集/
├── 01_明确支持/
│   ├── 01_PDF文档/
│   ├── 02_Word现代文档/
│   ├── 03_Excel现代工作簿/
│   ├── 04_PowerPoint现代演示文稿/
│   ├── 05_Word旧版文档/
│   ├── 06_Excel旧版工作簿/
│   ├── 07_PowerPoint旧版演示文稿/
│   ├── 08_Apple_Keynote/
│   ├── 09_Apple_Numbers/
│   └── 10_Apple_Pages/
├── 02_暂未支持/
├── 来源清单.tsv
├── 字段能力说明.md
├── 深字段覆盖矩阵.md
├── HuggingFace来源与筛选报告.md
├── SHA256SUMS
├── DeckProbe验证结果.jsonl
├── DeckProbe深度探测完整结果.jsonl
├── DeckProbe深度探测完整结果.json
├── DeckProbe深度探测汇总.json
├── DeckProbe字段目录.json
├── benchmark-gt.schema.json
├── benchmark-gt.使用说明.md
└── 下载数据.sh
```

## 来源

### Hugging Face 真实业务样本

- `OmegaUse-OfficeVal`：保留 7 个 DOCX/XLSX/PPTX/PDF，来源 revision 固定为 `8e19c575b5be64c8a2964a4e28aafb696490c2ae`，Apache-2.0。
- `Forceless/Zenodo10K`：保留 6 个 PPTX，只使用 `pptx/cc-by-4.0/` 下的文件，来源 revision 为 `e59bf3ec11f7518a6c84dc145d83c0675d412522`。
- `KAKA22/SpreadsheetBench`：从 verified-400 固定归档中保留 2 个 XLSX，来源 revision 为 `ab0b742b0fc95b946f212d80ac7771b5531272e4`，CC-BY-SA-4.0。
- `microsoft/OfficeComprehensionBenchmark`：保留 1 个同时具有图表、透视表、大量公式、批注和图片的 XLSX，来源 revision 为 `0104ac2f88348ecf1148781b85fdb6a189b59671`，CDLA-Permissive-2.0。
- 筛选结果、未采用数据集和 16 个文件的 deep 结果见 [HuggingFace来源与筛选报告.md](./HuggingFace来源与筛选报告.md)。

### OmniDocBench

- 用于 `OmniDocBench_PPT复杂页面.pdf`。
- 原始内容是 OmniDocBench 中的真实复杂 PPT 页面图像。
- PDF 使用 OmniDocBench 官方 `tools/image_to_pdf.py` 转换，不是自行制作的简单测试页。
- 数据版本固定为 `aa1ee96d106dbe53d0ae59474d75c6e6d9b53fec`。
- OmniDocBench 说明其 PDF 来自公开网络与用户贡献，仅供科研使用，不作商业用途。

### Apache Tika

- 主要来源：Office、PDF、现代/旧版 iWork 及未支持格式的解析器回归样本。
- 版本固定为 `acab4a86262b6c5586ffe771fc607e50f77f0fbe`。
- 项目许可证：Apache License 2.0。

### Apache POI

- 仅保留用于补充 OOXML 数字签名和 `.potx` 模板的样本；图表、透视表、公式等普通业务特征已由真实业务文件替代。
- 版本固定为 `3e24e7d6f4151b993232ee67faae650ade533712`。
- 项目许可证：Apache License 2.0。

### delivr.to file-samples

- 用于补充 `.dot/.pps/.pot` 以及真实密码保护 PDF/OOXML 样本。
- 版本固定为 `bbe8f8001b09733b436f133cfe7ad130849056c5`。
- 项目声明样本为良性安全测试文件。
- 许可证：CC BY-NC 4.0，禁止商业使用。

### Cupertino Files

- 用于补充当代 Keynote/Numbers/Pages 真实 IWA 样本：Keynote Build effects、表格和图片，Numbers 公式、过滤规则和多 sheet 结构，Pages 多章节页眉页脚。
- 其 `fixtures/ATTRIBUTION.md` 对每个样本的来源、作者、许可和已解码特征逐一记录。
- 版本固定为 `bb6c7e39245ac45a36b12362fbd35680e9be722d`。
- 项目许可证：MIT；个别上游 fixture 的再分发许可以其 attribution 为准。

每个文件的来源项目、固定提交、原始路径和处理方式详见 `来源清单.tsv`。

## 复现下载

```bash
bash 格式测试数据集/下载数据.sh
```

脚本不会覆盖已存在的非空文件。OmniDocBench PDF 转换依赖 PyMuPDF（`fitz`）和官方脚本所引用的 `tqdm`。

## 完整性验证

- 共 74 个样本：61 个已声明支持格式的样本，13 个未支持格式样本。
- `字段代表样本` 仅剩 6 个：PDF 表单/注释、PDF 附件/JavaScript，以及 Word/Excel/PowerPoint 数字签名等公开业务语料难稳定替代的稀有正例。
- 16 个 `业务代表样本_HuggingFace` 和 6 个 `业务代表样本_公开来源` 承担常规内容与复杂结构覆盖；重复、低复杂度 fixture 已删除。
- 所有 ZIP/OPC/IWA/ODF/EPUB/VSDX 容器均通过 `unzip -t` 完整性检查。
- 现代 iWork 三个样本均包含 `Index/Document.iwa`。
- 旧版 iWork 三个样本分别包含 `index.apxl` 或 `index.xml`，不是仅通过改扩展名伪造。
- `.doc/.dot/.xls/.xlt/.ppt/.pps/.pot` 样本均为 CFB/OLE 容器。
- `SHA256SUMS` 记录全部 74 个样本的 SHA-256。

## DeckProbe v2.5.0 实测结果

验证命令的核心参数：

```bash
deckprobe --jsonl \
  --probe-level deep \
  --targets @all \
  --minimum-confidence low
```

| 样本组 | 结果 | 数量 | 说明 |
|---|---|---:|---|
| 已声明支持 | `ok` | 9 | 所有请求 target 均已解析，主要为现代 iWork |
| 已声明支持 | `partial` | 43 | 文件可正常路由和解析；`@all` 中一些可选元数据或安全事实未记录 |
| 已声明支持 | `MALFORMED_INPUT` | 9 | 见下方的真实兼容性问题 |
| 暂未支持 | `UNSUPPORTED_FORMAT` | 13 | 与当前分派白名单一致 |

`partial` 不表示文件损坏，只表示某些请求目标没有值或未达到请求置信度。

### 数据集暴露的 9 个兼容性问题

| 文件 | DeckProbe 结果 |
|---|---|
| `Word宏文档.docm` | 主 Content-Type 与 `.docm` Profile 校验不匹配 |
| `Word宏模板.dotm` | 主 Content-Type 与 `.dotm` Profile 校验不匹配 |
| `Excel二进制综合工作簿.xlsb` | 主 Content-Type 与 `.xlsb` Profile 校验不匹配 |
| `Excel宏工作簿.xlsm` | 主 Content-Type 与 `.xlsm` Profile 校验不匹配 |
| `Excel宏模板.xltm` | 主 Content-Type 与 `.xltm` Profile 校验不匹配 |
| `PowerPoint宏演示文稿.pptm` | 主 Content-Type 与 `.pptm` Profile 校验不匹配 |
| `PowerPoint宏放映文件.ppsm` | 主 Content-Type 与 `.ppsm` Profile 校验不匹配 |
| `PowerPoint宏模板.potm` | 主 Content-Type 与 `.potm` Profile 校验不匹配 |
| `Excel旧版嵌入对象工作簿.xls` | 包内嵌入 Word 对象导致 CFB 主流类型被误判为 Word |

这些文件均保留在语料中，因为它们正是公开解析器回归语料的价值所在；不应为了让当前产品通过而换成不真实的简单文件。同目录中已额外提供普通 `.xls` 基线样本。

完整机器可读报告位于 `DeckProbe验证结果.jsonl`。

## Full evidence 与 GT 记录

`DeckProbe验证结果.jsonl` 是便于查看的 `values` 视图；用于交叉验证和 GT 准备时，应使用 `DeckProbe深度探测完整结果.json` 或其流式等价版本 `DeckProbe深度探测完整结果.jsonl`。二者对全部 74 个样本执行 `deep + @all + low confidence + full view`，并在每条原生报告外补充文件 SHA-256、来源、实际进程退出码和完整调用参数。

- `DeckProbe字段目录.json`：从当前二进制实时发现的 124 个唯一 target，包含 profile 适用性、最小探测层级、值类型和字段级 JSON Schema。
- `benchmark-gt.schema.json`：统一验证 `deckprobe_native`、规范化后的 `cross_validation` 和 `ground_truth` 三种记录；第三方原始 JSON 不必符合该 Schema，也不必模拟 DeckProbe，适配器只需把独立事实转换到 `fact_id/definition/value/evidence`，产品字段另放在 `target_mapping`。
- `benchmark-cross-validation.example.json` 与 `benchmark-ground-truth.example.json`：可直接复制修改的示例；GT 示例故意保持 `draft`，不会自动把被测工具结果提升为真值。
- 详细约定见 [benchmark-gt.使用说明.md](./benchmark-gt.使用说明.md)。

## 字段能力结论

- [字段能力说明.md](./字段能力说明.md)：按通用、安全、PDF、Word、Excel、PowerPoint、iWork、Keynote、Numbers、Pages和旧版 Office 详细列出字段、类型、层级和含义。
- [深字段覆盖矩阵.md](./深字段覆盖矩阵.md)：把字段与真实样本、实测值、盲区和漏报一一对齐。

尤其需要注意：数据集已经包含动画、切换、公式、合并单元格、页眉页脚等真实文件，但这不代表 DeckProbe 能返回这些内容。文档中已将“文件格式可读”和“特征字段可返回”分开标记。

## 安全提示

语料包含宏、嵌入对象、外部关系、加密文档和附件。来源项目将其声明为良性测试文件，但仍应将其当作不可信文件处理：

- 不要在已启用宏的 Office 环境中手工打开。
- 不要点击文档内链接或启动嵌入对象。
- 优先在断网、沙箱或只读环境中运行探测。
