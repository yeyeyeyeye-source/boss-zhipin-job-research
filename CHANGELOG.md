# Changelog

## v2.7.0 (2026-08-10)

### 新增
- Strategy 任务改为单页流水线：每次只抓一页列表，逐个完成该页详情和 AI 判断后才决定是否请求下一页
- 断点恢复优先清理 SQLite 中已有的详情与 AI 积压；重复页仍推进保存的页码游标，不会提前结束后续页面

### 安全
- BOSS 列表和详情请求继续保持单通道串行，不新增网络并发；仅保留原有的单 AI Worker 与详情抓取重叠
- `code: 37`、HTTP 403/429、暂停、登录、AI 和 Run 预算停止规则保持不变，停止后不会请求下一页

### 修复
- 详情页不再仅因 URL 含 `_security_check` 或未来未知标记而误判访问受限；无明确受限证据且岗位身份、完整 JD 有效时正常保存。页面状态改为按 JD 外独立可见元素逐项判断，不依赖节点命名、不跨区域拼词；单独出现“安全校验”“滑块”“验证”等业务词不再触发页面风控判定

## v2.6.0 (2026-08-09)

### 新增
- 新增持久化 Strategy / Cycle / Run：一次 full Run 在所有城市间共享 500 次 BOSS 逻辑操作，崩溃恢复沿用同一 Run 与已用额度；下一次用户明确执行才获得新的 500 次本地预算
- 多城市按顺序进行每城最多 15 页 / 450 候选的深度扫描；预算耗尽后从原城市、页码、详情和 AI 断点继续
- 新增全局岗位/JD 目录，按平台岗位 ID 与规范化链接跨城市、跨 Run 去重；完整 JD 全局复用，AI 结果按策略隔离
- 每个受控收口的 Run 都冻结 SQLite 导出投影并生成独立累计 `RunNNN` Excel；历史 Run 可从冻结投影安全补导出，不吸收后续 Run 数据
- 新增显式 `--refresh`、`--confirm-access-restored`、`--ai-only`，以及不创建 Run 的纯本地 `boss-jobs export --run-id ...`

### 安全
- `code: 37`、HTTP 403/429 和明确访问限制仍立即停止所有后续 BOSS 操作并保存断点，只能由用户明确确认恢复；未加入自动重试、代理、多账号、验证码破解或请求指纹绕过
- AI-only Run 不会遮蔽既有访问限制确认门，也不会接管崩溃遗留的 full Run；未完成 Cycle 禁止用 `--refresh` 跳过断点
- 登录预检和列表第一页都在任何 BOSS 页面导航前先预留 Run 额度，确保 500/500 后的下一次受控操作在网络访问前停止
- 在线城市码回退同样预留 Run 请求额度，并把 code 37、HTTP 403/429 明确传播为访问限制
- Excel/CSV 导出会转义公式式文本；只有 `https://www.zhipin.com/...` 岗位链接才设置为可点击超链接

### 修复
- 重建历史 Run 不再把 `latest_output_path` 倒退到旧文件；默认复用和纯导出会以最新 Run 为准并修复旧版本遗留的错指针
- Strategy Run 在输出目录、写入、校验或发布阶段发生已知导出异常时都会把 `export_status` 记为 `failed` 并保存原始错误；清理失败不再覆盖已有导出错误，意外程序错误与中断仍向上抛出，Run 主状态与已冻结的 canonical 数据保持不变

### 发布整理
- 补充当前架构、私有运行数据和可复现依赖说明；公开仓库不包含数据库、岗位结果、日志、Chrome Profile、真实密钥或本机运行交接
- 新增 GitHub Actions 门禁，覆盖 Python 3.10/3.12、Ubuntu/Windows、全量测试、语法检查、锁文件和 wheel 构建
- 补齐 SQLite 变体与根目录 JSON/CSV 岗位结果的忽略规则，避免误提交私有运行数据

