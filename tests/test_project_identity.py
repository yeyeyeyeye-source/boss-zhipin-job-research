import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROJECT = "boss-zhipin-job-research"
REPOSITORY = "https://github.com/yeyeyeyeye-source/boss-zhipin-job-research"


class ProjectIdentityTests(unittest.TestCase):
    def read(self, name):
        return (ROOT / name).read_text(encoding="utf-8")

    def test_metadata_uses_current_project_and_maintainer(self):
        pyproject = self.read("pyproject.toml")
        self.assertRegex(
            pyproject,
            re.compile(rf'^name = "{PROJECT}"$', re.MULTILINE),
        )
        self.assertIn('{ name = "yeyeyeyeye-source"', pyproject)
        self.assertIn(REPOSITORY, pyproject)

    def test_public_docs_and_skill_use_current_repository(self):
        for name in (
            "README.md", "README.en.md", "CONTRIBUTING.md", "SKILL.md",
            "agents/openai.yaml", "docs/architecture.md", "docs/runtime-data.md",
        ):
            with self.subTest(name=name):
                content = self.read(name)
                self.assertNotIn("boss-zhipin-scraper", content)
                self.assertNotIn("eatmoreduck", content)

        self.assertIn(REPOSITORY, self.read("README.md"))
        self.assertIn(REPOSITORY, self.read("README.en.md"))
        self.assertIn("name: boss-zhipin-job-research", self.read("SKILL.md"))

    def test_current_docs_do_not_inherit_old_issue_gate_or_author_voice(self):
        contributing = self.read("CONTRIBUTING.md")
        readme = self.read("README.md")
        self.assertNotIn("\u5148\u5f00 Issue \u518d\u5199\u4ee3\u7801", contributing)
        self.assertNotIn("\u539f\u4f5c\u8005\u660e\u786e\u767b\u5f55", readme)
        self.assertNotRegex(
            "\n".join((contributing, readme, self.read("README.en.md"))),
            r"(?<![A-Za-z])(?:issue\s*)?#(?:24|33)(?!\d)",
        )

    def test_license_preserves_origin_and_names_current_contributor(self):
        license_text = self.read("LICENSE")
        self.assertIn("Copyright (c) 2026 eatmoreduck", license_text)
        self.assertIn("Copyright (c) 2026 yeyeyeyeye-source", license_text)
        provenance = self.read("docs/provenance.md")
        self.assertIn("e24641f", provenance)
        self.assertIn("yeyeyeyeye-source/boss-zhipin-job-research", provenance)


if __name__ == "__main__":
    unittest.main()
