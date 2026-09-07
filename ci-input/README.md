# GitHub 验收输入

`current/` 只能由 Casework/acceptance 的显式快照导出命令生成。正式工作流要求该目录包含
`READY`、`snapshot.json`、`samples.json`、`answers.json`、`claims.json`、`policy.json`、
`SHA256SUMS` 和获准公开的 `objects/`。

本目录不接受 Casework SQLite、本地缓存、私有样本、未审核答案或个人绝对路径。

当前 GT 精简和人工审核尚未完成，因此仓库暂不提供伪造的 `current/READY`。可用以下命令生成
供人工检查的草案快照：

```bash
python benchmark/scripts/release_acceptance.py snapshot export \
  --allow-draft --output /tmp/deckprobe-ci-input
python benchmark/scripts/release_acceptance.py snapshot validate \
  --allow-draft --snapshot /tmp/deckprobe-ci-input
```
