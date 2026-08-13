# Legacy reuse audit

Audit date: 2026-08-13.

## What was inherited

The public repository root commit `e24641f` imported 47 files from the v2.6
lineage of `eatmoreduck/boss-zhipin-scraper`. A byte comparison against the
available v2.6 source artifact found 29 identical files at import time; 24 were
still unchanged when this audit began.

That history is retained under the MIT License. Rewriting working collection,
SQLite, export, and test code merely to make its bytes different would add risk
without changing ownership or behavior, so correct implementation is retained
and covered by the current test suite.

## What is no longer inherited as current authority

The following surfaces now use the current project and maintainer identity:

- package metadata, lockfile root package, Skill name, and agent prompt;
- repository, clone, installation, and issue links;
- local database, Chrome profile, logs, and export defaults;
- Chinese and English README examples and directory maps;
- contribution rules and the active-agent entry document;
- release notes and source-ownership wording.

Old issue numbers, old maintainer voice, stale handoff claims, and historical
workflow artifacts are not current project rules.

## What remains intentionally historical

- the original copyright notice required by the MIT License;
- the published Git commits, which provide provenance rather than authority;
- references in this audit and `provenance.md` that identify the imported
  lineage accurately.

All current behavior must be derived from the canonical repository's `main`
branch, current documentation, code, tests, and runtime schema.
