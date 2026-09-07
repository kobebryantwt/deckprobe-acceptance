# DeckProbe 发布验收工具

验收 GitHub/npm **已经发布的资产**，不使用工作区开发二进制。复用 Benchmark Core 2.1 的双报告、证据和 finding 契约；保留原有 suites/evaluators。原手册见 [handbook.md](docs/handbook.md)。

## GitHub hosted 执行

覆盖范围、GT 建模结论和独立审计修复记录见
[`docs/coverage-audit.zh-CN.md`](docs/coverage-audit.zh-CN.md)。

正式迁移入口是 `.github/workflows/release-acceptance.yml`。它只下载已经发布的 DeckProbe
资产，主任务运行 R01/R03/R04/R05/R07/R09 与 Linux x64 GNU R08，独立任务运行 Ubuntu
x64 R02、R06 配对趋势和其余六个平台的 R08，最后合并为一份报告并发布历史站点。

GitHub 只读取经过人工批准和脱敏的 `ci-input/current/`。本地 Casework 仍是维护源；路径变化
不改变 case 或答案身份。导出与校验命令：

```bash
python benchmark/scripts/release_acceptance.py snapshot export --output ci-input/current
python benchmark/scripts/release_acceptance.py snapshot validate --snapshot ci-input/current
```

未审核答案可以用 `--allow-draft` 导出到临时目录查看，但草案不会包含 `READY`，不能启动正式
GitHub 验收。当前部署步骤和剩余事项见仓库根目录的 `ACCEPTANCE-GITHUB-TODO.zh-CN.md`。

## 使用

从仓库根目录执行；入口也支持任意工作目录下的绝对路径调用。需要 Python 3.9+、Node 20+、npm；Python 库版本见 `requirements.txt`。`gh` 用于验签。npm 包、Chromium 和实际发布二进制在准备阶段取得。

```sh
python3 benchmark/scripts/release_acceptance.py prepare --online
python3 benchmark/scripts/release_acceptance.py doctor
python3 benchmark/scripts/release_acceptance.py run --diagnostic --performance
python3 benchmark/scripts/release_acceptance.py run --target previous --diagnostic --performance
python3 benchmark/scripts/release_acceptance.py performance-pair
python3 benchmark/scripts/release_acceptance.py check
python3 benchmark/scripts/release_acceptance.py weekly
```

`--home /absolute/path` 放在子命令之前可指定独立状态目录。默认 `benchmark/artifacts/acceptance/`，不进 Git。准备阶段可能访问网络；`run` 不安装、不更新、不下载依赖。Browser 测试只允许测试静态资源的回环 HTTP 请求，这不是操作系统断网证明。

- `check`：比较发布、资产、规则、样本哈希、审批及环境；检查本身不标记已处理。
- `prepare --online`：锁定最新/前一正式版、下载全部平台档案、验证 checksum、取得公开 attestation bundle 并验签、安装冻结的 npm 依赖、准备 Chromium、语料和待审 GT、捕获 target catalog。
- `prepare`：仅准备本地/生成语料，保留现有发布锁。不会联网补样本。
- `doctor`：报告工具、身份、权限和隔离缺口。保存的 doctor 不会被当成某次运行的安全证据。
- `run`：只判定已批准答案；未批准答案保留 REVIEW。低层契约检查按用户批准的方案执行。
- `run --diagnostic`：可以采集公开/生成样例的未审答案实际值，但仍为 REVIEW，不能签核。私有样本仍禁止扫描。
- `compare --before RUN_DIR --after RUN_DIR --output NEW_DIR`：校验证据后比较；条件不一致时不归因产品回归。
- `report --run RUN_DIR --output NEW_DIR`：不运行产品、离线重建报告；先检验证据完整性，保留原目录。
- `weekly`：检查→有变化才准备→运行→归档→比较。单实例锁防重叠；成功结束才更新已处理指纹。无变化安静。
- `performance-pair`：对新旧发布版 native 逐次交错采样，输出到 `performance-pairs/`。GitHub R06 任务还会在同一 hosted runner 上对 Node、WASM、浏览器主线程和 Worker 交错采样，并逐配置保留原始点及 p50/p95。

