"""Human-readable test protocols, separate from verdicts and document GT.

These explanations describe the frozen evaluator below. They do not evaluate,
approve answers, or retroactively add checks to a historical run.
"""
from __future__ import annotations

VERSION = 1
SUPPORTED = {
    'runner.py': '12544fd0ac1110805515b6061c9296dbf0bf036b5170c3f7e73b3bd6caee4ca8',
    'contracts.py': 'aa7bfe77ca6f1ebb6d1817629610b5a498d072359cf7aa57b319dbc53cb9a9b2',
    'config/policy.json': '04e60675926fea747b935c7a181a78ed14f63c2ba050247c47f2b4455095d5e5',
    'security.py': '52ab62b4017dff9537ea6eb53ccefe978973e9f820074e4941cfcbae5886e40b',
    'adapters/runtime.mjs': 'a9a87a459a8a9d2aa8f2c4bc4fe1bae291ae096ee891cbd85ffb2bc8333c4334',
    'adapters/performance.mjs': '397a8a1e8c2ba651668e1a3dcfbeeb5a8c21b80d728c726791d7172c4e19d26d',
    'adapters/paired-performance.mjs': 'ddc3a49132f795267a43b73ec72b88509ae296f83192ec7a9b073a4c4809cc17',
    'coverage.py': 'b7bd99f460c02cd86f37dc907354e8b8353e760e7de9325050861e898d928df2',
    'docs/handbook.md': '16926e968c6826d693f83899e2e556bbd06350d674c68c792f932e40d91d47b2',
    'supply_evidence.py': '14240eb78dc8ae8d319baabd6bd82644fde7e86c94d6560e622ecd35b5a44b36',
    'github_ci.py': '5209ed9abae51720e1dfbe97b06cc36026c9793f8ab54f36fc907a87a9c85c24',
    'linux_security.py': '3254be83f0d53e0cb4982d1daf02bda790996077eff462c274a86f69e8fe2c63',
}
LEGACY = {'runner.py': {'ae3af454936e5367d7da5801c60ef482956ee8f0506f1e380838e17daace8d81', '82cdca1eb54b602d4d4605c26f165b1876876550fe849f2b2a8e44b89e4fd6bf', '9cda58512fa28f9ff23f98f1bf3742f717ff2c9ac237201266d9f1b341e6a0b2'}}


def protocol(kind, question, method, criteria, basis, limitation='', **extra):
    return dict(version=VERSION, kind=kind, question=question, method=method,
                criteria=criteria, basis=basis, limitation=limitation, **extra)


