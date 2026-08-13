---
name: boss-zhipin-job-research
description: Collect and analyze public BOSS直聘 job listings through the user's logged-in dedicated Chrome, with SQLite resume, concurrent detail/AI processing, strict target-JD review, and Excel export. Use when the user asks Codex to search, collect, inspect, analyze, or export BOSS直聘 or zhipin.com jobs by target role and city.
---

# BOSS直聘岗位采集

Version: 2.8.0

仅用于用户个人求职分析。复用本 Skill 内现有 `boss_app`、`scripts/boss_cdp_raw.py` 和 `data/city_codes.json`，不要复制 CDP 实现。

## 解析用户需求

从用户的一句话中提取：

- 城市列表
- 用户目标
- BOSS 检索词
- 目标类型：`exact_role` 或 `domain_scope`

用户只输入一次。明确岗位如“新媒体运营”使用 `exact_role`；领域目标如“AI产品相关岗位”使用 `domain_scope`。检索词只允许去掉“抓取”“相关岗位”等指令性文字，不得添加同义词、相近岗位或额外城市。

## 必须先确认

首次收到真实抓取需求时，只输出以下简短方案，随后结束当前回复并等待用户确认：

```text
已解析抓取方案：

城市：北京
目标岗位：新媒体运营
BOSS检索词：新媒体运营
目标类型：明确岗位
关键词扩展：关闭
筛选方式：根据完整JD严格筛选
抓取范围：尽可能获取全部可访问结果
单城市上限：15页 / 450个列表候选
单次Run预算：所有城市共用500次BOSS逻辑请求
输出文件：每轮独立的 RunNNN 累计 Excel

请确认是否按此方案执行。
```

确认前不得访问 BOSS、启动 Chrome、创建任务或修改正式数据库。用户修改目标时重新展示完整方案。不要输出按钮文字。

## 确认后执行

仅在用户明确回复确认后：

1. 使用项目 `.venv`，检查依赖、专用 Chrome CDP 和登录状态。
2. 调用确定性入口；不要让 Python 再次解释自然语言：

```powershell
python -m boss_app.cli run `
  --keyword "新媒体运营" `
  --target-role "新媒体运营" `
  --target-type exact_role `
  --cities 北京 上海 `
  --execute
```

3. 多城市按顺序访问 BOSS。每个 Strategy 城市每次只抓一页列表，随后逐个抓完该页详情并完成 AI 判断，再决定是否请求下一页；BOSS 列表与详情始终串行，只有详情抓取与单 AI Worker 可以重叠。恢复时先清理 SQLite 中已有的详情和 AI 积压。
4. AI只能依据用户确认目标和完整 JD 判断：匹配、待人工确认或不相关。不得扩大目标。
5. 单次 Run 共用 500 次 BOSS 逻辑请求；第 500 次允许，第 501 次在网络操作前停止。每个城市固定最多 15 页 / 450 个列表候选。
6. 每个正常收口的 Run 都生成独立累计 Excel，不必等待全部城市完成；SQLite 先冻结当轮合格行和待复核行，补导出不会吸收后续 Run 的数据。
7. 相同且已完成的策略默认直接返回最新 Excel，不创建 Run，也不发送 BOSS 请求。
8. `--refresh` 只能用于已完成 Cycle；未完成或崩溃遗留 Run 必须按原模式续跑。`--ai-only` 不接管运行中的 full Run，也不解除此前的访问恢复确认门。

预算耗尽后的下一次明确执行会从保存的城市、页码、详情和 AI 断点继续，并得到新的本地 500 次 Run 预算：

```powershell
python -m boss_app.cli run `
  --keyword "新媒体运营" --target-role "新媒体运营" `
  --target-type exact_role --cities 北京 上海 --execute
```

只有当前 Cycle 已完成且用户明确要求重新扫描时才启动新 Cycle：

```powershell
python -m boss_app.cli run `
  --keyword "新媒体运营" --target-role "新媒体运营" `
  --target-type exact_role --cities 北京 上海 --refresh --execute
```

仅处理已保存的完整 JD，不访问 BOSS：

```powershell
python -m boss_app.cli run `
  --keyword "新媒体运营" --target-role "新媒体运营" `
  --target-type exact_role --cities 北京 上海 --ai-only --execute
```

纯本地重建指定 Run 的冻结工作簿，不创建新 Run：

```powershell
python -m boss_app.cli export --run-id <RUN_ID>
```

## 强制停止规则

- `code: 37`、HTTP 403/429 或明确访问限制：立即停止所有后续 BOSS 请求，保存断点，不自动重试；AI继续处理已经保存的完整 JD。
- 访问恢复后，必须再次得到用户明确确认并在 full Run 中传入 `--confirm-access-restored`；不得按时间自动解除限制。
- AI配置缺失或服务失败：保存 `waiting_for_ai` 并停止继续抓取。
- 登录失效：进入 `waiting_for_login`，等待用户处理。
- 不使用代理、多账号、验证码破解、请求指纹绕过或自动循环恢复。

## 结果交付

每次执行后核验数据库、Run 状态和工作簿，并报告 Strategy ID、Run ID、已用请求数、停止原因及该 Run 独立累计 Excel 的绝对路径。不要等待所有城市完成才交付当轮文件，也不要把当轮快照误称为全部城市均已完成。

用户另行要求市场摘要或求职材料提示词时，复用 `scripts/job_summary.py`（安装后的命令为 `boss-summary`）。
