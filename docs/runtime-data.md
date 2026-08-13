# Local runtime data

Source code and private runtime data are intentionally separated. By default, runtime data lives under:

```text
~/.boss-zhipin-job-research/
├── boss_jobs.db            # Tasks, jobs, Strategy Runs, checkpoints
├── job-result/             # Incremental JSON and Excel exports
├── logs/                   # Worker logs
├── live-runs/              # Optional isolated run data
└── chrome-profile/         # Dedicated Chrome login profile
```

None of these files belongs in Git. SQLite creates `-wal` and `-shm` files while it is open; they are runtime companions, not source files.

## Upgrade from the legacy directory

Close every program using files in the old runtime tree, then rename the whole
`~/.boss-zhipin-scraper` directory to `~/.boss-zhipin-job-research` on the same
volume. Keep the database, WAL/SHM companions, Chrome profile, logs, and result
files together. Default entry points fail safely when only the old tree exists;
they do not create a new empty state over it. If both trees exist, they stop and
require manual reconciliation instead of overwriting either tree.

On the same computer, a new checkout continues to use the existing default database. On another computer, the application creates a new empty database and schema on first use.

## Backup

Stop active workers and the dedicated Chrome before backup. Copy the entire runtime directory to private storage. Do not publish the backup or attach it to a GitHub issue.

## Restore

Restore the private directory to the same user's home directory before starting the application. Keep the database and its matching runtime files together. Never overwrite a newer working database without a separate verified backup.
