#!/usr/bin/env python3
"""把 Markdown 套上模版，输出可直接粘进公众号编辑器的 HTML。

为什么不能用普通的 Markdown 转 HTML：

    公众号编辑器会剥掉 <style> 标签和所有 class 属性，只保留元素上的
    style="..." 内联声明。所以样式必须在生成时就编译进每一个标签，
    外链 CSS、<style> 块、class 选择器一律无效。

用法：
    python3 scripts/apply_template.py article.md --template policy-whitepaper
    python3 scripts/apply_template.py article.md -t tech-deepdive -o out.html
    python3 scripts/apply_template.py --list

只用标准库。Markdown 支持的是公众号真正用得上的子集，不是完整规范：
标题、段落、粗体、斜体、行内代码、链接、图片、有序/无序列表、引用、
围栏代码块、分隔线、表格。
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
from pathlib import Path

TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates"


# --------------------------------------------------------------------------- 模版

def load_template(name: str) -> dict:
    path = TEMPLATE_DIR / name / "template.json"
    if not path.exists():
        available = ", ".join(sorted(list_templates())) or "（无）"
        raise SystemExit(f"找不到模版 {name}。可用：{available}")
    return json.loads(path.read_text(encoding="utf-8"))


def list_templates() -> list[str]:
    if not TEMPLATE_DIR.exists():
        return []
    return [p.name for p in TEMPLATE_DIR.iterdir() if (p / "template.json").exists()]


def style_of(template: dict, key: str) -> str:
    """取某个元素的样式串，找不到就返回空。

    空样式也照常输出标签，只是不带 style 属性——模版没定义某个元素时，
    内容不该消失。
    """
    return template.get("styles", {}).get(key, "").strip()


def tag(name: str, template: dict, style_key: str, content: str, extra: str = "") -> str:
    style = style_of(template, style_key)
    attrs = f' style="{html.escape(style, quote=True)}"' if style else ""
    if extra:
        attrs += " " + extra
    return f"<{name}{attrs}>{content}</{name}>"


# --------------------------------------------------------------------------- 行内

def render_inline(text: str, template: dict) -> str:
    """处理行内标记。

    顺序有讲究：先把代码片段抠出来占位，避免代码里的 * 和 _ 被当成强调；
    最后再填回去。
    """
    placeholders: list[str] = []

    def stash(rendered: str) -> str:
        placeholders.append(rendered)
        return f"\x00{len(placeholders) - 1}\x00"

    # 行内代码最先，它内部的一切都不再解析
    def on_code(match: re.Match) -> str:
        return stash(tag("code", template, "code_inline", html.escape(match.group(1))))

    text = re.sub(r"`([^`]+)`", on_code, text)

    # 图片要在链接之前，否则 ![alt](src) 的尾部会被当成链接
    def on_image(match: re.Match) -> str:
        alt = html.escape(match.group(1), quote=True)
        src = html.escape(match.group(2), quote=True)
        style = style_of(template, "img")
        attrs = f' style="{html.escape(style, quote=True)}"' if style else ""
        figure = f'<img src="{src}" alt="{alt}"{attrs} />'
        if alt:
            caption = tag("figcaption", template, "figcaption", html.escape(alt))
            figure = tag("figure", template, "figure", figure + caption)
        return stash(figure)

    text = re.sub(r"!\[([^\]]*)\]\(([^)]+)\)", on_image, text)

    def on_link(match: re.Match) -> str:
        label = html.escape(match.group(1))
        href = match.group(2)
        # 公众号正文里的链接不可点击。渲染成普通强调文字，并把地址原样留在后面，
        # 免得读者以为能点。真正要给的链接放「阅读原文」。
        rendered = tag("span", template, "link", label)
        if href.startswith(("http://", "https://")):
            rendered += tag("span", template, "link_url", f"（{html.escape(href)}）")
        return stash(rendered)

    text = re.sub(r"\[([^\]]*)\]\(([^)]+)\)", on_link, text)

    text = html.escape(text)

    text = re.sub(r"\*\*([^*]+)\*\*",
                  lambda m: tag("strong", template, "strong", m.group(1)), text)
    text = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)",
                  lambda m: tag("em", template, "em", m.group(1)), text)

    for index, rendered in enumerate(placeholders):
        text = text.replace(f"\x00{index}\x00", rendered)
    return text


# --------------------------------------------------------------------------- 块级

def split_front_matter(text: str) -> tuple[dict, str]:
    if not text.startswith("---"):
        return {}, text
    lines = text.splitlines()
    for index in range(1, len(lines)):
        if lines[index].strip() in {"---", "..."}:
            meta = {}
            for raw in lines[1:index]:
                if ":" in raw and not raw.lstrip().startswith("#"):
                    key, _, value = raw.partition(":")
                    meta[key.strip()] = value.strip().strip("'\"")
            return meta, "\n".join(lines[index + 1:])
    return {}, text


def render_code_block(lines: list[str], template: dict) -> str:
    body = html.escape("\n".join(lines))
    inner = tag("code", template, "code_block_text", body)
    return tag("pre", template, "code_block", inner)


def render_table(rows: list[str], template: dict) -> str:
    cells = [[c.strip() for c in row.strip().strip("|").split("|")] for row in rows]
    if len(cells) < 2:
        return ""
    header, body = cells[0], cells[2:]  # cells[1] 是 |---|---| 分隔行

    head_html = "".join(tag("th", template, "th", render_inline(c, template)) for c in header)
    out = tag("tr", template, "tr", head_html)
    for row in body:
        row_html = "".join(tag("td", template, "td", render_inline(c, template)) for c in row)
        out += tag("tr", template, "tr", row_html)
    return tag("table", template, "table", out)


def render_markdown(text: str, template: dict) -> str:
    lines = text.splitlines()
    out: list[str] = []
    index = 0
    total = len(lines)

    while index < total:
        line = lines[index]
        stripped = line.strip()

        if not stripped:
            index += 1
            continue

        # 围栏代码块
        if stripped.startswith("```"):
            index += 1
            block: list[str] = []
            while index < total and not lines[index].strip().startswith("```"):
                block.append(lines[index])
                index += 1
            index += 1
            out.append(render_code_block(block, template))
            continue

        # 表格
        if stripped.startswith("|") and index + 1 < total and re.match(
                r"^\|[\s:|-]+\|$", lines[index + 1].strip()):
            rows = []
            while index < total and lines[index].strip().startswith("|"):
                rows.append(lines[index])
                index += 1
            out.append(render_table(rows, template))
            continue

        # 分隔线
        if re.match(r"^(\*{3,}|-{3,}|_{3,})$", stripped):
            style = style_of(template, "hr")
            attrs = f' style="{html.escape(style, quote=True)}"' if style else ""
            out.append(f"<hr{attrs} />")
            index += 1
            continue

        # 标题
        heading = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if heading:
            level = len(heading.group(1))
            # 文章标题在公众号后台单独填，正文里的 H1 会重复一遍，降级为 H2。
            level = max(level, 2)
            out.append(tag(f"h{min(level, 4)}", template, f"h{min(level, 4)}",
                           render_inline(heading.group(2), template)))
            index += 1
            continue

        # 引用
        if stripped.startswith(">"):
            quoted = []
            while index < total and lines[index].strip().startswith(">"):
                quoted.append(lines[index].strip().lstrip(">").strip())
                index += 1
            inner = tag("p", template, "blockquote_text",
                        render_inline(" ".join(quoted), template))
            out.append(tag("blockquote", template, "blockquote", inner))
            continue

        # 列表
        list_match = re.match(r"^([-*+]|\d+\.)\s+(.*)$", stripped)
        if list_match:
            ordered = bool(re.match(r"^\d+\.$", list_match.group(1)))
            items = []
            while index < total:
                item = re.match(r"^([-*+]|\d+\.)\s+(.*)$", lines[index].strip())
                if not item:
                    break
                items.append(tag("li", template, "li",
                                 render_inline(item.group(2), template)))
                index += 1
            name = "ol" if ordered else "ul"
            out.append(tag(name, template, name, "".join(items)))
            continue

        # 段落：连续非空行合并
        paragraph = []
        while index < total and lines[index].strip() and not re.match(
                r"^(#{1,6}\s|>|```|\||[-*+]\s|\d+\.\s|(\*{3,}|-{3,}|_{3,})$)",
                lines[index].strip()):
            paragraph.append(lines[index].strip())
            index += 1
        if paragraph:
            out.append(tag("p", template, "p",
                           render_inline(" ".join(paragraph), template)))
        else:
            index += 1

    return "".join(out)


# --------------------------------------------------------------------------- 输出

def build_document(body: str, template: dict, title: str | None, standalone: bool) -> str:
    section = tag("section", template, "body", body)

    if not standalone:
        return section

    # 独立预览页。这一层只用于浏览器查看，粘进公众号时不需要，
    # 因为公众号只认元素上的内联样式。
    name = html.escape(template.get("name", ""))
    page_title = html.escape(title or name)
    return (
        "<!doctype html>\n"
        '<html lang="zh-CN"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{page_title}</title>"
        "</head>"
        '<body style="margin:0;padding:24px 0;background:#e9e9e9;">'
        '<div style="max-width:677px;margin:0 auto;background:#ffffff;'
        'padding:20px 16px;box-shadow:0 1px 6px rgba(0,0,0,.12);">'
        f"{section}"
        "</div></body></html>"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="给 Markdown 套公众号模版")
    parser.add_argument("file", nargs="?", type=Path, help="Markdown 文件")
    parser.add_argument("-t", "--template", help="模版 id")
    parser.add_argument("-o", "--output", type=Path, help="输出文件，默认打印到 stdout")
    parser.add_argument("--list", action="store_true", help="列出可用模版")
    parser.add_argument("--standalone", action="store_true",
                        help="输出带模拟手机宽度的完整预览页（仅用于浏览器查看）")
    args = parser.parse_args()

    if args.list:
        names = sorted(list_templates())
        if not names:
            print("还没有模版")
            return 0
        for name in names:
            meta = load_template(name)
            best = "、".join(meta.get("bestFor", []))
            print(f"  {name:<22} {meta.get('name','')}  适合：{best}")
        return 0

    if not args.file or not args.template:
        parser.error("需要指定 Markdown 文件和 --template（或用 --list 查看模版）")
    if not args.file.exists():
        print(f"找不到文件：{args.file}", file=sys.stderr)
        return 2

    template = load_template(args.template)
    meta, markdown = split_front_matter(args.file.read_text(encoding="utf-8"))
    body = render_markdown(markdown, template)
    document = build_document(body, template, meta.get("title"), args.standalone)

    if args.output:
        args.output.write_text(document, encoding="utf-8")
        print(f"已写入 {args.output}")
        if not args.standalone:
            print("在浏览器里打开，全选复制，粘进公众号编辑器即可。")
    else:
        print(document)
    return 0


if __name__ == "__main__":
    sys.exit(main())
