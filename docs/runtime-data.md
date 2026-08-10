# Local runtime data

Source code and private runtime data are intentionally separated. By default, runtime data lives under:

```text
~/.boss-zhipin-scraper/
├── boss_jobs.db            # Tasks, jobs, Strategy Runs, checkpoints
├── job-result/             # Incremental JSON and Excel exports
├── logs/                   # Worker logs
├── live-runs/              # Optional isolated run data
└── chrome-profile/         # Dedicated Chrome login profile
```

None of these files belongs in Git. SQLite creates `-wal` and `-shm` files while it is open; they are runtime companions, not source files.

On the same computer, a new checkout continues to use the existing default database. On another computer, the application creates a new empty database and schema on first use.

## Backup

Stop active workers and the dedicated Chrome before backup. Copy the entire runtime directory to private storage. Do not publish the backup or attach it to a GitHub issue.

## Restore

Restore the private directory to the same user's home directory before starting the application. Keep the database and its matching runtime files together. Never overwrite a newer working database without a separate verified backup.
