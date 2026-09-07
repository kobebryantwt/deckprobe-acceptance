# DeckProbe 独立发布验收与基准评测体系 (deckprobe-acceptance)

本仓库是 [DeckProbe](https://github.com/deckflow/deckprobe) 的独立发布验收、基准测试（Benchmark）与 Ground Truth（GT）管理仓库。

本仓库严格基于 [《DeckProbe GitHub 最终发版验收手册》](./deckprobe-github-release-acceptance.md) 建设，验证 DeckProbe 作为纯本地、目标驱动扫描器的发布质量：提供可解释的路由信号，不渲染、不编辑、不执行宏、不上传文件，也不作最终安全结论。

---

## 核心架构：三层评测模型

本体系采用正交分层的现代化评测架构，避免测试用例盲目膨胀：

```text
┌────────────────────────────────────────────────────────────────────────┐
│                        DeckProbe 评测体系架构                          │
├────────────────────────────────────────────────────────────────────────┤
│ A. 格式契约层（轻量化矩阵）                                            │
│    • 26 种已支持格式的正向容器与 Profile 路由                           │
│    • 13 种未支持格式的 UNSUPPORTED_FORMAT 拦截边界 (PRO-R03)            │
│    • 错配拦截、模板标记、放映标记                                      │
├────────────────────────────────────────────────────────────────────────┤
│ B. 字段 GT 层（高密度复合样本集）                                      │
│    • 采用 Set-Cover（集合覆盖）模型与 Hero Document（全功能主样本）架构 │
│    • 覆盖 120+ 真实 Target（页/段/字/表/图/媒体/宏/签名/画布比例等）    │
│    • 客观真值独立存证，包含前瞻未支持特性（用于倒逼后续迭代）            │
├────────────────────────────────────────────────────────────────────────┤
│ C. 行为回归层（非功能与集成合同）                                      │
│    • CLI、JSONL、Node SDK、浏览器 Worker、大模型 MCP 跨端语义等价性    │
│    • Linux 命名空间纯本地断网运行自检 (PRO-R02)                         │
│    • 内存与时间预算超限拦截保护 (Budget Boundary)                       │
│    • 重复采样一致性 (Determinism) 与性能趋势 (PRO-R06)                  │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 完整使用流程指南（Step-by-Step）

整套体系支持完整的「本地维护 ➔ 本地自验 ➔ CI 快照导出 ➔ GitHub 全自动流水线」闭环：

### 步骤 1：本地依赖环境准备

确保本地已安装 Python 3.12+ 与 Node.js 24+：

```bash
# 1. 安装验收框架核心依赖
python3 -m pip install -r benchmark/acceptance/requirements.txt

# 2. 以可编辑模式安装本地 Casework 管理包
python3 -m pip install -e casework
```

---

### 步骤 2：启动 Casework 本地服务与 GT 审核

Casework 提供基于本地回环地址与 SQLite 数据库的真值管理 Web 界面，不执行任何外部脚本或待测程序：

```bash
# 启动本地管理服务（默认端口 8767）
python3 casework/run.py --data benchmark/artifacts/acceptance/casework serve --port 8767
```

1. 浏览器打开 [http://127.0.0.1:8767/](http://127.0.0.1:8767/)；
2. **右上角填写姓名**：用于单机审计历史追踪；
3. **场景化核对**：
   * 顶部统计栏支持**点击卡片联动筛选**（例如点击「待审核断言」即可自动过滤出包含待审题目的样本）；
   * 左侧浏览 67 个场景卡片，查看每个复合样本的标准答案、统计口径与独立取证依据；
4. **一键审核全部**：
   * 核对无误后，点击顶部操作栏的 **「一键审核全部」**，勾选确认后即可在单次原子事务中批准全部场景；
5. **同步到验收**：
   * 点击右上角 **「同步到验收」**，系统会将 SQLite 中的已审数据固化导出为执行器所需的文件系统契约（`answers/index.json` 等）。

---

### 步骤 3：本地执行全量比对验收（本地验货）

在推向远端前，可直接在本地针对待测 DeckProbe 发布包执行完整扫描比对：

```bash
# 执行本地全量比对（诊断模式）
python3 benchmark/scripts/release_acceptance.py run --diagnostic
```

* 运行完成后，终端会输出生成的本地交互式 HTML 审计报告路径：
  ```bash
  open benchmark/artifacts/acceptance/runs/<runId>/report.html
  ```
* 报告完整展示通过率、300+ 检查项明细、各平台适配器一致性与证据链追踪。

---

### 步骤 4：生成正式 CI 发布快照（生成 READY 凭证）

当本地 GT 全部批准并确认无误后，导出供 GitHub Actions 消费的脱敏公开快照：

```bash
# 1. 导出正式快照至 ci-input/current
python3 benchmark/scripts/release_acceptance.py snapshot export --output ci-input/current

# 2. 校验快照完整性
python3 benchmark/scripts/release_acceptance.py snapshot validate --snapshot ci-input/current
```

* 此时 `ci-input/current/` 目录下将生成官方放行凭证 **`READY`**（包含已审批声明、公共样本与答案校验和）。

---

### 步骤 5：GitHub Actions 自动化流水线

将代码提交推送到 GitHub 远端仓库后，自动化验收将全自动接管：

#### 1. 开启 GitHub Pages 权限（首次配置）
* 进入仓库的 **Settings** ➔ **Pages**；
* 将 **Build and deployment** 下的 **Source** 设置为 **`GitHub Actions`**。

#### 2. 流水线执行内容（`.github/workflows/release-acceptance.yml`）
* **触发方式**：
  * **定时触发**：每周一上午 10:00（北京时间）自动巡检；若无新发布则自动记录 `NO_CHANGE`，不浪费构建资源；
  * **手动触发**：在 GitHub Actions 页面点击 **Run workflow**，支持指定 Release Tag 或强制运行。
* **执行任务全览**：
  1. `freeze`：锁定目标 Release 资产与输入快照（必须具备 `READY` 凭据才放行）；
  2. `main-functional`：执行 R01、R03、R04、R05、R07、R09 全套功能验收；
  3. `security-linux`：在 Linux network namespace 与 nftables 断网沙箱中验证 R02 纯本地安全；
  4. `performance`：高精度测量候选版本与前一正式版的交错性能趋势（R06）；
  5. `platform-smoke`：覆盖 **macOS (ARM64 / Intel x64)、Linux (ARM64 / x64 GNU 与 musl Alpine)、Windows x64** 共 7 大平台二进制可用性（R08）；
  6. `aggregate-report`：聚合所有平台与任务结果，生成统一 HTML 审计总报告；
  7. `persist-and-pages`：将长期运行历史写入 `acceptance-results` 分支，并自动发布到 GitHub Pages 在线展示；
  8. `verdict`：执行最终发版通过/失败熔断裁决。

---

## 目录结构说明

```text
deckprobe-acceptance/
├── .github/
│   ├── workflows/
│   │   └── release-acceptance.yml   # 7 平台发布验收 GitHub 工作流
│   └── actions/
│       └── setup-acceptance/        # Python 3.12 + Node 24 统一配置 Action
├── benchmark/
│   ├── acceptance/                  # 验收引擎：Runner、Coverage、Contracts、报告生成器
│   └── scripts/
│       └── release_acceptance.py    # 统一验收 CLI 入口
├── casework/                        # 本地 GT 管理服务（Web 界面与 SQLite 审计库）
│   ├── casework/                    # 服务端、事实映射、前端 app.js / style.css / index.html
│   └── run.py                       # Casework CLI 启动入口
├── ci-input/                        # 【生产基准输入】经脱敏与人工签核的正式快照
│   └── current/
│       ├── READY                    # 发版放行凭证
│       ├── snapshot.json            # 快照元数据（status: approved）
│       ├── answers.json             # 111 条公开可执行黄金断言
│       ├── claims.json              # 2,104 行完整能力声明与场景绑定
│       ├── policy.json              # 性能语料与门禁策略
│       ├── SHA256SUMS               # 校验和清单
│       └── objects/                 # 获准公开的样本原件
├── 格式测试数据集/                  # 本地持续维护的源素材库（含来源许可与校验和）
│   ├── 01_明确支持/                 # 51 份高密度活动样本（覆盖 26 种格式，含 10 份旧版 Office）
│   ├── 02_暂未支持/                 # 13 份未支持格式负向样本
│   ├── 来源清单.tsv                 # 来源归属与版权政策
│   └── SHA256SUMS                   # 64 份活动文件校验和
└── deckprobe-github-release-acceptance.md # 官方最终发版验收手册规范
```

---

## 增量维护指南（后续版本迭代）

当 DeckProbe 发布新版本（如 2.6.0、3.0.0）时，系统具备**增量继承（Delta Inheritance）机制**，绝不需要每次重审成千上万道题目：
1. **未变更字段**：自动继承上一版的 `approved` 审批状态，日常发版审核量为 0；
2. **新增字段**：只有真正新增的 Target 会自动生成待审条目，只需在 Casework 界面核对新增项；
3. **前瞻字段激活**：我们在业务大样本中预埋的事实（如 12,844 个公式、OMML 数学公式、转场切换数等），一旦新版 DeckProbe 宣称支持，只需在映射中开启，即可直接将其激活为正式考题验证新功能算法！