## v2.5.x 及更早的未发布变更

### 新增
- v2.5.0 Codex-first Skill：自然语言需求先展示简短确认方案，确认前不访问 BOSS；新增 `boss-jobs` 确定性入口，多城市串行、每城详情抓取与单 AI Worker 并行
- 任意确认目标岗位可依据完整 JD 返回匹配、不相关或待人工确认；数据库保存判断理由与置信度，Excel 可追加“待人工确认”工作表
- 城市 `AI产品运营` 任务改为完整 JD 保存后立即逐岗位 AI 解析；不相关候选标记为 `irrelevant` 且不导出，15 页 / 450 候选仅作为扫描上限，不触发合格数量补采；访问限制仍立即停止并等待手动恢复
- v2.4.0 全国 `AI运营` 合格数量门禁：完整 JD 通过一次 AI 请求同时完成相关性审核与职责/要求/加分项总结，只有合格岗位计入目标 50；不相关候选标记为 `irrelevant` 并保留去重，页面耗尽或无新增且不足目标时进入 `incomplete`
- 全国任务只保存城市名，详情地址不再覆盖列表城市；Excel 改为只导出合格岗位的严格 7 列格式，三类摘要按编号换行，无加分项显示“无”
- Streamlit 默认任务更新为 `AI运营 / 全国 / 10 页 / 50 条`，状态面板新增合格岗位和不相关数量
- 采集任务新增 10 条验证、20 条稳定性、50 条扩容、100 条批量和自定义数量模式；页数仍由用户单独指定，历史任务可原地扩大目标并把已保存岗位计入总数
- SQLite 岗位新增规范化链接身份，与 `job_id` 共同去重；旧库启动时无损补充字段，异常遗留的无租约 `processing` 记录也会恢复为 `pending`
- 列表 API 与详情流程统一识别 `code: 37`、HTTP 403/429 及限制提示；命中后立即停止后续网络步骤、保存进度并进入 `waiting_for_access`，仅由用户手动恢复
- 详情请求之间增加可配置的串行间隔和随机抖动（`BOSS_NETWORK_INTERVAL_MIN/MAX`），不包含代理、多账号或验证绕过逻辑
- `Collector.run_existing(task_id, token)` 可只处理已经写入任务的候选岗位，不再次请求列表；访问受限时仍保存断点并等待用户手动恢复
- v2.3.0 本地 Streamlit 岗位采集程序：新增 SQLite 任务/岗位持久化、独立 worker、单实例租约与心跳、异常恢复、协作式暂停/继续和历史任务状态面板
- 新增 OpenAI 兼容 JD 解析、薪资/岗位类型规则解析和 AI-only 重试；AI 未配置或失败时保留完整岗位与原始 JD，并进入 `waiting_for_ai`
- 新增严格 11 列 Excel 导出，支持冻结首行、筛选、列宽、换行和可点击岗位链接；失败记录同样导出
- CDP 核心新增可复用的 `fetch_list_page` 和 `fetch_job_detail`，原 CLI 行为保持不变
- 详情/列表结果新增独立字段 `boss_active_status`（如「今日活跃」「在线」）：列表兼容 `activeTimeDesc` 与 `bossOnline`（仅在线时映射为「在线」）；详情页从招聘者卡片解析更细粒度状态并优先保留；JD 正文仍剔除该行，不混入描述
- 新增 `--stop-chrome` 命令：抓取/分析完成后关闭 BOSS 专用 CDP Chrome（按 user-data-dir 精准匹配隔离 profile，不碰主 Chrome）；抓取命令新增 `--close-chrome` 选项，正常结束后自动收尾（默认关闭，异常退出不触发以保留登录态）。复用已有 `stop_cdp_chrome` 的安全匹配逻辑，补齐进程关闭/收尾链路的单元测试。（#26）
- 城市码表外置为 `data/city_codes.json`（全量 300+ 城市，覆盖一二三四五线），新增 `--list-cities [关键词]` 命令查看支持的城市；`resolve_city` 查询链改为「本地静态码表 → 运行时拉 BOSS 接口 → 9 位裸码兜底」。城市码表打进 wheel，`pip install` 用户也可用。（#24）

