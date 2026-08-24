#!/usr/bin/env python3
"""公众号发布前体检。

检查的是「这篇稿子放进公众号编辑器会不会出问题」，不评价写得好不好。
文笔、结构、观点由人和写作类 skill 负责，这里只管机器能判定的事。

用法：
    python3 scripts/check_mp.py article.md
    python3 scripts/check_mp.py article.md --title "标题" --digest "摘要"
    python3 scripts/check_mp.py article.md --json

标题和摘要也可以写在 Markdown 顶部的 YAML front matter 里：

    ---
    title: 标题写在这
    digest: 摘要写在这
    ---

退出码：有 error 返回 1，只有 warning 返回 0。CI 里可以直接用。

只用标准库，不需要安装任何东西。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import unquote, urlsplit

LIMITS_FILE = (
    Path(__file__).resolve().parent.parent / "references" / "platform-limits.json"
)

ERROR = "error"
WARNING = "warning"


@dataclass
class Finding:
    level: str
    check: str
    line: int
    message: str


def load_limits(path: Path) -> dict:
    """读取限制配置。缺文件不是致命错误，退回内置默认值并提示。"""
    if not path.exists():
        print(f"[提示] 未找到 {path}，使用内置默认值", file=sys.stderr)
        return {
            "limits": {
                "titleMaxChars": {"value": 64, "enforce": True},
                "digestMaxChars": {"value": 120, "enforce": True},
                "codeBlockMaxLineWidth": {"value": 60, "enforce": False},
                "paragraphMaxChars": {"value": 300, "enforce": False},
                "imageMaxSizeMB": {"value": 10, "enforce": False},
            },
            "rules": {
                "noBareUrlInBody": {"enforce": True},
                "noTopLevelHeading": {"enforce": True},
                "requireImageAlt": {"enforce": False},
            },
        }
    return json.loads(path.read_text(encoding="utf-8"))


def level_for(config: dict) -> str:
    return ERROR if config.get("enforce") else WARNING


def split_front_matter(text: str) -> tuple[dict, str, int]:
    """切出 YAML front matter。

    只解析顶层的 `key: value`，不引入 yaml 依赖——这里需要的就只有 title 和 digest。
    返回 (字段, 正文, 正文起始行号偏移)。
    """
    if not text.startswith("---"):
        return {}, text, 0

    lines = text.splitlines()
    for index in range(1, len(lines)):
        if lines[index].strip() in {"---", "..."}:
            meta = {}
            for raw in lines[1:index]:
                if ":" not in raw or raw.lstrip().startswith("#"):
                    continue
                key, _, value = raw.partition(":")
                meta[key.strip()] = value.strip().strip("'\"")
            return meta, "\n".join(lines[index + 1 :]), index + 1
    return {}, text, 0


def mask_code_blocks(lines: list[str]) -> list[bool]:
    """标出哪些行在围栏代码块里，避免把代码当正文检查。"""
    inside = False
    flags = []
    for line in lines:
        if line.lstrip().startswith("```"):
            inside = not inside
            flags.append(True)
            continue
        flags.append(inside)
    return flags


def display_width(text: str) -> int:
    """按显示宽度算，一个汉字占两格。用于代码块宽度判断。"""
    width = 0
    for char in text:
        width += 2 if ord(char) > 0x2E80 else 1
    return width


def resolve_local_image(source: str, article_path: Path | None) -> Path | None:
    """把 Markdown 图片地址解析为本地路径；远程地址和 data URI 不读取。"""
    if article_path is None:
        return None

    raw = source.strip()
    if raw.startswith("<") and raw.endswith(">"):
        raw = raw[1:-1].strip()
    if not raw:
        return None

    parsed = urlsplit(raw)
    if parsed.scheme in {"http", "https", "data"} or parsed.netloc:
        return None
    if parsed.scheme and parsed.scheme != "file":
        return None

    candidate = Path(unquote(parsed.path))
    if not candidate.is_absolute():
        candidate = article_path.resolve().parent / candidate
    return candidate


def check_title(title: str | None, limits: dict) -> list[Finding]:
    config = limits["limits"].get("titleMaxChars", {})
    if not title:
        return [Finding(WARNING, "title", 0,
                        "没有提供标题。用 --title 或 front matter 的 title 字段补上，"
                        "标题是列表页唯一的点击理由。")]
    findings = []
    maximum = config.get("value", 64)
    if len(title) > maximum:
        findings.append(Finding(
            level_for(config), "title", 0,
            f"标题 {len(title)} 字，超过 {maximum} 字上限，列表页和分享卡片会被截断。"))
    elif len(title) > 20:
        findings.append(Finding(
            WARNING, "title", 0,
            f"标题 {len(title)} 字，手机列表页大概率折行。20 字以内更稳。"))
    return findings


def check_digest(digest: str | None, limits: dict) -> list[Finding]:
    config = limits["limits"].get("digestMaxChars", {})
    if not digest:
        return [Finding(WARNING, "digest", 0,
                        "没有提供摘要。留空的话微信会自动截正文开头，通常很难看。")]
    maximum = config.get("value", 120)
    if len(digest) > maximum:
        return [Finding(level_for(config), "digest", 0,
                        f"摘要 {len(digest)} 字，超过 {maximum} 字上限，会被截断。")]
    return []


def check_body(
    body: str,
    offset: int,
    limits: dict,
    article_path: Path | None = None,
) -> list[Finding]:
    findings: list[Finding] = []
    lines = body.splitlines()
    in_code = mask_code_blocks(lines)

    rules = limits.get("rules", {})
    width_config = limits["limits"].get("codeBlockMaxLineWidth", {})
    paragraph_config = limits["limits"].get("paragraphMaxChars", {})
    image_size_config = limits["limits"].get("imageMaxSizeMB", {})

    max_width = width_config.get("value", 60)
    max_paragraph = paragraph_config.get("value", 300)
    max_image_mb = image_size_config.get("value", 10)

    # 公众号正文里的裸链接不可点击，读者只能手动复制。
    bare_url = re.compile(r"(?<!\()(?<!\]\()https?://[^\s)\]<>]+")
    markdown_link = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
    image = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")
    heading = re.compile(r"^(#{1,6})\s+(.*)$")

    image_count = 0
    external_links: list[tuple[int, str]] = []

    for index, line in enumerate(lines):
        line_number = offset + index + 1
        stripped = line.strip()

        if in_code[index]:
            if not stripped.startswith("```") and display_width(line) > max_width:
                findings.append(Finding(
                    level_for(width_config), "code-width", line_number,
                    f"代码行显示宽度 {display_width(line)}，超过 {max_width}，"
                    f"手机端只能横向滚动。断行或改用截图。"))
            continue

        match = heading.match(stripped)
        if match and len(match.group(1)) == 1:
            config = rules.get("noTopLevelHeading", {})
            findings.append(Finding(
                level_for(config), "heading", line_number,
                "正文里出现 H1。文章标题在公众号后台单独填，正文小标题从 ## 起。"))

        for found in image.finditer(line):
            image_count += 1
            alt = found.group(1).strip()
            config = rules.get("requireImageAlt", {})
            if not alt:
                findings.append(Finding(
                    level_for(config), "image-alt", line_number,
                    "图片没有 alt。公众号不渲染 alt，但它是你自己写图注时的草稿。"))

            local_image = resolve_local_image(found.group(2), article_path)
            if local_image is not None and isinstance(max_image_mb, (int, float)):
                try:
                    if not local_image.is_file():
                        continue
                    size_bytes = local_image.stat().st_size
                except OSError:
                    size_bytes = 0
                size_mb = size_bytes / (1024 * 1024)
                if max_image_mb > 0 and size_mb > max_image_mb:
                    findings.append(Finding(
                        level_for(image_size_config), "image-size", line_number,
                        f"图片 {size_mb:.2f} MB，超过 {max_image_mb:g} MB。"
                        "上传素材库前请压缩。"))

        # 顺序要紧：先摘掉图片，否则 ![alt](src) 尾部的 ](src) 会被当成普通链接。
        # 只统计 http(s) 目标，本地图片路径和站内锚点不是「读者点不了的外链」。
        without_images = image.sub("", line)
        for found in markdown_link.finditer(without_images):
            if found.group(1).startswith(("http://", "https://")):
                external_links.append((line_number, found.group(1)))
        without_links = markdown_link.sub("", without_images)
        for found in bare_url.finditer(without_links):
            external_links.append((line_number, found.group(0)))

        if not match and len(stripped) > max_paragraph:
            findings.append(Finding(
                level_for(paragraph_config), "paragraph", line_number,
                f"这一段 {len(stripped)} 字，手机上要滑好几屏。中间断一下。"))

    if external_links:
        config = rules.get("noBareUrlInBody", {})
        first_line = external_links[0][0]
        findings.append(Finding(
            level_for(config), "link", first_line,
            f"正文里有 {len(external_links)} 处外部链接。公众号正文的链接不可点击，"
            f"读者只能手抄。留一个放「阅读原文」，其余改成引导文字或二维码。"))

    if image_count == 0:
        findings.append(Finding(
            WARNING, "image", 0,
            "全文没有配图。纯文字长文在公众号里完读率很低，至少配一张。"))

    return findings


def run(path: Path, title: str | None, digest: str | None) -> list[Finding]:
    text = path.read_text(encoding="utf-8")
    meta, body, offset = split_front_matter(text)
    limits = load_limits(LIMITS_FILE)

    findings = []
    findings += check_title(title or meta.get("title"), limits)
    findings += check_digest(digest or meta.get("digest"), limits)
    findings += check_body(body, offset, limits, path)
    return findings


def print_report(path: Path, findings: list[Finding], json_output: bool = False) -> int:
    """输出体检结果并返回与 CLI 一致的退出码。"""
    errors = [finding for finding in findings if finding.level == ERROR]
    warnings = [finding for finding in findings if finding.level == WARNING]

    if json_output:
        print(json.dumps({
            "file": str(path),
            "errors": len(errors),
            "warnings": len(warnings),
            "findings": [asdict(finding) for finding in findings],
        }, ensure_ascii=False, indent=2))
        return 1 if errors else 0

    if not findings:
        print(f"✓ {path}：没有发现问题")
        return 0

    for finding in sorted(findings, key=lambda item: (item.level != ERROR, item.line)):
        marker = "✗" if finding.level == ERROR else "!"
        where = f"第 {finding.line} 行" if finding.line else "整篇"
        print(f"{marker} [{finding.check}] {where}：{finding.message}")

    print(f"\n{len(errors)} 个错误，{len(warnings)} 个提示")
    if errors:
        print("错误会导致发布后显示异常，建议改完再发。")
    return 1 if errors else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="公众号发布前体检")
    parser.add_argument("file", type=Path, help="Markdown 文件")
    parser.add_argument("--title", help="文章标题（也可写在 front matter）")
    parser.add_argument("--digest", help="文章摘要（也可写在 front matter）")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    args = parser.parse_args()

    if not args.file.exists():
        print(f"找不到文件：{args.file}", file=sys.stderr)
        return 2

    findings = run(args.file, args.title, args.digest)
    return print_report(args.file, findings, args.json)


if __name__ == "__main__":
    sys.exit(main())
