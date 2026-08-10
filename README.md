# BOSS直聘爬虫 · 职位抓取工具 v2.6（Chrome CDP / Codex Skill）

> 🌐 English documentation: [README.en.md](./README.en.md)

![Python](https://img.shields.io/badge/python-3.10+-blue.svg)
![License](https://img.shields.io/badge/license-MIT-green.svg)
![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey.svg)
![Version](https://img.shields.io/badge/version-2.6.0-orange.svg)

一个轻量的 **BOSS直聘爬虫（spider / crawler / scraper）**：通过 Chrome DevTools Protocol 连接本地已登录的专用 Chrome，复用真实登录态调用 zhipin.com 搜索 API。既保留原有 JSON / CSV CLI，也提供 SQLite 断点续跑、AI 结构化解析、Excel 导出和 Streamlit 本地任务面板。

v2.5 同时提供 Codex Skill：先把用户的一句话解析为简短方案，得到确认后再执行；检索词不自动扩展，详情抓取与 AI 审核并行，任意目标岗位都按完整 JD 严格筛选。

> 📌 **一句话介绍**：不用 Selenium/Playwright，直接通过 Chrome DevTools Protocol 连接本地已登录的 Chrome，复用真实登录态调搜索 API，输出含明文薪资的 JSON/CSV，并生成薪资分布、技能词频和求职材料优化提示词。

![cover](cover.png)

---

## ⚠️ 免责声明

本项目仅供学习和技术研究参考，旨在探讨 Chrome DevTools Protocol、前端反爬机制与数据采集技术。请勿用于任何违反 [BOSS直聘用户协议](https://www.zhipin.com/about/protocol.html) 或相关法律法规的用途，不得用于商业转售、恶意爬取或对目标网站造成负担的行为。使用本项目所产生的一切后果由使用者自行承担，作者不对任何滥用行为负责。

---

## 🚀 30 秒快速开始

```bash
# 1. 克隆 + 装依赖
git clone https://github.com/eatmoreduck/boss-zhipin-scraper.git
cd boss-zhipin-scraper
uv sync --locked

# 2. 启动隔离 Chrome 并登录（只需一次，登录态持久保存）
uv run python scripts/boss_cdp_raw.py --setup-chrome

# 3. 抓取 + 分析
uv run python scripts/boss_cdp_raw.py --keyword "AI Agent" --city 上海 --pages 3 --analysis

# 支持全国城市（含三四五线），例如：
uv run python scripts/boss_cdp_raw.py --keyword "前端" --city 赣州 --pages 3
# 查看支持的城市：--list-cities [关键词]
uv run python scripts/boss_cdp_raw.py --list-cities 江

# 4. 抓取后生成聚合摘要 + 提示词（默认读取最新结果）
uv run python scripts/job_summary.py
```

抓完直接拿到：薪资分布、经验要求、高频技能词、求职材料优化提示词。提示词只基于岗位数据，不读取本地简历文件，也不给岗位算个人匹配分。

## Codex Skill 多轮深度检索（v2.6）

这是 Codex Skill 的确定性执行路径；原 JSON/CSV CLI 与 Streamlit 用法保持不变。策略身份由规范化后的检索词、目标岗位与类型、城市集合和筛选条件共同确定，城市输入顺序只决定调度顺序。每个城市固定最多扫描 15 页、保存 450 个列表候选；一次明确执行的 full Run 在所有城市之间共用 500 次可控 BOSS 逻辑操作（登录探测、列表 WAPI、详情导航）。500 是本地安全预算，不是 BOSS 官方安全阈值，也不能用来规避平台限制。

```powershell
# 首轮；执行前仍须先向用户展示方案并获得明确确认
python -m boss_app.cli run --keyword "新媒体运营" --target-role "新媒体运营" `
  --target-type exact_role --cities 北京 上海 深圳 --execute

# 预算用完后，由用户再次明确执行；从已保存的城市/页码/详情/AI 断点继续
python -m boss_app.cli run --keyword "新媒体运营" --target-role "新媒体运营" `
  --target-type exact_role --cities 北京 上海 深圳 --execute

# 明确从第一页启动新扫描 Cycle；只处理已保存 AI；或重建某个 Run 的文件
python -m boss_app.cli run --keyword "新媒体运营" --target-role "新媒体运营" `
  --target-type exact_role --cities 北京 上海 深圳 --refresh --execute
python -m boss_app.cli run --keyword "新媒体运营" --target-role "新媒体运营" `
  --target-type exact_role --cities 北京 上海 深圳 --ai-only --execute
python -m boss_app.cli export --run-id <RUN_ID>
```

跨 Run 使用全局岗位目录按平台岗位 ID、规范化链接去重；完整 JD 全局复用，AI 判断按策略保存。每个受控收口的 Run 都冻结“截至本 Run”的合格行和待复核行，并生成独立 `RunNNN` 累计 Excel，即使城市尚未全部完成也会产出；后续补导出读取冻结快照，不会把 Run002 的数据混入 Run001。相同且已完成的策略默认零 BOSS 请求返回最新文件，只有 `--refresh` 才创建新 Cycle；`--ai-only` 不执行 BOSS 操作，`export` 不创建 Run。

`--refresh` 只用于已经完成的 Cycle；若当前 Cycle 或崩溃遗留 Run 尚未收口，必须先按原模式续跑，不能借刷新跳过断点。`--ai-only` 不会接管运行中的 full Run，也不会解除此前的访问限制确认门。

命中 `code: 37`、HTTP 403/429 或明确访问限制时立即停止并保存断点，且不会自动重试。再次 full Run 前必须由用户确认平台访问已恢复并传入 `--confirm-access-restored`；项目不提供代理、多账号、验证码破解或请求指纹绕过。

## 本地数据与隐私

GitHub 仓库只保存程序和数据库结构，不包含用户的数据库、岗位结果、日志、密钥或 Chrome 登录状态。同一台电脑上的新 checkout 默认继续使用 `~/.boss-zhipin-scraper/boss_jobs.db`；在另一台电脑首次运行时，程序会创建一份新的空数据库并初始化表结构。

不要复制或提交 `.venv`。请使用 `uv sync --locked` 根据 `uv.lock` 重建环境。目录职责、备份与恢复方法见 [本地运行数据](docs/runtime-data.md)，当前 v2.6 数据流见 [架构说明](docs/architecture.md)。

## 本地 Streamlit 岗位采集程序

v2.4.0 在原 CLI 外提供本地应用。Streamlit 只创建任务、读取 SQLite 和启动独立 worker，不在页面进程内阻塞采集；同一时刻只允许一个任务持有 worker 租约。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
.\.venv\Scripts\python.exe scripts\boss_cdp_raw.py --setup-chrome
.\.venv\Scripts\python.exe -m streamlit run app.py
```

首次启动请只在弹出的 BOSS 专用 Chrome 中登录。主 Chrome 不会被关闭；进程管理严格按专用 `--user-data-dir` 匹配。AI 配置从本地 `.env` 读取 `BOSS_AI_API_KEY`、`BOSS_AI_BASE_URL` 和 `BOSS_AI_MODEL`，不保存账号、密码或验证码。未配置 AI 时，已发现候选和已保存的完整 JD 不会丢失；任务会进入 `waiting_for_ai` 并暂停后续详情抓取，配置完成后可使用“仅重试待处理 AI”。

界面默认预填“AI运营 / 全国 / 10 页 / 50 条扩容”，也可选择 10 条验证、20 条稳定性、100 条批量或自定义岗位数量；最大页数独立输入，单次上限为 15 页。历史任务可直接扩大目标，`completed` 不会重复处理，异常遗留的 `processing` 会恢复为 `pending`，失败详情只处理到配置的最大重试次数。

全国 `AI运营` 任务采用合格数量门禁：每个候选必须取得完整 JD，并在现有一次 AI 请求中同时返回 `is_ai_operations`、岗位职责、任职要求和加分项。只有 `crawl_status='completed' AND ai_status='completed'` 才计入目标 50；销售 AI 产品、CIO、纯产品经理、人工智能训练师或只在要求/公司介绍中提到 AI 的岗位标记为 `irrelevant`，保留用于去重但不重试、不导出、不算失败。页面耗尽或无新增且不足 50 时进入 `incomplete`，不会伪装成完成。

城市 `AI产品运营` 任务把每个已保存的完整 JD 交给单 AI Worker；详情抓取本身保持串行，但可在 AI 处理上一条 JD 时抓取下一条详情，AI 调用不会并发扩张。AI 销售、普通产品经理、纯运营或仅泛泛提到 AI 的候选标记为 `irrelevant`，保留用于去重和审计但不写入 Excel。15 页 / 450 个候选只是单城扫描上限，不是合格岗位目标；页面耗尽后任务正常完成，不会为凑满 450 个合格岗位继续补采。

全国任务优先保存列表 API 的纯城市名，详情地址不得覆盖，数据库和 Excel 都不会写入区、街道、商圈或详细地址。Excel 只导出合格岗位，严格 7 列：岗位名称、城市、薪资范围、岗位职责、任职要求、加分项、岗位详情链接；三类摘要在单元格内按 `1. 2. 3.` 换行，无加分项显示“无”。

岗位按任务内 `job_id` 和去除查询参数、锚点及尾部斜杠后的规范化岗位链接双重去重。命中 `code: 37`、HTTP 403/429 或明确的访问限制提示时，worker 会立即停止后续网络步骤、保留当前进度并将任务置为 `waiting_for_access`；界面不会自动循环重试，待平台恢复后由用户点击“恢复/继续任务”。详情请求保持串行，并用 `BOSS_NETWORK_INTERVAL_MIN` / `BOSS_NETWORK_INTERVAL_MAX` 配置随机间隔。

列表任务会在每个完整页面落盘后保存下一页游标。手动恢复时从该游标继续；若在页内暂停、写入失败或收到访问限制，则保留当前页以避免漏掉剩余岗位。默认 API 模式只用非搜索同源页建立页面上下文，再对每页执行一次显式列表请求，不再先加载真实搜索第一页后重复请求第一页。旧任务升级后首次恢复仍可能安全重放第一页。

对于已由可信离线来源写入同一任务的候选，应用层可调用 `Collector.run_existing(task_id, token)`，复用现有详情、AI、租约和断点流程而不再次请求岗位列表。它处理完当前已保存候选即结束，不会为凑足全国任务目标继续补充列表；若遇访问限制，仍须由用户手动再次调用恢复。

## ✨ 特性

- 明文薪资（API 模式直接读取 `salaryDesc`，不解析受字体混淆影响的 DOM 文本）
- Boss 活跃状态独立字段（`boss_active_status`）：列表兼容 `bossOnline`→「在线」，详情可得到「刚刚活跃」等更细状态
- JSON / CSV 双格式输出
- 详情页 JD 抓取 + 技能分析
- 抓取后聚合摘要 + 可复制提示词
- 增量写入（异常退出不丢数据）
- SQLite 任务状态机、独立 worker、单实例租约和暂停/继续
- 分阶段数量、历史任务原地扩容、双重去重和访问受限断点恢复
- OpenAI 兼容接口一次请求完成完整 JD 的 AI 运营相关性审核与三类摘要
- 全国 AI运营 50 条合格门禁，支持 `irrelevant` 审计和不足目标时的 `incomplete`
- 纯城市字段与严格 7 列 Excel（编号换行、冻结筛选、可点击岗位链接）
- Streamlit 本地界面与 2 秒只读状态刷新
- 一键环境检查 + 持久隔离 Chrome CDP profile
- 多维筛选（规模、融资、薪资、经验、学历、行业）
- Windows + macOS + Linux；Windows 会兼容 GBK 控制台和带空格的 Chrome profile 路径

<details>
<summary>🔍 为什么不选 Selenium / Playwright 类爬虫？</summary>

- Selenium/Playwright 会额外启动一套受控浏览器；本项目为了复用用户本人明确登录的隔离 Chrome，选择了更轻量的 CDP 连接方式。
- 列表页调用同一页面使用的搜索 API，直接读取明文 `salaryDesc`，无需把受字体混淆影响的 DOM 薪资当作可信数据。
- CDP 并不保证不会触发平台限制。程序遇到限制状态会保存进度并停止，不提供代理、多账号、验证码破解或请求指纹绕过。

</details>

## 安装

### 完整项目（推荐）

v2.6 的 Skill 入口依赖 `boss_app/`、`scripts/`、`data/` 和项目依赖，不能只下载 `SKILL.md` 或单个脚本。请克隆完整仓库：

```bash
git clone https://github.com/eatmoreduck/boss-zhipin-scraper.git
cd boss-zhipin-scraper
uv sync --locked
uv run python scripts/boss_cdp_raw.py --help
```

没有 `uv` 时，也可以用 Python 3.10+ 创建 `.venv`，再从 `requirements.txt` 安装依赖。

### 作为 Codex Skill 使用

把**完整仓库**克隆到 Codex skills 目录，再在仓库内创建依赖环境：

```bash
git clone https://github.com/eatmoreduck/boss-zhipin-scraper.git \
  ~/.codex/skills/boss-zhipin-scraper
cd ~/.codex/skills/boss-zhipin-scraper
uv sync --locked
```

安装后重新打开 Codex 任务，再说“帮我搜一下 BOSS直聘 上上海的 AI Agent 岗位”。Skill 仍会先展示方案并等待确认，确认前不会访问 BOSS。

## 作为命令行工具使用

不想装成 Skill 也可以直接当 CLI 用：

```bash
# 1. 克隆 + 安装依赖
git clone https://github.com/eatmoreduck/boss-zhipin-scraper.git
cd boss-zhipin-scraper
pip install -r requirements.txt

# 2. 启动 Chrome CDP
python3 scripts/boss_cdp_raw.py --setup-chrome
# 首次使用也不会复制主 Chrome 登录态；请在弹出的 BOSS 专用浏览器中登录 zhipin.com
# setup 会等待登录完成，并确认接口能返回明文薪资

# 3. 检查环境
python3 scripts/boss_cdp_raw.py --check

# 可选：真实浏览器/API smoke test（不写结果文件）
python3 scripts/boss_cdp_raw.py --smoke-test

# 4. 抓取
python3 scripts/boss_cdp_raw.py --keyword "AI Agent" --city 上海 --pages 3 --format csv --analysis

# 5. 抓取后摘要和提示词
python3 scripts/job_summary.py --top 15
```

## 参数

| 参数 | 说明 |
|------|------|
| `--keyword` | 搜索关键词（默认 "AI Agent"） |
| `--city` | 城市（中文或 9 位代码，默认上海）。**支持全国城市**（一二三四五线全覆盖，共 300+ 个），运行时自动从 BOSS 同步最新城市码；码表见 [`data/city_codes.json`](data/city_codes.json)，或用 `--list-cities` 查看。本地及在线码表均无法识别的城市名会报错退出，避免静默得到 0 条结果 |
| `--list-cities [关键词]` | 打印支持的城市列表，可选关键词过滤，如 `--list-cities 江` |
| `--pages` | 页数（上限 15） |
| `--format` | json / csv；csv 会同时导出列表和详情 CSV |
| `--detail` | 抓取详情页 JD（默认开启） |
| `--no-detail` | 不抓取详情页 |
| `--analysis` | 分析报告 |
| `--merge FILE` | 合并已有数据（按 job_id 去重） |
| `--allow-dom-fallback` | API 无数据时允许降级 DOM 提取；默认关闭，薪资可能不可信 |
| `--check` | 环境检查（CDP + 依赖 + 登录态） |
| `--smoke-test` | 用真实 Chrome/CDP 跑一次 BOSS 搜索 API smoke test，不写结果文件 |
| `--setup-chrome` | 一键启动 Chrome CDP（持久隔离 profile） |
| `--copy-login-state` | 手动导入主 Chrome 的 Local State + Cookie 相关文件到隔离 profile（默认、首次启动、重复启动都不复制） |
| `--reset-chrome-profile` | 重建 BOSS 专用 Chrome profile，会清除此专用浏览器内的登录态 |
| `--no-wait-login` | `--setup-chrome` 启动后不等待登录完成 |
| `--login-timeout` | `--setup-chrome` 等待登录完成的秒数（默认 300） |
| `--stop-chrome` | 关闭 BOSS 专用 CDP Chrome（按隔离 profile 精准匹配，不碰主 Chrome） |
| `--close-chrome` | 抓取正常结束后自动关闭专用 Chrome（默认不关；异常退出不触发，保留登录态） |
| `--output` | 列表输出路径（默认 `~/.boss-zhipin-scraper/job-result/`） |
| `--detail-output` | 详情输出路径（默认 `~/.boss-zhipin-scraper/job-result/`） |
| `--cdp-port` | CDP 端口（默认 9222） |
| `--scale/--salary/--experience/--degree` | 筛选条件 |

## 抓取后摘要与提示词

`scripts/job_summary.py` 只读取已抓取的 `boss_jobs_*.json` 和 `boss_details_*.json`，做简单聚合分析并生成一段可复制提示词。它不读取本地简历文件，不引入 PDF 依赖，也不给个人与岗位做分数判断。

```bash
# 读取默认结果目录下最新的 boss_jobs_*.json，并自动匹配同时间戳或最新详情文件
python3 scripts/job_summary.py

# 指定列表和详情文件
python3 scripts/job_summary.py \
  --input ~/.boss-zhipin-scraper/job-result/boss_jobs_20260625_1200.json \
  --details ~/.boss-zhipin-scraper/job-result/boss_details_20260625_1200.json \
  --top 15

# 只输出提示词
python3 scripts/job_summary.py --prompt-only
```

打包安装后也可以使用入口命令：

```bash
uv run boss-summary --top 15
```

摘要会覆盖这些维度：薪资区间、经验要求、学历要求、地区分布、高频公司、技能标签、JD 高频词。提示词会要求模型基于这些统计去做简历关键词补齐、项目经历改写方向和面试准备清单，但明确要求不要虚构经历。

## 文件结构

```
boss-zhipin-scraper/
├── app.py                # Streamlit 本地任务面板
├── boss_app/             # SQLite、worker、AI 解析与 Excel 导出服务
├── SKILL.md              # Codex Skill 定义
├── README.md
├── CHANGELOG.md
├── LICENSE
├── pyproject.toml
├── data/
│   └── city_codes.json   # 全量城市码表
├── scripts/
│   ├── boss_cdp_raw.py   # CDP 抓取核心 + 原 CLI
│   └── job_summary.py    # 抓取后摘要 + 提示词
└── requirements.txt
```

## 工作原理

这是一个基于 Chrome CDP 的 BOSS直聘爬虫，核心流程：

1. 通过 Chrome DevTools Protocol (CDP) 连接到已打开的 Chrome
2. 在 BOSS直聘页面内注入 JS，用同步 XHR 调用搜索 API
3. API 返回明文 `salaryDesc`，无需解析受字体混淆影响的 DOM 薪资
4. 列表 API 保留 `securityId` / `lid` 等上下文，进入详情页时带上这些参数
5. 每页抓完立即写入文件，按 `job_id` 去重

默认不会使用 DOM 提取列表，因为 DOM 薪资可能受字体反爬影响。只有明确传 `--allow-dom-fallback` 时，API 无数据才会降级 DOM。

详情页只从包含“职位描述”的详情区提取 JD，整页 `body` 仅用于识别登录墙和导航页，不会直接写入结果。若页面出现“登录查看完整内容”，抓取会明确报错并停止，避免把截断正文、招聘者信息、公司介绍和推荐职位当成完整 JD 保存。

`--input ... --analysis --no-detail` 会优先加载 `--detail-output`，其次加载与输入列表同目录、同时间戳的 `boss_details_*.json`，最后查找 `~/.boss-zhipin-scraper/job-result` 下最新详情文件。

## Chrome profile 安全策略

`--setup-chrome` 默认使用持久隔离 profile，不软链接、不复制你的主 Chrome 数据。首次启动和后续重复启动都只是创建或复用这个专用 profile：

- `~/.boss-zhipin-scraper/chrome-profile`

未显式指定 `--output` 或 `--detail-output` 时，抓取结果默认保存到：

- `~/.boss-zhipin-scraper/job-result`

首次使用需要在这个专用 Chrome 中手动登录 BOSS直聘。`--setup-chrome` 会等待登录完成，并用搜索接口确认能拿到明文 `salaryDesc` 后再返回。登录态保存在专用 profile 内，重启机器后仍然保留；重复运行 `--setup-chrome` 不会清空它，也不会影响主 Chrome、Gmail、GitHub 等账号。

`--check` 和 worker 启动前的登录检查会先初始化真实搜索结果页，再从同一页面上下文发送一次搜索接口探测，避免从站点首页直接请求 wapi 产生与用户可见搜索页不一致的结果。登录探测每轮只发送一个搜索请求，并在不同关键词/城市之间轮换，等待间隔会从 3 秒逐步退避到最多 15 秒；这些请求同样计入单次 500 次的全局请求预算。未登录、探测样本为空、接口限制和响应异常会分别提示。遇到已确认的限制状态（例如 `code: 31`、`code: 37`「您的环境存在异常」）会立即停止探测，不会继续提示重复登录或密集重试；对未知风控码还会按 message 关键字（环境存在异常、访问频繁、安全校验等）兜底识别为限制状态，避免把「已登录但被风控」误判为登录失败。

`--setup-chrome` 的交互式登录页是唯一会主动置前的临时页面；环境检查、列表/详情抓取和 smoke test 创建的临时标签页都会在后台运行，避免自动流程反复抢占当前窗口。这里的“后台”仅表示不激活标签页，专用 Chrome 仍以有界面模式运行，必要时可以手动打开检查。

如确实需要从主 Chrome 手动导入 BOSS 登录态，可以显式运行：

```bash
python3 scripts/boss_cdp_raw.py --setup-chrome --copy-login-state
```

`--copy-login-state` 每次运行都会覆盖隔离 profile 内对应的 Cookie 相关文件；日常启动不要加这个参数。它只复制 `Local State` 和 `Default/Cookies*`、`Default/Network/Cookies*` 这类 Cookie 数据库相关文件，不复制密码库、历史记录、扩展或完整 profile。需要清空专用浏览器登录态时使用：

```bash
python3 scripts/boss_cdp_raw.py --setup-chrome --reset-chrome-profile
```

### 用完如何收尾

抓取/分析结束后，专用 Chrome 不会自动关闭（默认保留登录态，方便你接着跑下一条抓取）。确认不再使用时，可以手动收尾：

```bash
python3 scripts/boss_cdp_raw.py --stop-chrome
```

`--stop-chrome` 只关闭 scraper 隔离 profile（`--user-data-dir`）对应的 Chrome 进程，**绝不**按端口或进程名去 kill，因此不会误伤你正在用的主 Chrome、Gmail、GitHub 等账号。

如果你希望某次抓取正常结束后就顺手关掉 Chrome，可以加 `--close-chrome`：

```bash
python3 scripts/boss_cdp_raw.py --keyword "AI Agent" --city 上海 --pages 3 --close-chrome
```

`--close-chrome` 默认不开启；且只在抓取走完的**成功路径**上触发，登录失败、异常退出等情况不会关闭 Chrome，登录态得以保留。

## License

MIT

## 友情链接

- [LINUX DO](https://linux.do/) — 真诚、友善、充满活力的技术社区，本项目认可并推荐。

## Star History

[![Star History Chart](https://api.star-history.com/svg?repos=eatmoreduck/boss-zhipin-scraper&type=Date)](https://star-history.com/#eatmoreduck/boss-zhipin-scraper&Date)