### 修复
- v2.5.1 列表任务新增安全的下一页游标，恢复时不再重放已完整处理的历史页；默认 API 路径改用非搜索同源上下文，避免真实搜索第一页与显式 WAPI 的双重列表获取。页内暂停、写入异常或访问限制仍保留当前页且不自动重试
- Codex Skill 任务持续刷新单实例租约；访问预检受限时仍处理已保存 JD，AI 失败后不再调用已排队岗位；多城市导出按岗位身份去重，并以新文件名原子写入避免覆盖旧结果
- `--check` 与 worker 启动前登录检查改为先初始化真实搜索结果页，再从同一页面上下文执行单次 wapi 探测；避免首页直连探测出现与真实搜索页不一致的 `code: 37`，同时保留明确访问限制立即停止且不自动重试的语义
- 暂停后继续采集会把 SQLite 中已有岗位键传回列表核心，跨 worker 恢复时重复岗位不再占用剩余数量上限；成功列表/详情会刷新短时登录判断，避免立即重复探测触发风控
- Windows 独立 worker 强制使用 UTF-8 写日志，避免重定向日志在 GBK 环境下出现乱码
- Windows GBK 控制台遇到 emoji 时不再抛出 `UnicodeEncodeError`；带空格或引号的 `--user-data-dir` 能被正确解析，专用 Chrome 仍按 profile 精确匹配
- 详情结果校验请求岗位 ID 与最终 URL，错位页面标记失败；标题和实际地址优先采用详情页值并以列表数据兜底
- 城市解析先执行本地及在线码表的正反向映射，再接受未收录的 9 位裸城市码；未知城市名现在会在抓取前明确报错退出。在线城市接口同时校验业务 `code`，不再把 `code: 35` 等风控响应静默当作空码表
- 登录探测识别 BOSS 风控码 `code: 37`「您的环境存在异常」为限制状态（RESTRICTED），并对未知风控码按 message 关键字（环境存在异常、访问频繁、安全校验等）兜底识别；避免已登录但被风控/限流的用户被误判为「登录探测响应异常」而无法继续。（#33）
- 登录探测改为区分可用、未登录、限制、空结果和响应异常；每轮仅请求一次并采用有上限的退避等待，`code: 31` 等明确限制会立即停止。探测请求现已纳入全局请求预算，CLI 不再把风控或异常统一提示为未登录。（#31）
- 登录检查、列表/详情抓取和 smoke test 的临时标签页统一在后台创建，仅人工登录页置前，避免自动流程抢占前台焦点（#28）
- 详情页 JD 改为只提取“职位描述”区，并在登录墙、导航页或过短正文出现时拒绝写入，不再把整页 `body`、招聘者信息、公司介绍和推荐职位当作 JD
- 同步 BOSS 当前 `city.json` / `condition.json` 映射，修正城市码以及薪资、经验、学历筛选枚举漂移，并在内置城市表未命中时自动加载 BOSS `cityGroup.json` 支持更多城市中文名
- `scrape_details` 最终保存改用 `os.path.dirname(path) or "."`，`--detail-output` 传不带目录的裸文件名时不再抛 `FileNotFoundError`（与循环内及其它写文件处保持一致）
- 修正城市码：天津 `101030100`、沈阳 `101070100`（原均误用 `101060100`）
- `require_runtime_dependencies` 缺失依赖时同时提示 uv 和 pip 安装方式
- `--merge` 现在会合并旧详情并落盘到 `--detail-output`（之前只合并列表，详情丢失）
- API URL filter 改用 `urlencode`（原字符串拼接，filter 值含特殊字符会出错）

