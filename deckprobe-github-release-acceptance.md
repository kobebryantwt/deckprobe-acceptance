# DeckProbe GitHub 最终发版验收手册

## 目标

验证 DeckProbe 作为纯本地、目标驱动扫描器的最终 release：它提供可解释的路由信号，不渲染、不编辑、不执行宏、不上传文件，也不作最终安全结论。

## 固定输入

- Git tag、各平台 release binary、checksums/attestation、Apache-2.0 LICENSE、schema-v2、target catalog。
- PDF、现代/旧版 Office、XLSB、现代 Keynote/Numbers/Pages、旧 XML iWork 与损坏/加密/宏样例。
- 基准机器说明和网络/进程监控。

## 一票否决项

- 任意本地输入被上传、宏/外链被执行，或产品文案把扫描写成完整安全判定。
- schema、target catalog、CLI/Node/WASM/MCP 输出不兼容却没有版本迁移说明。
- 已宣称支持的格式/target 返回未文档化的空值或静默错误。

## 验收用例

| ID | 声明 | 步骤 | 通过证据 |
|---|---|---|---|
| PRO-R01 | 可追溯发布 | 下载各平台 binary/包，核 checksum、attestation、version、LICENSE | SHA、签名/未签名披露与 tag 一致 |
| PRO-R02 | 纯本地安全边界 | 断网和网络监控下扫描含宏/外链样例 | 无网络、无 Office/宏启动、无外链访问；报告只提供扫描结果 |
| PRO-R03 | 格式与限制 | 按矩阵扫描 PDF、Office、iWork、负向格式 | 支持项按 target 返回值；XLSB、旧 XML iWork、受限 PDF 等限制按文档状态出现 |
| PRO-R04 | target 语义 | 对 metadata/structure/security/assets/quality target 运行，并校验 schema | value、status、confidence、path、evidence、成本计数齐全；`partial` 不被呈现为健康结论 |
| PRO-R05 | path 共享 | 请求可共享必需 target 与可选 target | 报告的 selected path、piggyback 和成本与测试计划相符，不影响正确性 |
| PRO-R06 | 性能声明 | 在固定机器、文件集、冷热启动下测浅/深 probe | 发布 p50/p95、样例大小、target、版本和命令；“毫秒”仅在覆盖数据范围内使用 |
| PRO-R07 | 集成表面 | CLI、JSONL、Node、浏览器 Worker、MCP 执行等价样例 | schema 与核心语义一致；批处理错误隔离和 Worker 不阻塞 UI 的证据可复核 |
| PRO-R08 | 平台与供应链 | macOS/Linux/Windows 按发布清单安装，对同一冻结样本执行最小探测 | 每个平台均能启动且最小语义结果一致；R03—R07 负责完整功能套件；notarization/AuthentiCode 缺失按 release notes 披露 |
| PRO-R09 | 安全报告 | 验证 SECURITY/GitHub Advisories 私密提交路径 | 私密入口可用，公开 Issue 不要求机密样例 |

## 签核规则

PRO-R02、R03、R04 为 P0。任何新增格式或 target 必须连同 schema、限制、样例与性能回归一起签核。
