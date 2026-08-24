from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

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

    def test_platform_facts_are_enforced_and_experience_limits_are_advisory(self):
        configured_limits = self.limits["limits"]

        self.assertTrue(configured_limits["titleMaxChars"]["enforce"])
        self.assertTrue(configured_limits["digestMaxChars"]["enforce"])
        self.assertFalse(configured_limits["codeBlockMaxLineWidth"]["enforce"])
        self.assertFalse(configured_limits["paragraphMaxChars"]["enforce"])
        self.assertFalse(configured_limits["imageMaxSizeMB"]["enforce"])

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

    def test_heading_line_is_still_checked_for_external_links(self):
        links = [
            finding
            for finding in self.findings_for("headings.md")
            if finding.check == "link"
        ]

        self.assertEqual(1, len(links))
        self.assertEqual(check_mp.ERROR, links[0].level)
        self.assertEqual(8, links[0].line)
        self.assertIn("2 处外部链接", links[0].message)

    def test_wide_code_line_uses_display_width_and_source_line(self):
        code_findings = [
            finding
            for finding in self.findings_for("code-blocks.md")
            if finding.check == "code-width"
        ]

        self.assertEqual(1, len(code_findings))
        self.assertEqual(check_mp.WARNING, code_findings[0].level)
        self.assertEqual(9, code_findings[0].line)
        self.assertGreater(check_mp.display_width("中a"), len("中a"))

    def test_image_url_is_not_counted_as_external_link(self):
        findings = self.findings_for("images.md")

        self.assertFalse(any(finding.check == "link" for finding in findings))
        image_alt = [finding for finding in findings if finding.check == "image-alt"]
        self.assertEqual(1, len(image_alt))
        self.assertEqual(check_mp.WARNING, image_alt[0].level)
        self.assertEqual(8, image_alt[0].line)

    def test_oversized_local_image_is_reported_relative_to_article(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            image = root / "oversized.png"
            with image.open("wb") as file:
                file.seek(10 * 1024 * 1024)
                file.write(b"x")
            (root / "small.png").write_bytes(b"small")
            article = root / "article.md"
            article.write_text(
                "![大图](oversized.png)\n![小图](small.png)", encoding="utf-8"
            )

            findings = check_mp.run(article, "图片大小测试", "图片大小检查摘要")

        image_sizes = [
            finding for finding in findings if finding.check == "image-size"
        ]
        self.assertEqual(1, len(image_sizes))
        self.assertEqual(check_mp.WARNING, image_sizes[0].level)
        self.assertEqual(1, image_sizes[0].line)
        self.assertIn("10 MB", image_sizes[0].message)

    def test_local_image_resolver_decodes_paths_and_skips_remote_sources(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            article = Path(temporary_directory) / "articles" / "article.md"
            expected = article.resolve().parent / "images" / "封面 图.png"

            resolved = check_mp.resolve_local_image(
                "images/%E5%B0%81%E9%9D%A2%20%E5%9B%BE.png", article
            )

        self.assertEqual(expected, resolved)
        self.assertIsNone(check_mp.resolve_local_image("cover.png", None))
        self.assertIsNone(check_mp.resolve_local_image("", article))
        for source in (
            "https://example.com/cover.png",
            "//cdn.example.com/cover.png",
            "data:image/png;base64,AAAA",
            "ftp://example.com/cover.png",
        ):
            with self.subTest(source=source):
                self.assertIsNone(check_mp.resolve_local_image(source, article))

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