### 变更
- CLI 与 Streamlit 单次最大抓取页数由 10 页调整为 15 页；全局 500 次 API 请求预算和访问限制立即停止规则保持不变
- 平台支持声明更新为 Windows + macOS + Linux；新增 Windows GBK、路径解析和主 Chrome 保护回归测试
- `pyproject.toml` 删除空的 `[csv]` extra（csv 是标准库）
- SKILL.md 脚本路径解析改用 Python `os.path.realpath`（macOS 自带 `readlink` 无 `-f`）

### 新增
- `scripts/job_summary.py` 抓取后摘要脚本：读取已有 JSON，输出岗位聚合摘要和求职材料优化提示词
- `boss-summary` 命令行入口，便于打包安装后直接运行摘要脚本
- 抓取后摘要测试：覆盖 JSON 加载、聚合维度、提示词输出和项目边界
- 版本号一致性测试：校验脚本、pyproject.toml、SKILL.md、README.md 四处版本同步
- CONTRIBUTING.md 贡献指南

## v2.0.0 (2026-06)

### 新功能
- `--check` 环境检查（CDP 连通性、依赖、登录态）
- `--setup-chrome` 一键启动 Chrome CDP（持久隔离 profile）
- `--copy-login-state` 手动导入主 Chrome 的 Local State + Cookie 相关文件到隔离 profile
- `--reset-chrome-profile` 重建 BOSS 专用 Chrome profile
- `--setup-chrome` 默认等待 BOSS 登录完成，并确认接口返回明文薪资
- `--no-wait-login` / `--login-timeout` 控制 setup 登录等待
- 默认抓取结果保存到 `~/.boss-zhipin-scraper/job-result`
- 未传 `--city` 时默认搜索上海
- `--format csv` 同时导出列表 CSV 和详情 CSV
- `--merge` 合并多次抓取结果（去重）
- `--cdp-port` 自定义 CDP 端口（默认 9222）
- `--smoke-test` 用真实 Chrome/CDP 跑一次搜索 API smoke test，不写结果文件
- `--allow-dom-fallback` 显式允许 API 失败时降级 DOM 提取
- `--version` 查看版本号
- 登录态检测：未登录时给出明确提示
- 分析报告技术词动态提取（不再硬编码）
- 进度显示：`[2/3 页, 45/90 条]`

### 改进
- CDP WebSocket 消息过滤 + 超时重试（不再无限卡死）
- 详情页写入去重（中断重跑不重复）
- 请求频率保护（最多 10 页，全局 500 次上限）
- 清除所有 bare except，改为具体异常类型
- API 路径提取为常量，方便维护
- DOM fallback 标记为 deprecated
- DOM fallback 默认关闭，避免把字体反爬后的薪资写进结果
- API 错误行不再被当成职位数据处理
- 详情输出保留 `job_id`、`job_link` 和 `salary_source`
- 详情页访问会带上列表 API 返回的 `securityId` / `lid` 上下文
- `--input ... --analysis --no-detail` 会从 `--detail-output`、同目录同时间戳详情文件、默认结果目录最新详情文件中加载详情
- 登录态检测改为多关键词、多城市 probe，但仍要求接口返回明文薪资
- Linux / Windows 平台支持（Chrome 路径 + 隔离 profile）
- pyproject.toml 版本锁定依赖

### 安全
- 默认不软链接、不复制主 Chrome profile；首次启动也不自动导入主 Chrome 登录态，避免影响 Gmail/GitHub 等主浏览器登录态
- API URL 可配置（`API_JOB_LIST_PATH` 常量）

## v1.0.0 (2026-06)

### 初始版本
- Chrome CDP 抓取 BOSS直聘职位列表
- API 明文薪资（绕过字体反爬）
- 详情页 JD 抓取 + 技能标签提取
- 增量写入（异常退出不丢数据）
- 分析报告（薪资分布、经验要求、简历建议）
- 多维筛选（规模、融资、薪资、经验、学历、行业）