迁移后的正式周度入口是 GitHub Actions 的 IANA `Asia/Shanghai` 周一 10:00 调度；不依赖本机 Codex。
本地 `weekly` 仅保留给迁移前历史复现和故障诊断，不作为 GitHub 正式结果来源。

## 对照报告

`report.html` 按 R01—R09 分 tab，手册分组只作导航。每项先提出可回答的问题，左侧说明测试动作、具体通过条件或尚待完成的实验要求；右侧展示本轮执行情况、具名观测项和结论范围。文档事实项才使用 GT、预期答案和独立取证；安全实验、人工审阅、接口等价性、性能测量及平台覆盖分别说明其方法。差异优先展示且默认展开，一致项默认折叠；可搜索、按格式及结果筛选、全部展开或折叠。“文件索引”列出全部语料及关联断言，无执行记录的文件明确显示未执行。

`case_explanations.py` 是呈现说明，不是 evaluator；它将机器值解释为测试语境中的含义，例如私有样本数量、校验问题数、Worker 心跳阈值。说明只适用于已核对的冻结实现哈希，旧实现无法匹配时明确回退为原始规则。`case-protocols.json` 保存本页说明，原始预期、实际值、状态和 GT 审批不变。`unknown` 两边一致、环境预检或文件存在等有限结论，都不能因呈现优化升级成更强的验收证明。

草案与实测一致仍保持 REVIEW，解析错误、target/value 缺失、合法 null 和零值分别呈现。正式报告中的未审答案显示未执行；已归档诊断可用于查看这些草案的实测值，二者不混用。接口 native 比较基准不标成独立文档事实 GT。

页面完全离线，无外部字体、脚本或网络请求。源文件链接指向本机内容缓存及原始地址。新运行冻结匹配的语料/GT 元数据到 `report-context.json`；重建旧运行时，只有哈希绑定一致的元数据才能附加。重建生成新目录，保留 `run.json`、`agent-report.json` 和原始证据，`presentation.json` 单独记录呈现版本。原 Core 静态报告保留在 `core-report.html`。

R01 使用字段级证据对照：平台包 checksum、GitHub 附件摘要、已验签的 repository/subject/commit/tag、各引擎包与 JS/MCP 的 LICENSE/NOTICE，以及 npm 实际审计数量、签名数量和原始日志。每个字段都有独立状态及证据位置；不把错误列表 `[]`、退出码 `0` 或附件总数当成证明。许可证正文仅允许换行符差异，原始字节 SHA 与全文仍归档。第三方披露完整性单列待审，不由文件存在替代。

## GT 审批

### 可交互的独立管理模块

当前维护范围从数据集来源清单导入：

```sh
python3 benchmark/scripts/release_acceptance.py --home benchmark/artifacts/acceptance \
  dataset import --source 格式测试数据集
```

再次导入时，文件路径变化但内容哈希和逻辑文件名未变的样本会保留 GT 与审批；新增内容不会继承答案；
删除的样本会退出活动项目；内容相同但逻辑文件名或格式变化时，相关答案标为 `stale`。刷新前的数据库、
项目快照及不再使用的对象会存入 `benchmark/artifacts/acceptance/migrations/`，避免旧样本继续混入当前页面和执行输入。
导入器按 `来源清单.tsv` 的实际行数工作，不依赖固定 case 数量。

```sh
python3 benchmark/scripts/release_acceptance.py manage --port 8767
```

打开 `http://127.0.0.1:8767`。首轮导入全部维护样本与 GT 到 `benchmark/artifacts/acceptance/casework/`，提供添加样本、重新定位、替换内容、停用、GT 新增/修改/审核和版本历史。通用模块位于仓库根目录 `casework/`，只用 Python 标准库；DeckProbe 的导入、检查定义验证和执行投影位于 `maintenance.py`，不混入通用模块。

