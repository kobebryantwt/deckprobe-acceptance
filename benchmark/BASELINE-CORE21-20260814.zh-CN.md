# DeckProbe Core 2.1 质量基线（2026-08-14）

本基线使用已批准的质量政策 v1、标准 Benchmark Core 2.1、报告契约 2，以及 Evaluator v2。除 `runtime-parity` 仍为 draft 外，其余 10 个 Suite 均完成严格校验和正式运行。每个运行均生成 `report.html`、`agent-report.json` 和 `run.json`。

| Suite | 判定 | Gate | 质量分 | 覆盖 | 观察项 | 主要差异 |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| summary/security | REVIEW | 65/65 | 91.67 | 100% | 0 | PDF 标题 Unicode 破坏 |
| PDF deep | REVIEW | 17/17 | 89.29 | 100% | 0 | PDF 标题 Unicode 破坏；缺少 `pdf.link_count` |
| OOXML deep | REVIEW | 51/51 | 98.40 | 100% | 0 | DOCX author 与 description 被截断 |
| Legacy deep | REVIEW | 31/31 | 83.33 | 100% | 3 | DOC/PPT CFB entry count 期望 5、实际 8 |
| iWork deep | FAIL | 33/36 | 100.00 | 100% | 13 | 三种格式的 external/missing-data Gate 返回 null |
| edge corpus r2 | FAIL | 47/48 | 90.79 | 100% | 4 | Legacy title 状态 Gate；大 PDF内部预算错误；链接、修复页数、图片与 CFB 计数差异 |
| CLI contract | FAIL | 61/62 | N/A | N/A | 0 | schema discovery 根类型合同失败 |
| budget | PASS | 2/2 | N/A | N/A | 0 | 预算错误合同满足 |
| determinism | PASS | 2/2 | N/A | N/A | 0 | 两次默认输出逐字节一致 |
| exact slide count | PASS | 无 Gate | N/A | N/A | 1 | B1 仅记录：实际为精确 16 页 |

## 报告目录

- `benchmark/artifacts/runs/deckprobe-summary-security-v1/deckprobe-summary-security/core21-policy-v1-20260814/`
- `benchmark/artifacts/runs/deckprobe-pdf-deep-v1/deckprobe-pdf-deep/core21-policy-v1-20260814/`
- `benchmark/artifacts/runs/deckprobe-ooxml-deep-v1/deckprobe-ooxml-deep/core21-policy-v1-20260814/`
- `benchmark/artifacts/runs/deckprobe-legacy-deep-v1/deckprobe-legacy-deep/core21-policy-v1-20260814/`
- `benchmark/artifacts/runs/deckprobe-iwork-deep-v1/deckprobe-iwork-deep/core21-policy-v1-20260814/`
- `benchmark/artifacts/runs/deckprobe-edge-corpus-v1/deckprobe-edge-corpus-deep/core21-policy-v1-20260814-r2/`
- `benchmark/artifacts/runs/deckprobe-cli-contract-v1/deckprobe-cli-contract/core21-policy-v1-20260814/`
- `benchmark/artifacts/runs/deckprobe-budget-v1/deckprobe-budget-1k/core21-policy-v1-20260814/`
- `benchmark/artifacts/runs/deckprobe-determinism-v1/deckprobe-repeat-exact-slide-count/core21-policy-v1-20260814/`
- `benchmark/artifacts/runs/deckprobe-exact-slide-count-v1/deckprobe-exact-slide-count/core21-policy-v1-20260814/`

边界语料第一次运行因 45 秒适配器超时使大 PDF 被标为 blocked；Target 超时随后提高到 120 秒并以 `r2` 完整重跑。`r2` 完成率为 100%，是本基线采用的边界语料结果。大 PDF 最终由 DeckProbe 自身返回内部 5 秒 `BUDGET_EXCEEDED`，因此对应事实未解析，属于产品可观察结果而非基准设施阻塞。

标准 Core 2.1 规定：即使质量分达到 95，只要仍有 scored 检查失败，发布判定仍保持 REVIEW。因此 OOXML 98.40 分不是 PASS；这避免把已知事实差异标记为完全通过。
