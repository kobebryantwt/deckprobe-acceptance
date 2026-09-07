# Deep 探测、第三方交叉验证与 GT 记录约定

## 完整性口径

DeckProbe 2.5.0 的完整探测口径为：

```bash
deckprobe \
  --probe-level deep \
  --targets @all \
  --minimum-confidence low \
  --view full \
  <文件>
```

`deep` 是有序层级 `header < metadata < deep` 的最高层；`@all` 选择当前 profile 中 `min_level <= deep` 的全部适用 target。因此该组合包含 header、metadata 和 deep 字段。`deep` 单独使用但不指定 `@all` 时只会使用该层级的默认字段集，不等同于字段全集。

当前 live target 目录共有 124 个唯一字段。字段是否适用于某个 profile、最小层级、值类型和 JSON Schema 见 `DeckProbe字段目录.json`。

## 产物

| 文件 | 用途 |
|---|---|
| `DeckProbe深度探测完整结果.json` | 单个合法 JSON 文档，包含全部 74 条原生 full evidence 记录 |
| `DeckProbe深度探测完整结果.jsonl` | 与上项等价的流式版本；每行一条记录 |
| `DeckProbe深度探测汇总.json` | 状态码、报告状态和 profile 数量汇总 |
| `DeckProbe字段目录.json` | 从 `formats` 和 `targets <profile>` 实时生成的 124 字段目录 |
| `benchmark-gt.schema.json` | 规范化第三方事实、原生 DeckProbe 报告和 GT 草案的统一 Draft 2020-12 Schema |
| `benchmark-cross-validation.example.json` | 第三方工具归一化记录示例 |
| `benchmark-ground-truth.example.json` | 尚未审批的 GT 草案例子 |

## 三种记录

- `record_collection`：单个 JSON 文档中的原生记录集合。
- `deckprobe_native`：DeckProbe 原生 full report。只作为被测工具输出和对照线索，不能直接成为自己的 oracle。
- `cross_validation`：第三方工具的独立观测。建议保留原始输出到 `raw_output`，同时把可比较值归一化到 `fields`。
- `ground_truth`：待审或已审 GT。每个字段必须带 `ground_truth`，新生成内容必须先设为 `review_status: draft`。

第三方工具的**原始输出不需要模拟 DeckProbe，也不要求直接符合本 Schema**。适配器保留原始输出，
再把可独立解释的事实转换为 `cross_validation.fields`。`fact_id/definition/value/evidence` 是事实层；
`target_mapping` 是单独的产品映射层。修改映射不会改写事实答案或继承人工审批。

## 字段状态

| `state` | 含义 | 是否允许 `value` |
|---|---|---:|
| `observed` | 工具实际得到值；值可以是合法的 JSON `null` | 必须 |
| `absent` | 文件中没有记录该字段 | 不允许 |
| `not_applicable` | 字段不适用于该格式/profile | 不允许 |
| `unsupported` | 工具不支持提取该字段 | 不允许 |
| `unknown` | 工具无法确定 | 不允许 |
| `error` | 该字段提取失败 | 不允许 |

不要把 `absent`、`unsupported`、`unknown` 都写成 `null`。`null` 只能在目标字段自己的值 Schema 允许且工具确实返回了空值时，配合 `state: observed` 使用。

## 状态码

本轮语料实际出现：

- `0`：探测进程成功；报告状态可能是 `ok` 或 `partial`。
- `3`：`UNSUPPORTED_FORMAT`。
- `4`：`MALFORMED_INPUT` 或预算类输入失败；本轮 9 个已知回归文件均为 `MALFORMED_INPUT`。

完整错误码约束已经嵌入 `benchmark-gt.schema.json` 的 DeckProbe 原生报告定义。

## 从交叉验证到 GT

1. 用第三方工具生成 `cross_validation` 记录，并保存工具版本、命令、文件 SHA-256 和证据定位。
2. 对同一 target 比较多个独立来源；DeckProbe 自身不得作为唯一 oracle。
3. 将准备采用的期望写入 `ground_truth.expected`，选择明确的 comparator。
4. 保持 `review_status: draft`，人工检查证据和分歧。
5. 只有审核确认后才改为 `approved` 并进入 benchmark gate/scored check。

Casework 导入规范化记录时仍会清除外部审批状态，要求在当前项目重新审核：

```bash
python3 casework/run.py --data benchmark/artifacts/acceptance/casework \
  import-evidence deckprobe-format-dataset /path/to/cross-validation.json
```

执行比较器解释 `target_mapping`，而不是要求第三方工具返回 DeckProbe 的 report envelope。`value` 检查按
target 的 JSON Schema 校验值类型；`status`、`error`、`allowed_paths` 和 `cost_ceiling` 使用各自的比较结构，
不会错误套用 target value 类型。

JSON Schema 能检查类型、枚举、必填项以及 value 检查对应的 target 值类型，但不能保证同一 `fields`
数组内事实不重复；写入端应以 `(sample.sha256, fact_id, definition)` 做事实唯一键，以独立映射记录关联 target。

## 重新生成

```bash
python3 格式测试数据集/生成深度探测产物.py --deckprobe /path/to/deckprobe
```

生成器不会自动批准任何 GT。

生成后可对发布二进制重新校验全部记录、124 个 target 类型和内嵌 report schema：

```bash
python3 格式测试数据集/验证benchmark契约.py --deckprobe /path/to/released/deckprobe
```