def explain(row, policy, evidence):
    key = row['id']
    actual = row.get('actual')
    data = actual if isinstance(actual, dict) else {}
    answer = row.get('answer')
    runner = [('implementation/runner.py', 'run() 中对应检查；本轮冻结实现')]
    contract = [('implementation/contracts.py', 'report_issues / normalize / evaluate_answer')]
    rule = [('implementation/config/policy.json', row['requirement'] + ' 的证据要求与运行参数')]
    if answer:
        c = answer['check']
        conditions = {
            'target': ['目标状态为 resolved 或 estimated，必须含 value。', 'value 的类型和值均与下方答案相同；缺失、null、0 和 false 分别处理。'],
            'status': ['指定 target 的 status 与下方预期状态相同。'],
            'error': ['整体 status 为 error，error.code 与下方预期错误码相同。'],
            'allowed_paths': ['指定 target 的 path 属于下方允许集合。'],
            'cost_ceiling': ['各成本字段为非负整数，且不超过下方对应上限。'],
        }
        return protocol('文档答案核对', answer['question'],
                        ['对绑定哈希的文件执行：' + ' '.join(answer.get('options', [])),
                         '读取 ' + c.get('target', c['type']) + '，按该条答案的检查类型比较。'],
                        conditions.get(c['type'], ['按归档答案中的 check 比较。']), contract,
                        ('该私有样本本轮未交给待测系统，因此没有实际值，不能比较或形成产品结论。' if actual=='Private scan requires live isolation'
                         else '答案已经人工审核；本轮实际值一致，因此计为正式通过。' if row.get('approval')=='approved' and row.get('status')=='passed'
                         else '答案已经人工审核；本轮实际值不一致，因此计为正式失败。' if row.get('approval')=='approved' and row.get('status')=='failed'
                         else '答案尚未人工审核；当前实际值仅作为诊断观察，不计入正式通过或失败。'),
                        expectedLabel={'status': '预期 target 状态', 'error': '预期错误码', 'allowed_paths': '允许的解析路径',
                                       'cost_ceiling': '各成本字段上限'}.get(c['type'], '预期值与数据类型'), showExpected=True)
    if row.get('details', {}).get('audit'):
        audit = row['details']['audit']
        questions = {
            'release_checksums': '下载的每个发布附件是否与发布方记录一致？',
            'release_provenance': '每个平台包是否确实由指定仓库、提交和 tag 构建？',
            'release_licenses': '各组件声明什么许可证，实际包内是否带有对应文件？',
            'npm_signatures': '这份已安装依赖树中的包，注册表签名是否全部验证成功？',
        }
        return protocol('发布资产核对', questions.get(key, row['title']), [audit['scope']],
                        ['按下方每个组件、每个字段的预期值和实际证据核对；缺失证据单独列出。'],
                        [('implementation/supply_evidence.py', 'collect()；逐字段的独立证据链接见下方')])
    if key == 'release_version':
        return protocol('发布版本核对', '本次运行的二进制版本是否等于冻结的发布 tag？',
                        ['执行已下载发布包的 --version。'],
                        ['退出码为 0；去掉输出首尾空白后，版本文本等于下方冻结值。'], runner,
                        showExpected=True, expectedLabel='由发布 tag 得到的版本文本')
    if key == 'third_party_disclosure':
        return protocol('人工材料审阅', '第三方依赖是否逐项对应到应随包提供的披露材料？',
                        ['需要先建立依赖清单与许可证、署名和 NOTICE 的对应表，再逐项审阅。'],
                        ['每项依赖有可复核的披露依据；未完成对应表和审核时不能签核。'], rule,
                        '本轮只完成许可证文件检查；未完成第三方披露完整性审阅。',
                        observed='尚无逐项披露核对表或审核结论。', criteriaLabel='完成这项审阅需要')
    if key == 'live_security_monitor':
        env = evidence.get('evidence/doctor.json', {})
        return protocol('安全环境验证', '能否发现并阻止验收进程的联网、非预期执行和文件修改？',
                        ['扫描前用控制程序触发联网、子进程和标记文件事件，验证限制和采集都有效。',
                         '在隔离身份下运行被测程序，关联进程树、网络和文件事件；扫描后再做一次相同自检。'],
                        ['IPv4、IPv6、DNS、回环和代理路径均有约束与归因证据。',
                         '前后控制事件都可见；无日志中断、丢失或无法解释的监控盲区。',
                         '被测程序无禁止行为尝试；即使访问被拦截，尝试本身仍要判为异常。'],
                        [('implementation/security.py', 'validate_session() 的会话证据约束'),
                         ('implementation/docs/handbook.md', 'PRO-R02 与一票否决项'), *rule],
                        '本轮只做环境预检，尚未执行上述完整安全实验。安装工具或空日志都不能作为通过证据。',
                        criteriaLabel='完整安全实验的通过条件', observed='环境预检受阻；未获得本轮扫描前后自检和连续监控证据。',
                        observedFields=[['受限管理员入口', '可用' if env.get('noninteractiveAdmin') else '不可用 / 未证明'],
                        ['专用低权限身份', env.get('testIdentity') or '未配置'],
                                        ['完全磁盘访问与前后控制实验', '尚未证明'],
                                        ['私有文件扫描许可', '允许' if env.get('privateScanAllowed') else '禁止']])
    if key == 'linux_live_isolation':
        return protocol('Linux 安全边界实验', 'Ubuntu x64 验收进程是否在可观测的断网环境中扫描，且没有联网、派生程序或修改输入？',
                        ['创建独立 network namespace 和 veth 路由，使用 nftables 计数并阻断非回环流量。',
                         '扫描前后分别触发 IPv4、IPv6、DNS、代理、回环、子进程和标记文件控制事件。',
                         '用 strace 关联产品的网络、进程和文件系统调用，并在扫描前后核对输入 SHA-256。'],
                        ['前后控制事件全部可见，且 nftables 丢弃计数增长；采集记录连续。',
                         '产品没有 IPv4/IPv6 connect、非预期 execve、输入哈希变化或未解释的 nftables 命中。',
                         'namespace 和 veth 清理成功；任一监控能力无法证明时为 BLOCKED。'],
                        [('implementation/linux_security.py', 'run_security()；控制实验、采集、判定与清理'), *rule],
                        '结论只适用于本轮 Ubuntu x64 hosted runner、公开 CI 样本和原生 CLI 扫描。',
                        observedFields=[[{'controlsVisible':'控制与采集完整','forbiddenConnects':'产品网络尝试',
                                          'unexpectedExecutions':'非预期派生程序','modifiedInputs':'被修改输入',
                                          'productDropPackets':'产品流量的 nftables 丢弃计数','runs':'扫描样本数',
                                          'scope':'结论范围'}.get(k,k),v] for k,v in data.items()])
    if key == 'publication_wording':
        return protocol('人工文案审阅', '本版安全相关文案，是否超出了已有样本和监控证据能支持的范围？',
                        ['需要对照前一版，列出新增或变更的安全描述，并关联其支持证据。'],
                        ['每条描述明确验证范围和限制，不把有限测试写成完整安全保证。',
                         '留存原文、差异、对应证据和人工审核结论。'], rule,
                        '仅有 sourceCommit 能定位版本，不能证明文案已被审阅。',
                        criteriaLabel='完成这项审阅需要', observed='本轮只记录了源提交；尚未归档文案差异和逐条审核结论。',
                        observedFields=[['待审源提交', data.get('sourceCommit', '未记录')]])
    if key == 'private_sources_protected':
        return protocol('验收流程保护', '安全监控尚未就绪时，验收器是否跳过私有样本？',
                        ['根据样本清单的 private 标记拦截扫描；本轮事实检查遇到私有样本即阻塞。'],
                        ['私有输入不传给被测程序。下方数字统计需保护的私有样本，不是产品通过的文件数。'], runner,
                        '这是验收器自身的跳过策略记录；未采集独立进程事件，不能据此声明 DeckProbe 安全。',
                        observed=f'清单中有 {actual} 份私有样本，本条记录的是保护范围。',
                        observedFields=[['私有样本数', actual], ['本条证据层级', '验收器流程记录；无独立监控事件']])
    if key == 'complete_declared_coverage':
        return protocol('覆盖缺口核对', '每个声明的格式、target 和必需场景是否都有已审答案与执行证据？',
                        ['按声明矩阵计算设计、审核、执行、通过覆盖；分别保留缺失场景。'],
                        ['声明矩阵经过审核；每个适用组合有绑定样本的已审答案和执行证据。'],
                        [('implementation/coverage.py', 'coverage() 的覆盖分母与关联规则'), *rule],
                        '诊断中与草案一致，不会增加正式已审覆盖。',
                        observed='覆盖尚未完成；下面按阶段显示数量与缺口。',
                        observedFields=[[{'total':'声明组合总数','designed':'已设计','approved':'已审核','executed':'正式执行','passed':'正式通过','declarationReviewStatus':'声明矩阵审核状态'}.get(k,k), v] for k,v in data.get('coverage',{}).items()],
                        observations=data.get('gaps', []))
    if key.startswith('schema_'):
        return protocol('输出契约校验', '这份输出的结构、target 状态、置信度与证据字段是否自洽？',
                        ['用该发布版本的 JSON Schema 校验原始输出，再检查状态与字段间的关系。'],
                        ['输出符合 schema；完整探测报告中 target 键与 canonical 名称一致。',
                         'resolved / estimated 有 value、path、source；置信度映射为 none=0、low=0.4、medium=0.7、high=0.95、exact=1。',
                         'unresolved_targets 与各 target 状态一致，整体 partial / ok 与未解决项一致。',
                         '三个成本字段均为非负整数；错误输出中的 exit_code 与进程退出码一致。'], contract,
                        '这里只验证输出契约。error 输出校验 schema 和退出码后结束；values 视图只校验 schema。文档事实由对应 GT 项核验。',
                        observed=('已执行 JSON Schema、状态/字段关系、置信度映射、成本字段和退出码校验；未发现契约违规。'
                                  if isinstance(actual,list) and not actual else
                                  f'已执行输出契约校验，发现 {len(actual)} 条违规。' if isinstance(actual,list) else '查看原始校验记录。'),
                        observations=actual if isinstance(actual,list) and actual else [], actualLabel='契约校验结果')
    if key in {'optional_required_semantics', 'optional_shared_cost', 'paths_oracle'}:
        method = [
            '基准请求：只请求必需字段 slide_count。',
            '变体请求：仍请求 slide_count，同时把 orientation 和 aspect_ratio 声明为“有现成结果才返回”的 optional 字段。',
            '两条命令独立执行，再比较基准请求和变体请求；左栏是基准请求的实际输出，不是人工 GT。',
        ]
        if key == 'paths_oracle':
            records = evidence.get('evidence/paths.json', {}) if isinstance(evidence, dict) else {}

            def request_summary(name):
                record = records.get(name, {}) if isinstance(records, dict) else {}
                report = record.get('report', {}) if isinstance(record, dict) else {}
                process = record.get('process', {}) if isinstance(record, dict) else {}
                target = report.get('results', {}).get('powerpoint.slide_count', {})
                execution = report.get('execution', {})
                cost = execution.get('actual_cost', {})
                error = report.get('error', {})
                parts = [f"整体 {report.get('status', '未记录')}"]
                if target:
                    value = f"，值 {target['value']}" if 'value' in target else ''
                    parts.append(f"slide_count {target.get('status', '未记录')}{value}")
                    parts.append(f"路径 {target.get('path', '未记录')}")
                if cost:
                    parts.append('自报成本：读取 {physical_bytes_read} B / 展开 {expanded_bytes} B / 随机读 {random_reads} 次'.format(**cost))
                if error:
                    parts.append(f"错误 {error.get('code', '未记录')}，退出码 {process.get('exitCode', '未记录')}")
                return '；'.join(parts)

            observed = [[label, request_summary(name)] for name, label in [
                ('required', '只请求 slide_count'),
                ('optional', '追加 optional 字段'),
                ('no_piggyback', '禁止顺带返回'),
                ('exact', '要求 exact 置信度'),
                ('budget', '读取预算限制为 1'),
            ]] if records else []
            return protocol('路径规则审核', '不同请求约束会选择什么解析路径，并产生什么成本和预算行为？',
                            ['分别执行：只请求必需字段、追加 optional、禁止 piggyback、要求 exact、设置极小读取预算。',
                             '记录每次选择的 path、target 状态和值、产品自报成本、整体状态、错误码和进程退出码。'],
                            ['先为每种请求审核允许路径或路径约束；路径可以是允许集合，不要求写死唯一实现。',
                             '审核成本的计量定义和允许范围，并确认预算超限时应返回的状态、错误码和退出码。',
                             '上述答案冻结后，再用本轮记录逐条比较；目前尚不能判定通过或失败。'], runner,
                            '本轮已经真实执行五组请求，但缺少已审的路径、成本和预算答案，所以状态是 REVIEW。它不是“执行结果通过”。',
                            criteriaLabel='形成正式结论前还缺什么',
                            observed='已取得五组请求的诊断记录；下列内容是待审核事实，不是已通过答案。',
                            observedFields=observed, actualLabel='五组请求的实际记录')
        cost = key == 'optional_shared_cost'
        return protocol('请求差异比较', '追加 optional 字段后，' + ('产品自报的读取成本是否增加？' if cost else '必需字段 slide_count 的输出是否被改变？'),
                        method, ['两次请求的 physical_bytes_read、expanded_bytes、random_reads 均为整数，且逐字段相等。'] if cost else
                        ['两次请求中 powerpoint.slide_count 的完整结果对象存在且相等，包括值、状态、置信度、路径和来源。'], runner,
                        ('本轮两次请求的三个自报成本均为 1927 B、379 B、7 次，因此这条差异检查通过。'
                         '它只证明在这个样本和这两条命令中没有增加产品自报成本，不代表操作系统 I/O，也不证明 optional 字段成功返回。') if cost else
                        ('本轮两次请求的 slide_count 都是 unknown，且路径、来源和置信度完全相同。'
                         '因此“追加 optional 没有改变必需字段”通过；它不能证明页数已正确求出，也不能证明 optional 字段成功返回。'),
                        expectedLabel='基准请求的实际' + ('自报成本' if cost else ' slide_count 输出'),
                        actualLabel='追加 optional 后的实际' + ('自报成本' if cost else ' slide_count 输出'), showExpected=True)
    if key == 'background_performance':
        config = policy.get('performance', {})
        warm, samples = config.get('warmup','未记录'), config.get('samples','未记录')
        return protocol('性能测量', '这些文件在不同探测级别和运行方式下，需要多长时间？',
                        [f'固定语料分 header / metadata / deep；每种配置预热 {warm} 次、记录 {samples} 次。首次初始化通过新进程、新页面或新 Worker 重建后重复采样。',
                         '分别记录新进程、JSONL、Node、WASM 和 Worker；保留每个原始测量点，再计算 p50 / p95。'],
                        [f'只有取得 {samples} 次且全部成功的配置才展示分位数；失败和未完成配置仍保留。',
                         '本项只作后台趋势观察，没有预设的“正确毫秒数”，也不据此签核对外性能声明。'], runner + rule,
                        '后台负载和文件系统缓存未受控；新进程不等于磁盘冷缓存。', criteriaLabel='测量结果如何使用',
                        observed=f'共 {data.get("configurations", 0)} 组配置，其中 {data.get("complete", 0)} 组完成重复采样；其他配置需分别查看原因。')
    if key == 'performance_pair':
        return protocol('GitHub 配对性能趋势', '同一 hosted runner 中，候选版相对前一正式版是否出现需要复核的延迟增长？',
                        ['新旧版本在同一 runner 交错运行；原生配置及 Node、浏览器、Worker 配置均预热后保留 30 个有效点。',
                         '首次初始化通过新进程、新页面或新 Worker 重建后重复采样；逐配置计算 p50 和 p95。'],
                        ['所有配置保留完整原始点且可比；缺失或删去慢样本为 BLOCKED。',
                         '相对增长至少 20% 且绝对增长至少 2 ms 时为 REVIEW，不直接否决发布。'],
                        [('implementation/github_ci.py', 'run_performance() 的配对、完整性与阈值判定'),
                         ('implementation/adapters/performance.mjs', 'JS、WASM、浏览器和 Worker 重复测量'), *rule],
                        '该结果只表示 GitHub runner 上的版本趋势，不支持绝对毫秒声明。',
                        observedFields=[[{'groups':'原生配置组数','comparisons':'比较项数','runtimeVersions':'运行时版本数',
                                          'blocked':'不完整配置数','alerts':'需复核项数'}.get(k,k),v] for k,v in data.items()])
    if key == 'formal_performance':
        return protocol('性能签核准备', '是否有足够证据支持某个明确范围的性能声明？',
                        ['需要在受控时段固定机器、软件环境、语料、运行方式与缓存状态，并独立重复测量。'],
                        ['每配置至少 100 次有效测量；保留失败和超时；每条对外声明指向具体测量范围。'], rule,
                        '本轮只有后台观察，未执行正式性能签核。', criteriaLabel='正式签核门槛', observed='缺少受控环境、足量样本和独立重复证据。')
    if key in {'native_install','npm_native_install'}:
        npm = key == 'npm_native_install'
        return protocol('本机启动检查', ('npm 安装的启动器' if npm else 'macOS ARM64 发布二进制') + '能否启动并返回正确版本？',
                        ['对冻结安装目录中的' + (' Node 启动器' if npm else '可执行文件') + '执行 --version。'],
                        ['退出码为 0，版本输出与冻结版本一致。'], runner,
                        '这里只执行本机版本启动检查；不代表其他平台或全部安装方式都经过验证。',
                        observed=str(actual).strip(), showExpected=npm, expectedLabel='原生发布包的版本输出')
    if key == 'platform_matrix':
        return protocol('平台执行覆盖', '每个发布平台是否都有相应机器上的安装与运行证据？',
                        ['在各平台 runner 使用同一冻结发布组合、样本与规则执行验收。'],
                        ['下方每个平台都有实际执行证据；只下载到包或验证哈希不算该平台已运行。'], rule,
                        '本轮只能说明本机执行范围。', showExpected=True, expectedLabel='必须实际运行的平台',
                        observedFields=[['本轮执行平台', data.get('executed',[])], ['缺少 runner 的平台',data.get('missing',[])]])
    if key.startswith('platform_'):
        environment = data.get('environment', {}) if isinstance(data, dict) else {}
        version = data.get('version', {}) if isinstance(data, dict) else {}
        smoke = data.get('smoke', {}) if isinstance(data, dict) else {}
        return protocol('发布平台启动检查', '该平台的正式发布资产能否在匹配架构上安装、启动并返回最小 JSON？',
                        ['从冻结 release 下载该平台资产和独立 checksum，在对应 hosted runner 或同架构 Alpine 用户空间解压。',
                         '核对操作系统、CPU 架构和 musl loader，再执行 --version 与最小 document.format 探测。'],
                        ['资产摘要与 release 记录和 checksum 文件一致；runner 的系统、架构及 libc 与平台 ID 相符。',
                         '--version 等于冻结 tag；最小探测退出码为 0 且 stdout 是 JSON 对象。'],
                        [('implementation/github_ci.py', 'platform_smoke() 的资产、环境与启动校验'), *rule],
                        '这是平台安装与基础启动证据，不重复执行 R03—R07 的完整功能套件。',
                        observedFields=[['发布资产',data.get('asset') if isinstance(data,dict) else actual],
                                        ['实际系统 / 架构',f'{environment.get("system","未记录")} / {environment.get("machine","未记录")}'],
                                        ['环境是否匹配',environment.get('matches')],['版本退出码',version.get('exitCode')],
                                        ['探测退出码',smoke.get('exitCode')]])
    if key == 'private_reporting_enabled':
        enabled = data.get('privateReporting',{}).get('enabled')
        return protocol('仓库设置核对', '目标仓库是否启用了 GitHub 私密漏洞报告？',
                        ['读取目标仓库的 private-vulnerability-reporting API，并归档响应和检查时间。'],
                        ['响应中的 enabled 必须为 true；字段不可取得则缺少证据。'], runner,
                        '该开关不证明当前账号能打开提交表单；表单访问另测。',
                        observedFields=[['仓库',data.get('repository')],['期望 enabled',True],['实际 enabled',enabled],['检查时间',data.get('checkedAt')]])
    if key == 'private_reporting_form':
        return protocol('认证入口验证', '使用实际访问身份，能否打开私密漏洞报告表单？',
                        ['需要登录后访问私密报告入口，记录访问身份、页面和检查时间；不提交报告。'],
                        ['能访问有效的私密提交表单；保留与目标仓库和身份绑定的页面证据。'], rule,
                        '本轮没有认证后的页面证据。', criteriaLabel='入口验证的通过条件', observed='尚未证明当前访问身份能打开表单。')
    if key == 'security_policy_entry':
        return protocol('安全策略入口核对', '发布提交是否包含与该 commit 绑定且可访问的 SECURITY.md？',
                        ['从冻结 release 的目标 commit 取得 SECURITY.md，并记录内容摘要和来源。'],
                        ['文件存在、来源 commit 与发布绑定且 SHA-256 可复核；公开入口与仓库实际设置一致。'],
                        [('implementation/github_ci.py', 'run_main() 的发布提交 SECURITY 快照检查'), *rule],
                        '文件存在只证明策略文本随版本发布；私密报告开关由相邻检查独立验证。',
                        observedFields=[[{'sha256':'SECURITY.md SHA-256','missing':'是否缺失','declaredEntries':'文档声明的私密报告入口',
                                          'matchesRepository':'入口是否指向本仓库'}.get(k,k),v]
                                        for k,v in data.items()])
    if '_parity_' in key:
        mode = key.split('_parity_')[0]
        return protocol('接口等价性', f'{mode} 与原生 CLI 对同一文件是否给出等价结果？',
                        ['用相同的 @summary,@security 与 metadata 请求分别执行，再校验 schema 并逐字段比较。'],
                        ['至少返回一份报告，且每份报告通过契约校验。',
                         '仅去除 input.source_kind/path/name 与 elapsed_ms；仅将扩展名、扩展名匹配和大小的允许来源文字作等价归一化。',
                         '其余值、状态、置信度、路径与证据语义均须保持一致。'], contract + runner,
                        'native 是接口比较基准；各接口一致仍不能代替独立 GT。MCP 默认解析与固定引擎分别记录。',
                        observed=f'本轮记录 {len(actual)} 条契约或等价性问题。' if isinstance(actual,list) else '查看接口执行记录。',
                        observations=actual if isinstance(actual,list) else [], baselineLabel='原生 CLI 的比较基准')
    if '_tools_' in key and key.startswith('mcp'):
        return protocol('MCP 工具与拒绝行为', 'MCP 是否暴露必需工具，并拒绝非法参数和越界路径？',
                        ['调用 tools/list，再分别发送非法参数请求和允许范围外的文件路径。'],
                        ['包含 probe、probe_batch、list_formats、list_targets。',
                         '非法参数和越界路径均返回 JSON-RPC error 或 result.isError。'], runner,
                        '该项只核验这两种拒绝行为，不代表所有参数边界都已覆盖。',
                        observedFields=[['发现的工具',data.get('tools',[])],['非法参数被拒绝',data.get('invalidRejected')],['越界路径被拒绝',data.get('outsideRejected')]])
    if '_schema_' in key and key.startswith('mcp'):
        return protocol('MCP schema 资源', 'MCP 提供的 schema 是否等于引擎发布版本的 schema？',
                        ['读取 MCP schema resource，解析 JSON 后与发布 schema 对象比较。'],
                        ['解析后的两个 schema 对象完全相同；下方是对象摘要哈希。'], runner,
                        showExpected=True, expectedLabel='发布 schema 对象摘要', actualLabel='MCP schema 对象摘要')
    if ('_batch_' in key and key.startswith('mcp')) or key == 'jsonl_error_isolation':
        mcp = key != 'jsonl_error_isolation'
        rows = data.get('reports',[]) if mcp else actual if isinstance(actual,list) else []
        statuses = [x.get('report',{}).get('status') if mcp else x.get('status') for x in rows]
        return protocol('批处理错误隔离', '一条坏文件请求是否会影响后续正常文件？',
                        ['依次提交正常文件、不存在的文件、同一正常文件；检查三个独立结果及顺序。'],
                        ['恰有 3 个结果；第 1、3 个不是 error，第 2 个是 error。',
                         'MCP 首尾文件路径须正确，首尾报告经允许归一化后相同。' if mcp else 'JSONL 首尾完整结果对象相同。'], runner,
                        '坏文件使用不存在的路径；这项不等于损坏、加密等所有异常文件均已隔离。',
                        observedFields=[['返回数量',len(rows)],['第 1 / 2 / 3 条状态',statuses]])
    if key.startswith('worker_responsiveness_'):
        idle = data.get('idleMaxMs')
        threshold = max(50, idle*3) if isinstance(idle,(float,int)) else None
        return protocol('页面响应实验', 'Worker 探测期间，页面心跳是否继续运行？',
                        ['先记录空闲心跳，再主动阻塞主线程作为对照，最后记录 Worker 探测期间的心跳间隔。'],
                        ['空闲最大间隔大于 0；主动阻塞对照至少 100 ms；Worker 至少记录 3 个心跳。',
                         'Worker 最大间隔不超过 max(50 ms, 空闲最大间隔 × 3)。'], runner,
                        '这是当前文件与运行时的心跳实验，不足以外推所有大文件或 UI 场景。',
                        observedFields=[['空闲最大间隔（ms）',idle],['主动阻塞最大间隔（ms）',data.get('blockedMaxMs')],
                                        ['本轮 Worker 允许上限（ms）',threshold],['Worker 最大间隔（ms）',data.get('workerMaxMs')],['Worker 心跳数',data.get('workerTicks')]])
    if key == 'mcp_deadline':
        return protocol('MCP 超时处理', '引擎超过时限时，MCP 是否返回明确的超时错误？',
                        ['将引擎时限设为 1 ms，使用压力样本执行 mcp-timeout 适配器，读取 probe 响应的 error.code。'],
                        ['错误码必须为 MCP_TIMEOUT。'], runner,
                        '本条只比较错误码，不据此证明所有取消和资源清理行为。', showExpected=True, expectedLabel='应返回的错误码')
    if key == 'integration_deep_coverage':
        return protocol('接口场景覆盖', '接口测试是否涵盖复杂文档、旧格式和 iWork 等代表性场景？',
                        ['需要把各家族的已审代表样本分别接入 CLI、Node、WASM、Worker 与 MCP。'],
                        ['所需家族与复杂场景均有已审样本、明确断言和对应接口的执行证据。'], rule,
                        '原归档的缺口文字尚未逐项细化，其中提到的超时需结合独立 mcp_deadline 项阅读；此汇总项仍保持原 BLOCKED。',
                        criteriaLabel='覆盖完成需要', observed='现有少量 PDF / OOXML 接口样例不足以证明完整场景覆盖。')
    return protocol('未细化的检查', row['title'], ['当前归档未提供可准确展开的操作说明。'],
                    ['请核对下方原始规则；不能由标题推断额外通过条件。'], [],
                    '该检查尚未有经过实现核对的说明，保留原值和原判定。', showExpected=True, expectedLabel='原始预期记录')
