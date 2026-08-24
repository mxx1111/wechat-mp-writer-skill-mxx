from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from support import FIXTURES, ROOT, load_script, run_script

apply_template = load_script("apply_template")


class ApplyTemplateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.template = apply_template.load_template("policy-whitepaper")

    def render_fixture(self, fixture: str) -> str:
        text = (FIXTURES / fixture).read_text(encoding="utf-8")
        _, markdown = apply_template.split_front_matter(text)
        return apply_template.render_markdown(markdown, self.template)

    def test_valid_fixture_renders_supported_block_and_inline_elements(self):
        rendered = self.render_fixture("valid.md")

        self.assertIn("<h2", rendered)
        self.assertIn("<strong", rendered)
        self.assertIn("<em", rendered)
        self.assertIn("<code", rendered)
        self.assertIn("<figure", rendered)
        self.assertIn("<ul", rendered)

    def test_table_fixture_renders_header_and_body_cells(self):
        rendered = self.render_fixture("tables.md")

        self.assertIn("<table", rendered)
        self.assertEqual(2, rendered.count("<th"))
        self.assertEqual(4, rendered.count("<td"))
        self.assertIn("数据对比", rendered)

    def test_external_links_are_rendered_as_text_instead_of_anchors(self):
        rendered = self.render_fixture("external-links.md")

        self.assertNotIn("<a ", rendered)
        self.assertIn("官方文档", rendered)
        self.assertIn("https://example.com/docs", rendered)

    def test_inline_html_and_code_are_escaped(self):
        rendered = apply_template.render_inline(
            "<script> & `x<y` **重点**", self.template
        )

        self.assertNotIn("<script>", rendered)
        self.assertIn("&lt;script&gt;", rendered)
        self.assertIn("x&lt;y", rendered)
        self.assertIn("<strong", rendered)

    def test_fragment_and_standalone_documents_have_distinct_wrappers(self):
        fragment = apply_template.build_document(
            "<p>正文</p>", self.template, "标题 & 摘要", False
        )
        standalone = apply_template.build_document(
            "<p>正文</p>", self.template, "标题 & 摘要", True
        )

        self.assertTrue(fragment.startswith("<section"))
        self.assertNotIn("<!doctype html>", fragment)
        self.assertTrue(standalone.startswith("<!doctype html>"))
        self.assertIn("<title>标题 &amp; 摘要</title>", standalone)

    def test_every_template_can_render_its_sample_without_style_blocks(self):
        names = sorted(apply_template.list_templates())
        self.assertTrue({"policy-whitepaper", "tech-deepdive"}.issubset(names))

        for name in names:
            with self.subTest(template=name):
                template = apply_template.load_template(name)
                sample = ROOT / "templates" / name / "sample.md"
                if not sample.exists():
                    self.assertEqual(name, template["id"])
                    continue
                _, markdown = apply_template.split_front_matter(
                    sample.read_text(encoding="utf-8")
                )
                rendered = apply_template.build_document(
                    apply_template.render_markdown(markdown, template),
                    template,
                    None,
                    False,
                )
                self.assertEqual(name, template["id"])
                self.assertIn("style=", rendered)
                self.assertNotIn("<style", rendered)
                self.assertNotIn("class=", rendered)

    def test_cli_lists_templates_and_writes_output_file(self):
        listed = run_script("apply_template", "--list")
        self.assertEqual(0, listed.returncode)
        self.assertIn("policy-whitepaper", listed.stdout)
        self.assertIn("tech-deepdive", listed.stdout)

        with tempfile.TemporaryDirectory() as temporary_directory:
            output = Path(temporary_directory) / "output.html"
            result = run_script(
                "apply_template",
                str(FIXTURES / "valid.md"),
                "--template",
                "policy-whitepaper",
                "--output",
                str(output),
            )

            self.assertEqual(0, result.returncode)
            self.assertTrue(output.exists())
            self.assertTrue(output.read_text(encoding="utf-8").startswith("<section"))
            self.assertIn("已写入", result.stdout)

    def test_unknown_template_exits_with_available_names(self):
        with self.assertRaises(SystemExit) as raised:
            apply_template.load_template("missing-template")

        self.assertIn("policy-whitepaper", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
