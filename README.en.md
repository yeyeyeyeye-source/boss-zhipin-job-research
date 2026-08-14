# boss-zhipin-job-research v2.8 (Chrome CDP / Codex Skill)

> 🌐 中文文档：[README.md](./README.md)

![Python](https://img.shields.io/badge/python-3.10+-blue.svg)
![License](https://img.shields.io/badge/license-MIT-green.svg)
![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey.svg)
![Version](https://img.shields.io/badge/version-2.8.0-orange.svg)

A lightweight **BOSS Zhipin scraper / crawler** for [zhipin.com](https://www.zhipin.com). It connects to a dedicated, locally logged-in Chrome over CDP and calls the in-page search API. The current release keeps the original JSON / CSV CLI and adds resumable SQLite tasks, AI-assisted full-JD review, qualified-job Excel export, and a local Streamlit task UI.

The canonical source and maintenance repository is
[yeyeyeyeye-source/boss-zhipin-job-research](https://github.com/yeyeyeyeye-source/boss-zhipin-job-research).
See [Project provenance](docs/provenance.md) for origin and MIT attribution.

v2.5 also provides a Codex Skill. It previews the exact user strategy before execution, never expands search keywords, runs detail collection and AI review concurrently, and applies strict full-JD relevance checks to any confirmed target role.

> 📌 **In one sentence**: no Selenium/Playwright — connect to your logged-in Chrome over CDP, hit the search API with the real session, get JSON/CSV with plaintext salaries, plus salary-distribution, skill-frequency stats and a résumé-optimization prompt.

---

## ⚠️ Disclaimer

This project is for **learning and technical research purposes only**. It is intended to explore Chrome DevTools Protocol, front-end anti-scraping mechanisms, and data-collection techniques. Do **not** use it for any purpose that violates the [BOSS Zhipin Terms of Service](https://www.zhipin.com/about/protocol.html) or applicable laws and regulations, including commercial resale, malicious scraping, or any activity that imposes undue load on the target site. Users are solely responsible for the consequences of using this project; the author is not liable for any misuse.

---

## 🚀 30-Second Quick Start

```bash
# 1. Clone + install deps
git clone https://github.com/yeyeyeyeye-source/boss-zhipin-job-research.git
cd boss-zhipin-job-research
uv sync --locked

# 2. Launch an isolated Chrome and log in (only once; session persists)
uv run python scripts/boss_cdp_raw.py --setup-chrome

# 3. Scrape + analyze
uv run python scripts/boss_cdp_raw.py --keyword "AI Agent" --city 上海 --pages 3 --analysis

# Cities nationwide are supported (incl. tier-3/4/5), e.g.:
uv run python scripts/boss_cdp_raw.py --keyword "前端" --city 赣州 --pages 3
# List supported cities: --list-cities [keyword]
uv run python scripts/boss_cdp_raw.py --list-cities 江

# 4. Generate an aggregated summary + prompt after scraping (reads the latest result)
uv run python scripts/job_summary.py
```

Right after scraping you get: salary ranges, experience requirements, top skill keywords, and a job-application optimization prompt. The prompt is based solely on the scraped job data — it never reads your local résumé file and never scores personal-job match.

## Codex Skill Multi-Run Deep Search (v2.8)

This is the deterministic Codex Skill execution path; the legacy JSON/CSV CLI and Streamlit workflows remain available. A strategy is identified by its normalized keyword, target role/type, city set, and filters, while city input order controls scheduling only. Each city scans at most 15 pages / 450 list candidates. One explicitly started full Run shares 500 controllable BOSS logical operations across all cities (login probes, list WAPI calls, and detail navigations). This is a local safety budget—not an official BOSS risk threshold or a restriction-bypass mechanism.

```powershell
# First Run; show the parsed plan and obtain explicit user confirmation first
python -m boss_app.cli run --keyword "New Media Operations" --target-role "New Media Operations" `
  --target-type exact_role --cities 北京 上海 深圳 --execute

# A later explicit Run resumes saved city/page/detail/AI checkpoints
python -m boss_app.cli run --keyword "New Media Operations" --target-role "New Media Operations" `
  --target-type exact_role --cities 北京 上海 深圳 --execute

# Start a fresh scan Cycle, process saved AI only, or rebuild one Run workbook
python -m boss_app.cli run --keyword "New Media Operations" --target-role "New Media Operations" `
  --target-type exact_role --cities 北京 上海 深圳 --refresh --execute
python -m boss_app.cli run --keyword "New Media Operations" --target-role "New Media Operations" `
  --target-type exact_role --cities 北京 上海 深圳 --ai-only --execute
python -m boss_app.cli export --run-id <RUN_ID>
```

Across Runs, a global catalog deduplicates jobs by platform ID and normalized URL. Full JDs are reused globally, while AI decisions remain strategy-scoped. Every controlled Run freezes its qualified/review projection and produces an independent cumulative `RunNNN` workbook even when some cities remain unfinished. Re-export reads that frozen projection, so Run002 can never change Run001. Re-running an identical completed strategy returns its latest workbook with zero BOSS requests; only `--refresh` starts a new Cycle. `--ai-only` performs no BOSS operation, and `export` creates no Run.

When a user pauses a Strategy task, its current Run stays `running` and neither freezes a snapshot nor exports an unfinished result. The next explicit execution of the same strategy reuses that Run, its remaining request budget, and its saved checkpoints. Strategy tasks can be inspected and paused in Streamlit, but the generic task controls cannot expand, resume, or retry AI for them; use the Codex Skill or `boss-jobs run` so recovery keeps the original Run snapshot and budget boundaries.

Strategy tasks use a single-page pipeline: fetch one list page, process that page's full JDs and AI decisions, and only then decide whether another page is needed. BOSS list and detail operations remain serial; only the existing single AI worker may overlap with detail collection. A resumed task drains saved detail and AI backlog before expanding the list.

`--refresh` is only valid after the current Cycle has completed. An unfinished Cycle or crash-resumable Run must first continue in its original mode, so refresh cannot skip saved checkpoints. `--ai-only` never takes over a running full Run and never clears an earlier access-restoration gate.

`code: 37`, HTTP 403/429, or an explicit access restriction stops the Run immediately and saves its checkpoints. A later full Run requires the user to confirm access has recovered with `--confirm-access-restored`; there is no automatic retry, proxy, multi-account, CAPTCHA-breaking, or fingerprint-bypass path.

Detail-page URL parameters are diagnostic only and do not establish an access restriction by themselves. A correctly identified job with a valid complete JD is accepted when no explicit restriction evidence is present; an ordinary missing-JD extraction failure is not mislabeled as an access restriction.
Page-state evidence is evaluated one minimal visible text unit at a time outside the JD region, including explicit metadata from visible CAPTCHA iframes. One explicit overlay is treated as a complete status unit; otherwise parent/child candidates and unrelated page regions are not combined. Detection does not depend on CAPTCHA node class names or IDs, and hidden templates or ordinary business copy are not restriction evidence.

## Local Data and Privacy

The GitHub repository contains the application and database schema, not a user's database, job results, logs, secrets, or Chrome login state. A new checkout on the same computer continues to use `~/.boss-zhipin-job-research/boss_jobs.db` by default. On another computer, the application creates a new empty database and initializes its schema on first use.

When upgrading from the legacy directory, first close any program using an Excel file, database, or Chrome profile inside it, then rename the **entire** `~/.boss-zhipin-scraper` tree on the same volume to `~/.boss-zhipin-job-research`. Do not copy only `boss_jobs.db`: its WAL/SHM companions, Chrome login state, and historical outputs belong to the same runtime tree. On Windows run `Move-Item -LiteralPath "$HOME\.boss-zhipin-scraper" -Destination "$HOME\.boss-zhipin-job-research"`; on macOS/Linux run `mv -- "$HOME/.boss-zhipin-scraper" "$HOME/.boss-zhipin-job-research"`. If the old tree exists and the new one does not, default entry points stop with migration guidance. If both trees exist, they stop and require manual reconciliation rather than overwriting or hiding either side. Explicit `--db`, `BOSS_DB_PATH`, or input/output paths remain available.

Do not copy or commit `.venv`. Rebuild it from `uv.lock` with `uv sync --locked`. See [Local runtime data](docs/runtime-data.md) for storage, backup, and restore boundaries, and [Architecture](docs/architecture.md) for the current v2.8 data flow.

## Local Streamlit Job Collector

The local app wraps the existing CLI. Streamlit only creates tasks, reads SQLite, and launches a separate worker; it never runs the blocking collection loop in the UI process. A SQLite lease permits only one active worker at a time. A new task accepts any target role and a user-defined target job count up to 450. The role is used both as the search keyword and as the exact-role AI review target for each complete JD. Development test modes and page controls are no longer exposed; every task uses the internal ceiling of 15 pages with 30 candidates per page.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
.\.venv\Scripts\python.exe scripts\boss_cdp_raw.py --setup-chrome
.\.venv\Scripts\python.exe -m streamlit run app.py
```

On first use, log in only inside the dedicated BOSS Chrome window. Process management matches its exact `--user-data-dir` and never closes the main Chrome profile. AI configuration comes from local `BOSS_AI_API_KEY`, `BOSS_AI_BASE_URL`, and `BOSS_AI_MODEL` values in `.env`; no account, password, or verification code is stored. Without AI configuration, discovered candidates and already saved full JDs remain intact, but the task enters `waiting_for_ai` and pauses later detail collection until AI is configured; an AI-only retry can then continue locally.

All newly created Streamlit tasks use a qualified-count gate. Every candidate must have a complete JD, and one AI request classifies it as matched, irrelevant, or manual review against the user-entered role while also extracting responsibilities, requirements, and bonus points. Only `crawl_status='completed' AND ai_status='completed'` counts toward the target job count. Irrelevant candidates remain available for deduplication and audit but are not counted or exported. If the internal page ceiling is exhausted or a round adds no candidates before the requested qualified count is reached, the task becomes `incomplete` rather than completed. Detail collection remains serial, but it can fetch the next detail while the single AI worker processes the previous JD; AI calls never fan out concurrently. Historical tasks can still be expanded in place without reprocessing completed rows.

The list API's city name is preferred and detail addresses cannot overwrite it, so districts, streets, business areas, and full addresses are not stored or exported for the nationwide task. Excel contains qualified jobs only and has exactly seven columns: job title, city, salary range, responsibilities, requirements, bonus points, and job URL. The three summary cells use numbered line breaks; missing bonus points render as `无`.

Jobs are deduplicated per task by both `job_id` and a normalized job URL with its query, fragment, and trailing slash removed. On `code: 37`, HTTP 403/429, or an explicit access-restriction message, the worker immediately stops subsequent network steps, preserves progress, and sets `waiting_for_access`. The UI never retries this state automatically; after access recovers, the user explicitly chooses “恢复/继续任务”. Unknown URL markers do not trigger that state by themselves; a correctly identified job with a valid complete JD continues normally when no explicit restriction evidence is present. Detail requests remain serial and use randomized delays configured by `BOSS_NETWORK_INTERVAL_MIN` / `BOSS_NETWORK_INTERVAL_MAX`.

List tasks persist the next-page cursor only after a full page is durably processed. Manual resume continues from that cursor; a mid-page pause, local write failure, or access restriction keeps the current page so no remaining jobs are skipped. The default API path now initializes a non-search same-origin page and performs one explicit list request per page instead of loading and then re-requesting the real first search page. Legacy tasks may safely replay page 1 once after upgrading.

For candidates already inserted into the same task from a trusted offline source, the application layer can call `Collector.run_existing(task_id, token)`. It reuses the existing detail, AI, lease, and checkpoint pipeline without requesting the job list again. It stops after the saved candidates are processed instead of supplementing a nationwide target; an access restriction still requires an explicit manual call to resume.

## ✨ Features

- Plaintext salary (`salaryDesc` from API mode, without trusting font-obfuscated DOM text)
- Boss activity status as a separate field (`boss_active_status`): list maps `bossOnline`→"在线"; detail can provide finer labels like "刚刚活跃"
- Dual JSON / CSV output
- Detail-page JD scraping + skill analysis
- Aggregated summary + copy-paste prompt after scraping
- Incremental writes (no data loss on crash)
- SQLite task state machine, isolated worker, single-instance lease, and pause/resume
- User-defined target count, in-place historical expansion, dual deduplication, and access-limit recovery
- One OpenAI-compatible request for target-role relevance review and full-JD summaries
- User-defined qualified target job count with `irrelevant` audit rows and `incomplete` exhaustion state
- City-only storage and fixed seven-column Excel with numbered summaries and clickable links
- Local Streamlit dashboard with a two-second read-only status refresh
- One-shot environment check + persistent isolated Chrome CDP profile
- Multi-dimension filters (scale, funding, salary, experience, degree, industry)
- Windows + macOS + Linux, including GBK-safe Windows output and quoted Chrome profile paths

<details>
<summary>🔍 Why not a Selenium / Playwright crawler?</summary>

- Selenium/Playwright launches an additional controlled browser. This project instead uses a lighter CDP connection to the dedicated Chrome profile the user explicitly logged into.
- The list path calls the same search API used by the page and reads plaintext `salaryDesc`, so font-obfuscated DOM salary text is not treated as trusted data.
- CDP does not guarantee that platform restrictions will never occur. On a restriction the program preserves progress and stops; it provides no proxies, multiple-account rotation, CAPTCHA cracking, or request-fingerprint bypass.

</details>

## Installation

### Complete project (recommended)

The v2.8 Skill entry point depends on `boss_app/`, `scripts/`, `data/`, and the project dependencies. Downloading only `SKILL.md` or individual scripts is not sufficient. Clone the complete repository:

```bash
git clone https://github.com/yeyeyeyeye-source/boss-zhipin-job-research.git
cd boss-zhipin-job-research
uv sync --locked
uv run python scripts/boss_cdp_raw.py --help
```

If `uv` is unavailable, create `.venv` with Python 3.10+ and install `requirements.txt` instead.

### Use as a Codex Skill

Clone the **complete repository** into the Codex skills directory, then create its dependency environment:

```bash
git clone https://github.com/yeyeyeyeye-source/boss-zhipin-job-research.git \
  ~/.codex/skills/boss-zhipin-job-research
cd ~/.codex/skills/boss-zhipin-job-research
uv sync --locked
```

Restart the Codex task after installation, then say: “Search BOSS Zhipin for AI Agent jobs in Shanghai.” The Skill still previews the plan and waits for confirmation before accessing BOSS.

## Use as a CLI tool

You don't have to install it as a Skill — use it as a plain CLI:

```bash
# 1. Clone + install deps
git clone https://github.com/yeyeyeyeye-source/boss-zhipin-job-research.git
cd boss-zhipin-job-research
pip install -r requirements.txt

# 2. Start Chrome CDP
python3 scripts/boss_cdp_raw.py --setup-chrome
# First run won't copy your main Chrome session; log in to zhipin.com in the dedicated BOSS browser that pops up
# setup waits for login to finish and confirms the API returns plaintext salaries

# 3. Check the environment
python3 scripts/boss_cdp_raw.py --check

# Optional: real browser/API smoke test (writes no result files)
python3 scripts/boss_cdp_raw.py --smoke-test

# 4. Scrape
python3 scripts/boss_cdp_raw.py --keyword "AI Agent" --city 上海 --pages 3 --format csv --analysis

# 5. Summary + prompt after scraping
python3 scripts/job_summary.py --top 15
```

## Parameters

| Parameter | Description |
|-----------|-------------|
| `--keyword` | Search keyword (default "AI Agent") |
| `--city` | City (Chinese name or 9-digit code, default Shanghai). **Supports cities nationwide** (300+, incl. tier-3/4/5); city codes auto-sync from BOSS at runtime. See [`data/city_codes.json`](data/city_codes.json), or run `--list-cities`. An unrecognized city name now exits with an error instead of silently producing zero results |
| `--list-cities [keyword]` | Print the supported city list, optional keyword filter, e.g. `--list-cities 江` |
| `--pages` | Number of pages (max 15) |
| `--format` | json / csv; csv also exports list and detail CSVs |
| `--detail` | Scrape detail-page JD (on by default) |
| `--no-detail` | Do not scrape detail pages |
| `--analysis` | Analysis report |
| `--merge FILE` | Merge existing data (deduped by job_id) |
| `--allow-dom-fallback` | Allow DOM extraction fallback when the API has no data; off by default, salaries may be unreliable |
| `--check` | Environment check (CDP + deps + login state) |
| `--smoke-test` | Run one real Chrome/CDP BOSS search API smoke test, writes no result files |
| `--setup-chrome` | One-shot launch of Chrome CDP (persistent isolated profile) |
| `--copy-login-state` | Manually import the main Chrome's Local State + cookie-related files into the isolated profile (never copied by default, on first run, or on repeated runs) |
| `--reset-chrome-profile` | Rebuild the dedicated BOSS Chrome profile; clears the login state inside this dedicated browser |
| `--no-wait-login` | With `--setup-chrome`, do not wait for login to finish |
| `--login-timeout` | Seconds to wait for login under `--setup-chrome` (default 300) |
| `--stop-chrome` | Close the dedicated BOSS CDP Chrome (matched precisely by the isolated profile; never touches your main Chrome) |
| `--close-chrome` | Auto-close the dedicated Chrome after a scrape finishes normally (off by default; not triggered on errors, so the login state is kept) |
| `--output` | List output path (default `~/.boss-zhipin-job-research/job-result/`) |
| `--detail-output` | Detail output path (default `~/.boss-zhipin-job-research/job-result/`) |
| `--cdp-port` | CDP port (default 9222) |
| `--scale/--salary/--experience/--degree` | Filters |

## Post-Scrape Summary & Prompt

`scripts/job_summary.py` only reads the already-scraped `boss_jobs_*.json` and `boss_details_*.json`, does simple aggregation, and produces a copy-paste prompt. It never reads your local résumé file, pulls in no PDF dependency, and never scores a person against a job.

```bash
# Read the newest boss_jobs_*.json under the default result dir and auto-match the same-timestamp or newest detail file
python3 scripts/job_summary.py

# Specify list and detail files
python3 scripts/job_summary.py \
  --input ~/.boss-zhipin-job-research/job-result/boss_jobs_20260625_1200.json \
  --details ~/.boss-zhipin-job-research/job-result/boss_details_20260625_1200.json \
  --top 15

# Only emit the prompt
python3 scripts/job_summary.py --prompt-only
```

After installing the package you can also use the entry command:

```bash
uv run boss-summary --top 15
```

The summary covers: salary ranges, experience requirements, degree requirements, regional distribution, top companies, skill tags, frequent JD terms. The prompt asks the model to use these stats to fill in résumé keywords, suggest project-story rewrite directions, and produce an interview-prep checklist — while explicitly instructing it not to fabricate experience.

## File Structure

```
boss-zhipin-job-research/
├── app.py                # Local Streamlit task UI
├── boss_app/             # SQLite, worker, AI parser, and Excel services
├── SKILL.md              # Codex Skill definition
├── README.md             # Chinese docs
├── README.en.md          # English docs
├── CHANGELOG.md
├── LICENSE
├── pyproject.toml
├── data/
│   └── city_codes.json   # Full city-code map
├── scripts/
│   ├── boss_cdp_raw.py   # CDP core + original CLI
│   └── job_summary.py    # Post-scrape summary + prompt
└── requirements.txt
```

## How It Works

This is a Chrome-CDP-based BOSS Zhipin crawler. Core flow:

1. Connect to an already-open Chrome via the Chrome DevTools Protocol (CDP)
2. Inject JS inside the BOSS Zhipin page that calls the search API via synchronous XHR
3. The API returns plaintext `salaryDesc`, avoiding reliance on font-obfuscated DOM salary text
4. The list API preserves `securityId` / `lid` context, carried into the detail page
5. Each page is written to disk immediately, deduped by `job_id`

DOM extraction is not used for the list by default, since DOM salaries may be hit by font-based obfuscation. Only when `--allow-dom-fallback` is explicitly passed will it fall back to DOM when the API returns no data.

For detail pages, the scraper only extracts a section containing the job-description heading. Full-page `body` text is diagnostic input for detecting login walls and navigation shells and is never written directly as a JD. If the page contains the login-to-view-full-content marker, the crawl fails explicitly and stops before truncated text, recruiter metadata, company sections, or recommended jobs can be saved as a complete JD.

`--input ... --analysis --no-detail` first loads `--detail-output`, then the `boss_details_*.json` with the same timestamp in the same dir as the input list, and finally the newest detail file under `~/.boss-zhipin-job-research/job-result`.

## Chrome Profile Security Policy

`--setup-chrome` uses a persistent isolated profile by default — it neither symlinks nor copies your main Chrome data. First launch and subsequent launches only create or reuse this dedicated profile:

- `~/.boss-zhipin-job-research/chrome-profile`

Without an explicit `--output` or `--detail-output`, scraping results are saved under:

- `~/.boss-zhipin-job-research/job-result`

On first use you must log in to BOSS Zhipin manually inside this dedicated Chrome. `--setup-chrome` waits for the login to finish and uses the search API to confirm it can get plaintext `salaryDesc` before returning. The session is stored inside the dedicated profile and survives reboots; re-running `--setup-chrome` does not wipe it and does not affect your main Chrome, Gmail, GitHub, or other accounts.

The `--check` command and worker preflight first initialize a real search-results page, then send one search-API probe from that same page context. This avoids results that differ from the user-visible search flow when wapi is requested directly from the site homepage. Each login-probe round sends one search request, rotates across keyword/city targets, and backs off from 3 seconds to at most 15 seconds. Probe requests count toward the same 500-request global budget. Logged-out sessions, empty probe samples, API restrictions, and malformed responses are reported separately. A confirmed restriction such as `code: 31` or `code: 37` ("您的环境存在异常" / abnormal environment) stops probing immediately instead of prompting for another login or continuing frequent retries. Unknown risk-control codes are also recognized as restrictions via message keywords (abnormal environment, too-frequent access, security check, etc.), so an authenticated session that is merely rate-limited is no longer misreported as a login failure.

The interactive login page opened by `--setup-chrome` is the only temporary page intentionally brought to the foreground. Temporary tabs used by environment checks, list/detail scraping, and the smoke test run in the background so automation does not repeatedly steal focus. “Background” here only means the tab is not activated; the dedicated Chrome still runs with a visible UI and can be opened manually for inspection.

If you really need to import the BOSS session from your main Chrome, run explicitly:

```bash
python3 scripts/boss_cdp_raw.py --setup-chrome --copy-login-state
```

`--copy-login-state` overwrites the corresponding cookie-related files inside the isolated profile on every run; do not pass this for daily launches. It only copies `Local State` and `Default/Cookies*`, `Default/Network/Cookies*`-style cookie database files — not password stores, history, extensions, or a full profile. To wipe the dedicated browser's login state:

```bash
python3 scripts/boss_cdp_raw.py --setup-chrome --reset-chrome-profile
```

### Tearing down when you're done

After a scrape/analysis finishes, the dedicated Chrome is **not** closed automatically (the login state is kept by default so you can run the next scrape right away). When you're sure you no longer need it, tear it down manually:

```bash
python3 scripts/boss_cdp_raw.py --stop-chrome
```

`--stop-chrome` only closes the Chrome process(es) that belong to the scraper's isolated profile (`--user-data-dir`). It **never** kills by port or process name, so it cannot accidentally take down your main Chrome, Gmail, GitHub, or other signed-in sessions.

If you'd rather have a particular scrape close the dedicated Chrome once it finishes normally, add `--close-chrome`:

```bash
python3 scripts/boss_cdp_raw.py --keyword "AI Agent" --city 上海 --pages 3 --close-chrome
```

`--close-chrome` is off by default, and it only fires on the **success path** of a completed scrape — login failures, crashes, and other early exits leave the Chrome running so the login state is preserved.

## License

MIT

## Friends

- [LINUX DO](https://linux.do/) — A sincere, friendly, and vibrant tech community. This project endorses and recommends it.

## Star History

[![Star History Chart](https://api.star-history.com/svg?repos=yeyeyeyeye-source/boss-zhipin-job-research&type=Date)](https://star-history.com/#yeyeyeyeye-source/boss-zhipin-job-research&Date)