启用后，Casework 是样本与 GT 的维护源。页面“同步到验收”生成当前执行输入；`check`、`run`、`weekly` 和 `prepare` 也会同步。`prepare` 不再重新生成并覆盖人工维护的样本与答案；新增自动生成候选需要显式维护。旧 `approve --decisions` 在管理模式下拒绝写入，避免两套审批互相覆盖。

编辑会创建待审版本；批准/拒绝/暂缓记录均保留。替换文件使答案需重核，停用样本不删除历史且不缩小声明矩阵分母。私有文件继续受 R02 扫描禁令约束，通用管理模块本身不执行文件或产品。历史报告和证据不被重写。

停服务后重新执行同一命令可恢复。Casework 数据目录需随样本一起备份，不能仅保存页面。跨项目复用、通用 JSON 契约及独立运行方式见 `casework/README.md`。

### 旧只读审核入口（未启用管理模块时）

打开状态目录里的 `answers/review.html`。每一条均展示 ID、预期、取证方式、源哈希、答案哈希。批准方案不等于批准这些新答案。

审核页支持 PDF / Word / Excel / PowerPoint / iWork 筛选，可按扩展名或相似场景分组，并搜索中文问题、样本说明或技术 ID。默认先显示中文问题与答案；独立依据说明取证动作和局限，工具名称保留原文，原始 ID、依据和哈希可展开查看。该页仍为只读。呈现由 `review_view.py` 生成，不修改 GT 对象、生成器文件或审批记录；`prepare` 与 `approve` 后自动刷新。

复制 `answers/decisions.template.json`，只保留本人已审阅的条目，填写 `decision: approved|rejected` 和 `reviewer`；保留准确的 `answerDigest`。不要整批自动把 pending 替换为 approved。

```sh
python3 benchmark/scripts/release_acceptance.py approve --decisions /absolute/path/reviewed-decisions.json
```

审批记录不可覆盖，重复导入相同决定是幂等的。答案、样本或依据变化会产生新哈希，原审批失效。拒绝条目继续保留待处理状态。历史 67 个用例及其旧批准记录在 `corpus/legacy-review.json`，保留但不假定它们已批准新的证据绑定。IWA 配对导出文件不当作独立事实答案。

## 样本和覆盖

本地历史样本仅复制到只读内容缓存；原件不修改。公开样本来自固定 Apache POI commit，URL、SHA、体积及许可证来源在 `config/public-sources.json`。没有执行宏、启动 Office 或向外发送文档。

生成器提供 PDF 页树、零/单/多项、深层 Worker 压力 PDF、OOXML 正常结构和类型变体、外链、后缀错配、截断、旧 XML iWork 结构样例。宏扩展名无 VBA 时，其答案为不含 VBA，不能计入宏正例；公开 SimpleMacro.xlsm 提供真实 VBA 包。

独立事实使用 pypdf、ElementTree/zipfile、xlrd；不调用 DeckProbe 生成答案。当前尚缺：真实旧 XML iWork、签名 OOXML/PDF、加密 PDF、IWA 深层事实，以及完整 target 的正负例/边界证据。这些缺口保留在报告，不能因已有少量 fixture 可运行而消失。

`declarations.json` 是历史 catalog 的单调合并，不因新版少报 target 缩小分母。声明矩阵本身保持待审，后续审核不得删除现有要求来迎合产品输出。事实覆盖、特征方向覆盖、接口覆盖、平台覆盖分别展示。模板扩展名没有独立 catalog 时，记录缺口，不以 DOCX/XLSX/PPTX 通过自动替代。

## R01—R09 的当前执行能力

