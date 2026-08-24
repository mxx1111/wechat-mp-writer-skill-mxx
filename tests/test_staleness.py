from __future__ import annotations

import datetime
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from support import load_script, run_script


check_staleness = load_script("check_staleness")


def limits_data(root_date: str, items: dict, threshold: int = 180) -> dict:
    return {
        "lastVerified": root_date,
        "staleness": {
            "thresholdDays": threshold,
            "rationale": "测试阈值",
        },
        "verifyAgainst": "https://example.com/platform",
        "limits": items,
    }


def limit(last_verified=None, enforce=True) -> dict:
    item = {
        "value": 64,
        "unit": "字符",
        "enforce": enforce,
        "source": "https://example.com/limit",
    }
    if last_verified is not None:
        item["lastVerified"] = last_verified
    return item


class StalenessTests(unittest.TestCase):
    def test_parse_date_accepts_iso_date_and_rejects_invalid_values(self):
        self.assertEqual(
            datetime.date(2026, 8, 24), check_staleness.parse_date("2026-08-24")
        )
        self.assertIsNone(check_staleness.parse_date("2026/08/24"))
        self.assertIsNone(check_staleness.parse_date(None))

    def test_age_equal_to_threshold_is_not_stale(self):
        today = datetime.date(2026, 8, 24)
        verified = (today - datetime.timedelta(days=180)).isoformat()
        data = limits_data(verified, {"hard": limit(verified, True)})

        threshold, rationale, reports = check_staleness.inspect_staleness(
            data, current_date=today
        )

        self.assertEqual(180, threshold)
        self.assertEqual("测试阈值", rationale)
        self.assertTrue(all(not report.is_stale for report in reports))
        self.assertTrue(
            all(report.severity == check_staleness.SEVERITY_INFO for report in reports)
        )

    def test_stale_items_are_classified_by_enforcement(self):
        today = datetime.date(2026, 8, 24)
        stale = (today - datetime.timedelta(days=181)).isoformat()
        data = limits_data(
            today.isoformat(),
            {
                "hard": limit(stale, True),
                "soft": limit(stale, False),
            },
        )

        _, _, reports = check_staleness.inspect_staleness(data, current_date=today)
        by_target = {report.target: report for report in reports}

        self.assertEqual(
            check_staleness.SEVERITY_CRITICAL,
            by_target["limits.hard"].severity,
        )
        self.assertEqual(
            check_staleness.SEVERITY_WARNING,
            by_target["limits.soft"].severity,
        )

    def test_missing_and_invalid_dates_are_reported(self):
        data = limits_data(
            "not-a-date",
            {
                "hard": limit(None, True),
                "soft": limit("also-invalid", False),
            },
        )

        _, _, reports = check_staleness.inspect_staleness(
            data, current_date=datetime.date(2026, 8, 24)
        )
        by_target = {report.target: report for report in reports}

        self.assertTrue(by_target["file"].is_invalid)
        self.assertEqual(
            check_staleness.SEVERITY_CRITICAL,
            by_target["limits.hard"].severity,
        )
        self.assertEqual(
            check_staleness.SEVERITY_WARNING,
            by_target["limits.soft"].severity,
        )

    def test_override_threshold_changes_stale_decision(self):
        data = limits_data(
            "2026-08-01", {"hard": limit("2026-08-01", True)}, threshold=180
        )

        threshold, _, reports = check_staleness.inspect_staleness(
            data,
            override_threshold=10,
            current_date=datetime.date(2026, 8, 24),
        )

        self.assertEqual(10, threshold)
        self.assertTrue(all(report.is_stale for report in reports))

    def test_github_summary_contains_stale_counts_and_target(self):
        data = limits_data(
            "2026-08-24", {"hard": limit("2025-01-01", True)}
        )
        threshold, rationale, reports = check_staleness.inspect_staleness(
            data, current_date=datetime.date(2026, 8, 24)
        )

        with tempfile.TemporaryDirectory() as temporary_directory:
            summary = Path(temporary_directory) / "summary.md"
            with mock.patch.dict(os.environ, {"GITHUB_STEP_SUMMARY": str(summary)}):
                check_staleness.write_github_summary(threshold, rationale, reports)

            content = summary.read_text(encoding="utf-8")
            self.assertIn("强制拦截项 `1` 个", content)
            self.assertIn("`limits.hard`", content)

    def test_json_cli_and_fail_enforced_exit_code(self):
        data = limits_data(
            "2026-08-24", {"hard": limit("2025-01-01", True)}
        )

        with tempfile.TemporaryDirectory() as temporary_directory:
            config = Path(temporary_directory) / "limits.json"
            config.write_text(json.dumps(data), encoding="utf-8")
            result = run_script(
                "check_staleness",
                "--file",
                str(config),
                "--current-date",
                "2026-08-24",
                "--json",
                "--fail-enforced",
            )

        payload = json.loads(result.stdout)
        self.assertEqual(1, result.returncode)
        self.assertEqual(1, payload["criticalCount"])
        self.assertEqual(1, payload["staleCount"])

    def test_missing_config_cli_returns_read_error(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            missing = Path(temporary_directory) / "does-not-exist.json"
            result = run_script("check_staleness", "--file", str(missing))

        self.assertEqual(2, result.returncode)
        self.assertIn("读取配置文件失败", result.stderr)


if __name__ == "__main__":
    unittest.main()
