# Mac 原生监控：权限准备与可信边界

本机检查已发现：没有 `_deckprobe_accept` 测试身份，且 `sudo -n` 不能取得管理员权限。`eslogger` 还要求调用终端的“完全磁盘访问”。这些需要操作者在 macOS 中完成授权，不能由脚本绕过。

## 操作者可执行的准备

先阅读 `monitor_macos.py`。以下第一条只创建一个隐藏、无登录密码、无登录 shell 的普通测试身份，不赋予管理员组权限。

```sh
sudo python3 benchmark/acceptance/monitor_macos.py --provision-user
```

在系统设置 → 隐私与安全性 → 完全磁盘访问中，为实际执行监控的终端授权。然后选择一个不存在的输出目录运行可行性探针：

```sh
sudo python3 benchmark/acceptance/monitor_macos.py --output /private/tmp/deckprobe-monitor-probe-001
```

探针仅使用不含文档内容的控制流量：文档测试地址、`.invalid` DNS、回环、代理连接，以及 `/usr/bin/true`。不会扫描源文件。PF 使用独立 `com.apple/deckprobe-acceptance` 锚点与引用计数令牌，不替换系统主规则。占用中的锚点会拒绝运行。正常结束或异常会停止子进程并清理自身规则。

## 为什么探针不能自动签核

拒绝连接可能来自目标不存在，不等于防火墙成功。DNS 可能由系统服务代发，UID 规则并不构成完整沙箱。`eslogger` 输出受系统版本影响；pktap 抓包也不能单独证明没有 socket 尝试。因此探针只提供原始能力证据，明确为 BLOCKED，不生成伪造的 R02 通过凭据。

完整 R02 需要同一次执行内的：前后正控、目标进程树、IPv4/IPv6/DNS/回环/代理限制和归因、文件事件、采集完整性及规则清理；全部绑定 run ID、资产哈希和语料哈希。`security.validate_session` 实现该证据契约和否决检查，但普通 JSON 文件不能解除私有扫描禁令。

授权后先检查探针的真实结果。如果系统 DNS 或代理无法按进程可靠约束，应接入经过验证的 Network Extension/专用 runner 采集器；不要把 PF 探针升级标成 PASS，也不要用已弃用的 sandbox-exec 作为唯一长期依据。该环境能力是本方案当前明确的阻塞条件。

自动化不会执行 `sudo` 密码输入，不会保存管理员密码，不添加宽泛 NOPASSWD 规则。需要长期无人值守时，只有在采集路径验证成功后，才部署固定入口、限定操作的辅助服务。
