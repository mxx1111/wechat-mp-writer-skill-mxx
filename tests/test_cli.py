from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from support import FIXTURES, run_script


class UnifiedCliTests(unittest.TestCase):
    def test_help_lists_all_pipeline_commands(self):
        result = run_script("wechat_mp", "--help")

        self.assertEqual(0, result.returncode)
        for command in (
            "check",
            "render",
            "build",
            "validate-template",
            "doctor",
        ):
            self.assertIn(command, result.stdout)

    def test_check_preserves_preflight_exit_codes_and_json_output(self):
        valid = run_script("wechat_mp", "check", str(FIXTURES / "valid.md"))
        invalid = run_script(
            "wechat_mp",
            "check",
            str(FIXTURES / "external-links.md"),
            "--json",
        )
        payload = json.loads(invalid.stdout)

        self.assertEqual(0, valid.returncode)
        self.assertIn("没有发现问题", valid.stdout)
        self.assertEqual(1, invalid.returncode)
        self.assertEqual(1, payload["errors"])
        self.assertEqual("link", payload["findings"][0]["check"])

    def test_missing_article_and_template_are_input_errors(self):
        missing_article = FIXTURES / "missing-for-unified-cli.md"
        commands = (
            ("check", str(missing_article)),
            (
                "render",
                str(missing_article),
                "--template",
                "policy-whitepaper",
            ),
            (
                "build",
                str(missing_article),
                "--template",
                "policy-whitepaper",
            ),
            (
                "render",
                str(FIXTURES / "valid.md"),
                "--template",
                "missing-template-for-test",
            ),
        )

        for command in commands:
            with self.subTest(command=command[0]):
                result = run_script("wechat_mp", *command)
                self.assertEqual(2, result.returncode)
                self.assertTrue(result.stderr.startswith("✗"))

    def test_render_writes_fragment_and_standalone_preview(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            fragment = root / "fragment.html"
            preview = root / "preview.html"
            unchecked = root / "unchecked.html"

            fragment_result = run_script(
                "wechat_mp",
                "render",
                str(FIXTURES / "valid.md"),
                "--template",
                "policy-whitepaper",
                "--output",
                str(fragment),
            )
            preview_result = run_script(
                "wechat_mp",
                "render",
                str(FIXTURES / "valid.md"),
                "--template",
                "tech-deepdive",
                "--standalone",
                "--output",
                str(preview),
            )
            unchecked_result = run_script(
                "wechat_mp",
                "render",
                str(FIXTURES / "external-links.md"),
                "--template",
                "policy-whitepaper",
                "--output",
                str(unchecked),
            )

            self.assertEqual(0, fragment_result.returncode)
            self.assertEqual(0, preview_result.returncode)
            self.assertEqual(0, unchecked_result.returncode)
            self.assertTrue(fragment.read_text(encoding="utf-8").startswith("<section"))
            self.assertTrue(
                preview.read_text(encoding="utf-8").startswith("<!doctype html>")
            )
            self.assertTrue(unchecked.exists())

        stdout_result = run_script(
            "wechat_mp",
            "render",
            str(FIXTURES / "valid.md"),
            "--template",
            "policy-whitepaper",
        )
        self.assertEqual(0, stdout_result.returncode)
        self.assertTrue(stdout_result.stdout.startswith("<section"))

    def test_build_writes_output_when_preflight_passes_or_only_warns(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            valid_output = root / "valid.html"
            warning_output = root / "warning.html"

            valid = run_script(
                "wechat_mp",
                "build",
                str(FIXTURES / "valid.md"),
                "--template",
                "policy-whitepaper",
                "--output",
                str(valid_output),
            )
            warning = run_script(
                "wechat_mp",
                "build",
                str(FIXTURES / "code-blocks.md"),
                "--template",
                "tech-deepdive",
                "--output",
                str(warning_output),
            )

            self.assertEqual(0, valid.returncode)
            self.assertEqual(0, warning.returncode)
            self.assertTrue(valid_output.exists())
            self.assertTrue(warning_output.exists())
            self.assertIn("0 个错误，1 个提示", warning.stdout)

    def test_build_does_not_write_output_when_preflight_fails(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            output = root / "blocked.html"
            result = run_script(
                "wechat_mp",
                "build",
                str(FIXTURES / "external-links.md"),
                "--template",
                "policy-whitepaper",
                "--output",
                str(output),
            )

            self.assertEqual(1, result.returncode)
            self.assertFalse(output.exists())
            self.assertIn("不会生成 HTML", result.stdout)

            existing = root / "existing.html"
            existing.write_text("keep this output", encoding="utf-8")
            overwrite = run_script(
                "wechat_mp",
                "build",
                str(FIXTURES / "external-links.md"),
                "--template",
                "policy-whitepaper",
                "--output",
                str(existing),
            )
            self.assertEqual(1, overwrite.returncode)
            self.assertEqual("keep this output", existing.read_text(encoding="utf-8"))

    def test_build_defaults_to_html_next_to_article(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            article = Path(temporary_directory) / "article.md"
            article.write_text(
                (FIXTURES / "valid.md").read_text(encoding="utf-8"),
                encoding="utf-8",
            )

            result = run_script(
                "wechat_mp",
                "build",
                str(article),
                "--template",
                "policy-whitepaper",
            )

            self.assertEqual(0, result.returncode)
            self.assertTrue(article.with_suffix(".html").exists())

    def test_render_and_build_refuse_to_overwrite_source_markdown(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            article = Path(temporary_directory) / "article.md"
            original = (FIXTURES / "valid.md").read_text(encoding="utf-8")
            article.write_text(original, encoding="utf-8")

            for command in ("render", "build"):
                with self.subTest(command=command):
                    result = run_script(
                        "wechat_mp",
                        command,
                        str(article),
                        "--template",
                        "policy-whitepaper",
                        "--output",
                        str(article),
                    )
                    self.assertEqual(2, result.returncode)
                    self.assertIn("不能覆盖原 Markdown", result.stderr)
                    self.assertEqual(original, article.read_text(encoding="utf-8"))

    def test_validate_template_accepts_builtins_and_rejects_invalid_directory(self):
        builtins = run_script("wechat_mp", "validate-template", "--json")
        builtin_payload = json.loads(builtins.stdout)

        self.assertEqual(0, builtins.returncode)
        self.assertGreaterEqual(builtin_payload["templates"], 2)
        self.assertEqual(0, builtin_payload["errors"])

        with tempfile.TemporaryDirectory() as temporary_directory:
            template_dir = Path(temporary_directory) / "Bad Template"
            template_dir.mkdir()
            (template_dir / "template.json").write_text(
                json.dumps(
                    {
                        "id": "wrong-id",
                        "name": "",
                        "description": "测试",
                        "bestFor": [],
                        "palette": {},
                        "notes": [],
                        "styles": {"unknown-style": "color:red;"},
                    }
                ),
                encoding="utf-8",
            )
            invalid = run_script(
                "wechat_mp",
                "validate-template",
                str(template_dir),
                "--json",
            )

        invalid_payload = json.loads(invalid.stdout)
        self.assertEqual(1, invalid.returncode)
        self.assertGreater(invalid_payload["errors"], 0)
        fields = {
            finding["field"]
            for result in invalid_payload["results"]
            for finding in result["findings"]
        }
        self.assertIn("id", fields)
        self.assertIn("styles.body", fields)

    def test_validate_template_missing_target_is_an_input_error(self):
        result = run_script(
            "wechat_mp", "validate-template", "missing-template-for-test"
        )

        self.assertEqual(2, result.returncode)
        self.assertIn("找不到模版", result.stderr)

    def test_validate_template_reports_directory_without_configuration(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            template_dir = Path(temporary_directory) / "empty-template"
            template_dir.mkdir()
            result = run_script(
                "wechat_mp",
                "validate-template",
                str(template_dir),
                "--json",
            )

        payload = json.loads(result.stdout)
        self.assertEqual(1, result.returncode)
        self.assertEqual("template.json", payload["results"][0]["findings"][0]["field"])

    def test_doctor_reports_repository_health_in_json(self):
        result = run_script("wechat_mp", "doctor", "--json")
        payload = json.loads(result.stdout)

        self.assertEqual(0, result.returncode)
        self.assertTrue(payload["ok"])
        self.assertEqual(0, payload["errors"])
        names = {check["name"] for check in payload["checks"]}
        self.assertIn("python", names)
        self.assertIn("platform-limits", names)
        self.assertIn("templates", names)


if __name__ == "__main__":
    unittest.main()
