# 贡献指南

感谢你对 boss-zhipin-scraper 的兴趣！无论是提 Issue、修 Bug 还是加功能，都欢迎。

## 行为准则

请保持友善、尊重。技术讨论对事不对人，不接受任何人身攻击或骚扰言论。

## 在贡献之前

- **先开 Issue 再写代码**：修 Bug 或加新功能前，请先在 [Issues](../../issues) 里搜索是否已有人提过；没有的话新开一个，简要说明你打算做什么，避免和别人重复劳动或方向跑偏。
- **一个 PR 只做一件事**：混合多个改动的 PR 很难 review，请拆开。

## 开发环境

```bash
git clone https://github.com/eatmoreduck/boss-zhipin-scraper.git
cd boss-zhipin-scraper
uv sync --locked
uv run python -m unittest discover -s tests -v
```

要求 Python 3.10+。CLI 核心依赖 `requests` 和 `websocket-client`；本地应用还依赖 Streamlit、Pandas、OpenPyXL 和 python-dotenv，以 `requirements.txt` / `pyproject.toml` 为准。

## 代码规范

- **风格**：遵循 [PEP 8](https://peps.python.org/pep-0008/)，用 4 空格缩进、UTF-8、LF 换行。
- **异常处理**：不要用 bare `except:`，必须捕获具体异常类型（`requests.ConnectionError`、`json.JSONDecodeError` 等），项目现有的代码就是这么做的，请保持一致。
- **CDP 核心单文件原则**：浏览器/CDP、页面注入脚本和原 CLI 继续集中在 `scripts/boss_cdp_raw.py`。本地应用服务（SQLite、任务、worker、AI、Excel、登录映射）允许放在 `boss_app/`，Streamlit 入口为根目录 `app.py`；不要把 UI 或数据库逻辑塞回 CDP 核心。
- **注释**：复杂逻辑要写注释（参考 `human_scroll` 的做法）；公开函数补 docstring。

## 测试要求

- 修了 Bug 或加功能，**必须补测试**。CDP/CLI 测试在 `tests/test_chrome_setup.py`，应用测试在 `tests/test_boss_app.py`；均用标准库 `unittest` mock 外部服务，常规回归**不需要真实 Chrome 或网络**。
- 提 PR 前本地先跑通：

  ```bash
  uv run python -m unittest discover -s tests -v
  ```

- 涉及版本号改动，会触发 `VersionConsistencyTests`，确保 `scripts/boss_cdp_raw.py`、`pyproject.toml`、`SKILL.md`、`README.md` 四处版本一致。

## 提交信息（Commit Message）

使用 [Conventional Commits](https://www.conventionalcommits.org/) 格式，参考现有提交历史：

```
<type>: <简短描述，中文或英文均可>

feat: 新功能        例: feat: 详情页加过程日志
fix: 修 Bug         例: fix bug salary garbled characters
optimize: 优化      例: optimize(risk-control): 优化详情页进入方式
docs: 文档          例: docs: 更新 README 参数说明
refactor: 重构      例: refactor: API 路径提取为常量
test: 测试          例: test: 补城市码去重校验
chore: 杂项         例: chore: 升级依赖
```

## Pull Request 流程

1. Fork 仓库，从 `main` 拉一个新分支（`git checkout -b fix/city-code-typo`）。
2. 改代码 → 补测试 → 本地跑通。
3. 如果改了用户可见行为，更新 `README.md`；如果是有意义的变更，在 `CHANGELOG.md` 顶部加一条。
4. 提交 PR，描述里写清楚：改了什么、为什么改、怎么测试的。
5. 等待 review，有反馈就改，保持同一个 PR（不要关掉重开）。

## 关于合规

本项目通过复用用户**本人已登录的浏览器**抓取公开可见的职位数据，用于个人求职分析。提交代码时请不要加入任何大规模、无节制请求、或绕过平台安全校验的逻辑——这类改动不会被接受。请遵守目标网站的条款，对自己使用本工具的行为负责。

## 有问题？

- Bug / 功能建议 → [Issues](../../issues)
- 不确定怎么改 → 先开 Issue 讨论

再次感谢你的贡献！