| 项目 | 已实现 | 仍需补齐的签核条件 |
|---|---|---|
| R01 | 发布资产/依赖锁、所有平台 checksum、公开 attestation bundle 验签、tag commit 绑定、版本、许可证/NOTICE、npm 签名 | 未通过的来源/声明证据须复核；不以 checksum 替代来源证明 |
| R02 | 权限/身份检查、私有扫描拒绝、原生可行性探针、前后控制/丢事件/绑定校验器、文案 REVIEW | 管理员与 FDA 授权；DNS/代理/回环的可靠隔离与归因；真实本轮采集。探针不冒充完整 R02 |
| R03 | 内容寻址语料、生成/公开样本、逐答案 GT、历史审批保留、声明覆盖分母 | 每条新答案审核、完整事实与场景覆盖 |
| R04 | 发布 schema、状态、confidence、source/path、成本计数、partial 关系校验 | 未覆盖 target 的独立事实与版本迁移复核 |
| R05 | required/optional/no-piggyback/exact/budget 成组采集，共享语义/成本断言 | 精确路径集合、预算临界值、外部 I/O 口径答案审核 |
| R06 | GitHub hosted runner 上候选版/前版交错采样；每配置预热 5 次、采样 50 次；逐配置展示 p50/p95、变化比例与原始点 | 这是版本趋势观察，不是绝对延迟 SLA；增长达到 20% 且 2ms 标 REVIEW，数据不完整标观察性 BLOCKED，均不影响发布门禁 |
| R07 | CLI/JSONL、Node byte shapes、Browser/Worker、MCP 四工具/schema/好坏好/路径拒绝/参数拒绝/超时，实际发布包默认与指定引擎 | IWA/Legacy 等深度代表语料、WASM fallback、完整平台组合 |
| R08 | 全平台资产静态验证、ARM64 macOS 直接/native npm 启动 | Intel Mac、Linux GNU/musl、Windows 的原生运行证据 |
| R09 | 固定 SECURITY 快照、GitHub 私密报告设置读取 | 已认证表单访问；功能若关闭是配置失败，不是假装权限不足。绝不自动提交漏洞 |

## 安全环境准备

见 [macos-monitoring.md](docs/macos-monitoring.md)。本工具不会自动授予 TCC、关闭 SIP、改 sudoers、关闭整机网络、清空 PF 主规则或启动 Office。未证明隔离时私有扫描始终阻塞，不能通过上传一份“自检通过 JSON”解除。

## 证据、比较及失败分类

每次产生 Core 的 `report.html`、`agent-report.json`、`run.json`，附 `questions.json`、`coverage.json`、原始进程输出、执行实现快照和 `evidence-manifest.json`。哈希检查也拒绝未登记的附加文件。运行目录不覆盖，断点复用前核对输入与证据。报告重建使用新目录。只变更答案/审批时，满足相同发布资产、实现、政策和源哈希条件的事实证据可复用；公共契约仍执行。

本机与完整手册分别判定。FAIL 优先于 INCOMPLETE，未审需要 REVIEW；一个 P0 失败不能被其他分数抵消。R06 正式性能和 R08 其他平台属于完整签核层，本机运行不替它们通过。

对比同时锁定代码/evaluator、政策、语料、答案/审批、声明矩阵。新增检查归为 new_coverage；已存在的问题为 existing_failure；任一比较条件变化为 incomparable。保留最近一次运行与最近一次正式 PASS，FAIL 不替换通过基线。

每轮同时保存最新/前一发布版对照和周度基线。自第二轮起，将上轮冻结的完整组件组合按本轮规则重新执行后，与本轮候选组合比较；即使一周内发布了多个版本，也不会用相邻 tag 替换上周基线。

接口归一化只消除 input 的运行表面标记和耗时，并对三个 header target 明确允许 file/bytes 输入来源措辞差异：`input path ↔ input name`、`input path + detected profile ↔ input name + detected profile`、`filesystem metadata ↔ source length`。其他 source/path/value/confidence/成本信息均保留。

## 测试

```sh
python3 -m unittest discover -s benchmark/acceptance/tests -v
python3 <deck-benchmark-skill>/scripts/check_core.py benchmark/scripts/deck_benchmark.py
```

验收代码可进 Git，状态目录、私有样本、含元数据的原始报告不进 Git。不会自动提交或推送仓库，也不会自动删除历史结果。

### 按样本用途校准出题

旧版工具 `python3 -m benchmark.acceptance.purpose_audit` 仅适用于迁移前的 v1 数据；v2 项目请使用下方 `fact_inventory`，不要重跑旧工具。它检查现有样本的用途与 GT 对应关系，为已知且内容绑定有效的公开最小样本独立取证，补充外链、JavaScript 和 Word 段落数草案及负例。既有答案和审批保持不变，重跑不重复生成已有 target 的问题，后续人工维护的用途不会被覆盖。原始取证和审查清单存入 `artifacts/acceptance/purpose-audits/`。

