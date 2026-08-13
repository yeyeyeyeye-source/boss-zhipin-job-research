import tempfile
import unittest
from pathlib import Path
from unittest import mock
import sys

from boss_app.db import require_legacy_runtime_migrated
from boss_app.exporter import default_output_dir
from scripts import boss_cdp_raw as core


class RuntimeMigrationTests(unittest.TestCase):
    def test_default_path_refuses_to_hide_an_existing_legacy_tree(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            current = root / ".boss-zhipin-job-research"
            legacy = root / ".boss-zhipin-scraper"
            legacy.mkdir()

            with self.assertRaisesRegex(RuntimeError, "Move-Item"):
                require_legacy_runtime_migrated(
                    current / "boss_jobs.db",
                    default_path=current / "boss_jobs.db",
                    current_root=current,
                    legacy_root=legacy,
                )

    def test_explicit_custom_path_remains_available_during_migration(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            current = root / ".boss-zhipin-job-research"
            legacy = root / ".boss-zhipin-scraper"
            legacy.mkdir()

            require_legacy_runtime_migrated(
                legacy / "boss_jobs.db",
                default_path=current / "boss_jobs.db",
                current_root=current,
                legacy_root=legacy,
            )

    def test_default_path_refuses_when_old_and_new_trees_both_exist(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            current = root / ".boss-zhipin-job-research"
            legacy = root / ".boss-zhipin-scraper"
            current.mkdir()
            legacy.mkdir()
            (legacy / "boss_jobs.db").touch()

            with self.assertRaisesRegex(RuntimeError, "同时存在"):
                require_legacy_runtime_migrated(
                    current / "boss_jobs.db",
                    default_path=current / "boss_jobs.db",
                    current_root=current,
                    legacy_root=legacy,
                )

    def test_default_export_follows_the_selected_database_root(self):
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "custom-state" / "jobs.db"
            database = type("DatabasePath", (), {"path": database_path})()
            self.assertEqual(
                default_output_dir(database),
                database_path.parent / "job-result",
            )

    def test_chrome_and_result_defaults_share_the_same_migration_guard(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            current = root / ".boss-zhipin-job-research"
            legacy = root / ".boss-zhipin-scraper"
            legacy.mkdir()
            with mock.patch.object(core, "CURRENT_RUNTIME_ROOT", str(current)), \
                    mock.patch.object(core, "LEGACY_RUNTIME_ROOT", str(legacy)):
                with self.assertRaisesRegex(RuntimeError, "Move-Item"):
                    core.require_legacy_runtime_migrated()

    def test_explicit_input_analysis_without_details_skips_default_guard(self):
        with tempfile.TemporaryDirectory() as directory:
            input_path = Path(directory) / "jobs.json"
            input_path.write_text('{"jobs": []}', encoding="utf-8")
            with mock.patch.object(sys, "argv", [
                "boss_cdp_raw.py", "--input", str(input_path),
                "--analysis", "--no-detail",
            ]), mock.patch.object(
                core, "require_legacy_runtime_migrated",
            ) as migration_guard, mock.patch.object(
                core, "require_runtime_dependencies", return_value=True,
            ), mock.patch.object(core, "analyze"):
                core.main()

            migration_guard.assert_not_called()


if __name__ == "__main__":
    unittest.main()
