# Casework · 文档事实与 GT 管理 0.2

独立本地模块，Python 3.9+，管理服务仅依赖标准库。SQLite 保存项目、原件内容缓存和不可覆盖的历史快照。独立文档取证器属于接入项目，可有自己的依赖；不包含在通用管理服务中。

## 三层数据

1. 文档事实：稳定事实标识、问题、统计口径、答案状态、值、独立依据、文件绑定和人工审批。无需产品提供对应字段。
2. 产品映射：在项目级 `mappings[answerId]` 中记录 target、请求参数和适用要求；可以暂不映射或标为产品未支持。
3. 执行结果：由接入项目单独生成。事实已批准、字段已映射，不等于产品运行通过。

错误码、预算和状态限制属于版本契约预期，保留在独立页签，不能当作跨产品的文档事实。

## 页面操作

- 查看全部样本，按格式、审核状态、待核定或未映射事实筛选。
- 样本内分为“文档事实 / 版本契约预期 / 产品字段映射”；事实可再按图片、表格、公式、外链、安全、基础分类。
- 新事实无需填写产品 target。问题必填；选择“已有答案”时填写实际值；可先保存“待核定”或“暂无法取证”。
- `known` 表示已取到值，包括合法的 0、false、null；`unknown` 为待核定；`unreadable` 为暂无法取证；`not_applicable` 是有依据的不适用结论。
- 批准事实需统计口径、取证方法、操作者及核对确认。待核定 / 暂无法取证不能直接批准。操作原因选填。
- 修改值或口径创建待审版本。只调整映射不改变事实审批；修改事实口径会将旧映射标为未配置，需重新确认语义一致。
- 同内容同后缀重新定位保留逻辑文件名和审批；替换文件创建新版本，原 GT 需重核。
- 主要用途显示出题缺口，不用于缩小产品声明覆盖分母。新的独立取证若与已有值冲突，只记录差异，不覆盖已有答案。

## 独立运行

```sh
python3 casework/run.py --data /absolute/path/state import project.json
python3 casework/run.py --data /absolute/path/state import-evidence demo normalized-evidence.json
python3 casework/run.py --data /absolute/path/state serve --port 8767
python3 casework/run.py --data /absolute/path/state export demo exported.json
```

浏览器打开 http://127.0.0.1:8767。也可 `pip install ./casework` 后使用 `casework` 命令。HTTP 仅绑定回环地址，检查 Host、Origin 和写操作令牌。操作者姓名用于单机审计，不是多用户认证。文件作为附件下载，不执行宏或脚本。

## 通用 JSON 示例

```json
{
  "schemaVersion": 1,
  "project": {
    "id": "demo",
    "name": "独立事实示例",
    "factSchema": 2,
    "mappings": {},
    "samples": [{
      "id": "stable-file-id",
      "path": "/absolute/path/example.pdf",
      "inputName": "example.pdf",
      "sha256": "实际文件哈希",
      "bytes": 123,
      "format": "pdf",
      "private": true,
      "answers": [{
        "id": "stable-fact-id",
        "kind": "fact",
        "factVersion": 2,
        "factKey": "links.external_reference_count",
        "question": "文件中有多少条外部链接引用？",
        "definition": "按 URI 动作字典计数，相同间接对象只计一次，不含纯文本网址。",
        "valueState": "known",
        "expected": 1,
        "evidence": {"method": "独立解析器", "location": "可复核对象位置"}
      }]
    }]
  }
}
```

封装格式仍兼容 schemaVersion 1；项目内 factSchema / factVersion 2 标记独立事实模型。`answers` 为兼容字段名，包含 kind=fact 的事实及 kind=contract 的契约预期。新事实摘要不包含产品字段映射。

导入项目不自动继承审批。`import-evidence` 接受 benchmark GT v2 的 `cross_validation` / `ground_truth`
规范化记录，按 case ID 或 SHA-256 关联样本并生成待审事实；第三方原始输出应先经过适配器规范化。
导出不内嵌文件字节；迁移需一并复制内容缓存，再重新定位失效路径。不同项目的映射独立维护，不要求不同产品共享 target 命名。

## 旧项目迁移与历史

```sh
python3 casework/run.py --data /absolute/path/state migrate-facts demo
```

机械拆分原 target 检查与映射：原问题、答案、依据、文件绑定、摘要和审批均保留，旧 check 等字段只作为旧摘要的兼容来源。首次编辑事实采用新摘要并重新待审。原错误 / 状态检查仍属于版本契约。迁移不会批准任何草案。

`casework.sqlite3` 保存当前状态和历史；`objects/<sha256>/<logical-name>` 保存只读缓存。备份时停止服务并复制完整数据目录。当前无永久删除入口，不合并冲突导入；不能只保存 HTML 页面。

## DeckProbe 接入

`benchmark/acceptance/maintenance.py` 将独立事实导出到 `facts/index.json`，仅将已配置映射的事实和契约预期转换到 `answers/index.json`。未映射事实保留 GT，不伪造产品 target，也不计为产品通过。已有答案是否可签核仍由审批、文件绑定、执行证据与手册决定。

`benchmark/acceptance/fact_inventory.py` 是独立、离线、按文件限时的取证器。它明确区分资源数、引用数、内容去重数，以及原生表格 / 公式和视觉表格 / 公式。取不到值时保留未知状态；不执行待测产品、不请求外链、不执行文档脚本。私有文件原件和取证材料留在本机。

## 测试

```sh
python3 -m unittest discover -s casework/tests -v
python3 -m unittest discover -s benchmark/acceptance/tests -v
```

## 按 case 用途维护范围

`project.answerScopes[answerId]` 区分 `case`（纳入 GT）和 `reference`（参考取证）。它独立于事实摘要和审批；移为参考不会删除或改写历史，恢复纳入也不自动批准。页面默认只统计、审核和映射本 case 的 GT，参考取证单独查看，可逐条纳入或移出。

启用 `scopeSchema: 1` 后，批量自动取证的新条目默认作为参考，避免重新堆积通用问题。人工新增的问题默认纳入。审核事实是否正确，与判断它是否服务于当前用例，是两件独立的事。

项目适配器必须读取此范围：参考项即使已有批准和产品映射，也不能参与执行。DeckProbe 适配器已遵循这一规则。样本缺少专用 GT 时明确显示缺口，不能用参考条目数量补足覆盖。

## 验收场景与断言复用

管理页以一个 case 的验收场景为审核单位，页数、大小、状态、数量等作为场景内的必要断言。场景级审核使用每条断言当前摘要，任一条发生变化、缺少依据或答案待核定时，整次批准会原子失败，不会产生半批准状态。底层断言仍可单独编辑或审核。

相同 `factKey` 或检查定义表示共享规则；页面显示该规则覆盖的 case 数量。共享规则只定义一次语义，但每份文件的预期值、哈希绑定和执行结果仍独立保存。重复问题不再等同于重复 case。