Casework 的“维护用途”用于展示主要问题与缺口，不能替代发布声明矩阵，也不代表运行通过。产品未提供外链数量 / 地址集合接口时，只记录独立结构事实和接口缺口，不虚构可执行 target。私有历史文件的用途标记是待核验计划，不凭文件名生成事实答案。

### 独立文档事实库 v2

当前格式数据集可用下列命令安全切换为活动 Casework 项目。旧项目和 SQLite 备份保留；重复执行只接受
相同 case ID / 内容哈希集合，不覆盖人工历史：

```sh
python3 benchmark/scripts/release_acceptance.py --home benchmark/artifacts/acceptance \
  dataset import --source 格式测试数据集
python3 -m benchmark.acceptance.fact_inventory
```

声明矩阵把扩展名与实际解析 profile 分开，包含 `encrypted-ooxml`，并将六类必需场景绑定到具体已审答案。
先生成草案，逐场景绑定答案，再取得内容摘要供人工审核；只有显式执行 `approve` 才会批准全部声明行：

```sh
python3 benchmark/scripts/release_acceptance.py --home benchmark/artifacts/acceptance \
  claims prepare --catalog 格式测试数据集/DeckProbe字段目录.json
python3 benchmark/scripts/release_acceptance.py --home benchmark/artifacts/acceptance \
  claims bind-scenario --scenario identity --answer CASE_ANSWER_ID
python3 benchmark/scripts/release_acceptance.py --home benchmark/artifacts/acceptance claims review-digest
python3 benchmark/scripts/release_acceptance.py --home benchmark/artifacts/acceptance \
  claims approve --digest REVIEWED_DIGEST --reviewer YOUR_NAME
```

文档事实、版本契约和产品映射已分开。执行 `python -m benchmark.acceptance.fact_inventory` 可在已安装 pypdf、xlrd、olefile 的独立 Python 环境中，为维护范围生成离线事实草案（单文件 45 秒，ZIP 解压预算 256 MB）。本机准备环境为 `artifacts/acceptance/tools/signing-venv/bin/python`。取证不会执行 DeckProbe；私有文档只在本机独立解析，正式扫描仍受 R02 约束。

事实库导出为 `facts/index.json`，产品执行输入为 `answers/index.json`；没有映射的事实照常保存和人工批准，不进入产品执行，不被算成通过。原 99 条答案通过机械迁移保留摘要与审批；迁移前数据库备份位于 `migrations/facts-v2/before.sqlite3`。首次修改事实内容按 v2 摘要重新审核。

资源图片数、按内容去重的图片数、图像 XObject 数、原生表格数、显式公式单元格数分别登记口径；视觉表格 / 公式及暂不支持解码的旧格式不能填 0。未知、不适用、合法零值分开保存。已有值与新取证冲突会记录 finding，原答案不自动更新。

### case 用途与参考取证

`case_scope.py` 按已登记用途及旧 suite 问题一次性整理范围，保留全部事实和审批；旧 suite 的审批不会自动继承。迁移备份和数量摘要位于 `migrations/case-scope-v1/`，已执行后拒绝重复覆盖人工范围维护。

`answerScopes` 为独立范围记录，参考项不进入 `answers/index.json`，仍保留在完整事实库与管理历史中。声明矩阵及覆盖分母不随精简而缩减。范围维护请使用 Casework 的“移为参考取证 / 纳入本 case GT”；后续自动取证默认仅补参考，不自动扩张 case。

### 场景去重

Casework 默认按样本呈现一个验收场景，将原子事实和版本契约作为必要断言折叠在场景内。共享规则矩阵按 factKey / check 定义统计跨 case 复用；发布执行仍逐断言保留精确预期、证据与 finding。场景级审核不会改变摘要模型，也不会把一个样本的答案复制到另一个样本。
