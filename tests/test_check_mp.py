from __future__ import annotations

import copy
import json
import unittest

from support import FIXTURES, load_script, run_script


check_mp = load_script("check_mp")


class CheckMpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.limits = check_mp.load_limits(check_mp.LIMITS_FILE)

    def findings_for(self, fixture: str):
        return check_mp.run(FIXTURES / fixture, None, None)

    def test_valid_article_has_no_findings(self):
        self.assertEqual([], self.findings_for("valid.md"))

    def test_external_markdown_and_bare_links_are_aggregated(self):
        findings = self.findings_for("external-links.md")
        links = [finding for finding in findings if finding.check == "link"]

        self.assertEqual(1, len(links))
        self.assertEqual(check_mp.ERROR, links[0].level)
        self.assertEqual(6, links[0].line)
        self.assertIn("2 处外部链接", links[0].message)

    def test_only_h1_is_reported_as_a_heading_error(self):
        headings = [
            finding
            for finding in self.findings_for("headings.md")
            if finding.check == "heading"
        ]

        self.assertEqual(1, len(headings))
        self.assertEqual(check_mp.ERROR, headings[0].level)
        self.assertEqual(6, headings[0].line)

    def test_wide_code_line_uses_display_width_and_source_line(self):
        code_findings = [
            finding
            for finding in self.findings_for("code-blocks.md")
            if finding.check == "code-width"
        ]

        self.assertEqual(1, len(code_findings))
        self.assertEqual(check_mp.ERROR, code_findings[0].level)
        self.assertEqual(9, code_findings[0].line)
        self.assertGreater(check_mp.display_width("中a"), len("中a"))

    def test_image_url_is_not_counted_as_external_link(self):
        findings = self.findings_for("images.md")

        self.assertFalse(any(finding.check == "link" for finding in findings))
        image_alt = [finding for finding in findings if finding.check == "image-alt"]
        self.assertEqual(1, len(image_alt))
        self.assertEqual(check_mp.WARNING, image_alt[0].level)
        self.assertEqual(8, image_alt[0].line)

    def test_title_digest_and_paragraph_levels_follow_configuration(self):
        limits = copy.deepcopy(self.limits)
        limits["limits"]["titleMaxChars"] = {"value": 4, "enforce": True}
        limits["limits"]["digestMaxChars"] = {"value": 4, "enforce": True}
        limits["limits"]["paragraphMaxChars"] = {"value": 4, "enforce": False}

        title = check_mp.check_title("12345", limits)
        digest = check_mp.check_digest("12345", limits)
        paragraph = [
            finding
            for finding in check_mp.check_body("12345", 0, limits)
            if finding.check == "paragraph"
        ]

        self.assertEqual(check_mp.ERROR, title[0].level)
        self.assertEqual(check_mp.ERROR, digest[0].level)
        self.assertEqual(check_mp.WARNING, paragraph[0].level)

    def test_front_matter_parser_preserves_body_line_offset(self):
        text = "---\ntitle: 测试\ndigest: 摘要\n---\n\n正文"
        meta, body, offset = check_mp.split_front_matter(text)

        self.assertEqual({"title": "测试", "digest": "摘要"}, meta)
        self.assertEqual("\n正文", body)
        self.assertEqual(4, offset)

    def test_json_cli_returns_error_exit_code_and_structured_findings(self):
        result = run_script(
            "check_mp", str(FIXTURES / "external-links.md"), "--json"
        )
        payload = json.loads(result.stdout)

        self.assertEqual(1, result.returncode)
        self.assertEqual(1, payload["errors"])
        self.assertEqual("link", payload["findings"][0]["check"])

    def test_missing_file_cli_returns_usage_error(self):
        result = run_script("check_mp", str(FIXTURES / "missing.md"))

        self.assertEqual(2, result.returncode)
        self.assertIn("找不到文件", result.stderr)


if __name__ == "__main__":
    unittest.main()
