from __future__ import annotations

import unittest

from support import ROOT


class WorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ci_workflow = (
            ROOT / ".github" / "workflows" / "ci.yml"
        ).read_text(encoding="utf-8")
        cls.staleness_workflow = (
            ROOT / ".github" / "workflows" / "staleness-check.yml"
        ).read_text(encoding="utf-8")

    def test_push_and_pull_request_runs_fail_on_stale_enforced_limits(self):
        self.assertIn(
            "github.event_name == 'push' || github.event_name == 'pull_request'",
            self.staleness_workflow,
        )
        self.assertIn(
            "python3 scripts/check_staleness.py --fail-enforced",
            self.staleness_workflow,
        )

    def test_issue_creation_only_uses_existing_default_label(self):
        self.assertIn("labels: ['documentation']", self.staleness_workflow)
        self.assertNotIn("'maintenance'", self.staleness_workflow)

    def test_ci_scans_full_history_with_redacted_gitleaks_output(self):
        self.assertIn("fetch-depth: 0", self.ci_workflow)
        self.assertIn("sha256sum --check --status", self.ci_workflow)
        self.assertIn("gitleaks\" git . --no-banner --redact", self.ci_workflow)

    def test_ci_validates_all_templates(self):
        self.assertIn(
            "python scripts/wechat_mp.py validate-template",
            self.ci_workflow,
        )

    def test_ci_smoke_tests_only_files_present_in_repository_archive(self):
        self.assertIn("git archive HEAD | tar -x", self.ci_workflow)
        self.assertIn(
            "--template long-term-care-policy",
            self.ci_workflow,
        )


if __name__ == "__main__":
    unittest.main()
