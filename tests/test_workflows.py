from __future__ import annotations

import unittest

from support import ROOT


class WorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
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


if __name__ == "__main__":
    unittest.main()
