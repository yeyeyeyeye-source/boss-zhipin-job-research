# AGENTS.md

## Project boundary

This project connects to the user's own logged-in dedicated Chrome through CDP to collect public BOSS直聘 job listings for personal job-search analysis. Do not add proxies, multiple-account automation, CAPTCHA bypasses, fingerprint evasion, or automatic access-restriction retries.

## Safety invariants

- A new session is read-only until the user explicitly authorizes a real BOSS run.
- Never commit `.env`, SQLite databases, job exports, logs, or Chrome profiles.
- `code: 37`, HTTP 403/429, or an explicit restriction page must stop later BOSS requests, save progress, and enter `waiting_for_access`.
- Access recovery requires a new explicit user confirmation; never bypass it with `--refresh`.
- Search summaries never replace a validated complete JD.
- Preserve job identity deduplication, Run request budgets, leases, heartbeats, and frozen export snapshots.

## Code map

- `scripts/boss_cdp_raw.py`: CDP, list/detail collection, Chrome lifecycle, legacy CLI.
- `boss_app/`: SQLite, Strategy Run orchestration, collector, AI parsing, worker, and Excel export.
- `app.py`: Streamlit task UI; it must not block on collection.
- `tests/`: offline `unittest` suite using mocks and temporary data.

## Development rules

- Python 3.10+; use `uv.lock` for reproducible dependency resolution.
- Keep version surfaces synchronized in `scripts/boss_cdp_raw.py`, `pyproject.toml`, `SKILL.md`, and `README.md`.
- No bare `except:`; preserve existing error semantics.
- User-visible behavior changes require synchronized Chinese/English README and CHANGELOG updates.
- Preserve the original CLI and public interfaces unless the change explicitly requires a compatibility break.

## Verification

```powershell
python -m unittest discover -s tests -v
python -m compileall -q scripts/boss_cdp_raw.py app.py boss_app
uv lock --check --offline
uv pip check --python .venv\Scripts\python.exe
```

Final project verification must include adversarial multi-agent review. Tests remain offline and must not access real BOSS, operate the user's Chrome, start workers, or write the formal database.
