#!/usr/bin/env python3
"""微信公众号发布流水线统一命令行入口。

保留 check_mp.py、apply_template.py、check_staleness.py 作为兼容入口；
新工作流优先使用本脚本的 check、render、build、validate-template、doctor。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TextIO

if __package__:
    from . import apply_template, check_mp, check_staleness
else:
    import apply_template
    import check_mp
    import check_staleness


ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_DIR = ROOT / "templates"
TEMPLATE_SCHEMA_FILE = ROOT / "references" / "template.schema.json"

ERROR = "error"
WARNING = "warning"
INFO = "info"

class CliInputError(Exception):
    """用户输入、文件或配置不可用。"""


@dataclass
class TemplateFinding:
    level: str
    field: str
    message: str


@dataclass
class TemplateResult:
    template: str
    path: str
    findings: list[TemplateFinding]


@dataclass
class DoctorCheck:
    level: str
    name: str
    message: str


@dataclass(frozen=True)
class TemplateSchemaContract:
    required_fields: frozenset[str]
    root_fields: frozenset[str]
    required_style_keys: frozenset[str]
    style_keys: frozenset[str]


def load_template_schema() -> dict:
    try:
        schema = json.loads(TEMPLATE_SCHEMA_FILE.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CliInputError(f"模版 Schema 读取失败：{exc}") from exc
    if not isinstance(schema, dict):
        raise CliInputError("模版 Schema 根节点必须是对象")
    return schema


def string_set(value: object, description: str) -> frozenset[str]:
    if not isinstance(value, list) or not value or not all(
        isinstance(item, str) and item for item in value
    ):
        raise CliInputError(f"模版 Schema 的 {description} 必须是非空字符串数组")
    return frozenset(value)


def object_keys(value: object, description: str) -> frozenset[str]:
    if not isinstance(value, dict) or not value or not all(
        isinstance(key, str) and key for key in value
    ):
        raise CliInputError(f"模版 Schema 的 {description} 必须是非空对象")
    return frozenset(value)


def template_schema_contract() -> TemplateSchemaContract:
    schema = load_template_schema()
    properties = schema.get("properties")
    root_fields = object_keys(properties, "properties")
    required_fields = string_set(schema.get("required"), "required")
    if not required_fields <= root_fields:
        raise CliInputError("模版 Schema 的 required 包含未声明字段")

    assert isinstance(properties, dict)
    styles_schema = properties.get("styles")
    if not isinstance(styles_schema, dict):
        raise CliInputError("模版 Schema 缺少 styles 定义")
    style_keys = object_keys(styles_schema.get("properties"), "styles.properties")
    required_style_keys = string_set(
        styles_schema.get("required"),
        "styles.required",
    )
    if not required_style_keys <= style_keys:
        raise CliInputError("模版 Schema 的 styles.required 包含未声明样式")

    return TemplateSchemaContract(
        required_fields=required_fields,
        root_fields=root_fields,
        required_style_keys=required_style_keys,
        style_keys=style_keys,
    )


def require_article(path: Path) -> None:
    if not path.exists():
        raise CliInputError(f"找不到 Markdown 文件：{path}")
    if not path.is_file():
        raise CliInputError(f"不是 Markdown 文件：{path}")


def load_template(name: str) -> dict:
    try:
        return apply_template.load_template(name)
    except SystemExit as exc:
        raise CliInputError(str(exc)) from exc


def render_article(
    path: Path,
    template_name: str,
    standalone: bool,
    title: str | None = None,
) -> str:
    template = load_template(template_name)
    meta, markdown = apply_template.split_front_matter(
        path.read_text(encoding="utf-8")
    )
    body = apply_template.render_markdown(markdown, template)
    return apply_template.build_document(
        body,
        template,
        title or meta.get("title"),
        standalone,
    )


def write_document(output: Path, document: str) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(document, encoding="utf-8")
    print(f"已写入 {output}")


def require_distinct_output(article: Path, output: Path | None) -> None:
    if output is not None and article.resolve() == output.resolve():
        raise CliInputError("输出文件不能覆盖原 Markdown")


def resolve_template_dirs(target: str | None) -> list[Path]:
    if target is None:
        directories = (
            [path for path in TEMPLATE_DIR.iterdir() if path.is_dir()]
            if TEMPLATE_DIR.is_dir()
            else []
        )
        if not directories:
            raise CliInputError("没有可校验的模版")
        return sorted(directories, key=lambda path: path.name)

    builtin = TEMPLATE_DIR / target
    if re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", target) and builtin.is_dir():
        return [builtin]

    candidate = Path(target).expanduser()
    if candidate.exists():
        if candidate.is_file() and candidate.name == "template.json":
            return [candidate.parent]
        if candidate.is_dir():
            return [candidate]
        raise CliInputError(f"模版目标必须是目录或 template.json：{candidate}")

    raise CliInputError(f"找不到模版：{target}")


def validate_nonempty_string(
    data: dict,
    field: str,
    findings: list[TemplateFinding],
) -> str | None:
    value = data.get(field)
    if not isinstance(value, str) or not value.strip():
        findings.append(TemplateFinding(ERROR, field, "必须是非空字符串"))
        return None
    return value.strip()


def validate_string_list(
    data: dict,
    field: str,
    findings: list[TemplateFinding],
    require_items: bool,
) -> None:
    value = data.get(field)
    if not isinstance(value, list) or not all(
        isinstance(item, str) and item.strip() for item in value
    ):
        findings.append(TemplateFinding(ERROR, field, "必须是字符串数组"))
    elif require_items and not value:
        findings.append(TemplateFinding(ERROR, field, "至少填写一项"))


def validate_template_dir(template_dir: Path) -> TemplateResult:
    findings: list[TemplateFinding] = []
    config_path = template_dir / "template.json"
    template_name = template_dir.name

    if not config_path.is_file():
        findings.append(TemplateFinding(ERROR, "template.json", "缺少模版配置文件"))
        return TemplateResult(template_name, str(template_dir), findings)

    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        findings.append(TemplateFinding(
            ERROR,
            "template.json",
            f"无法读取有效 JSON：{exc}",
        ))
        return TemplateResult(template_name, str(template_dir), findings)

    if not isinstance(data, dict):
        findings.append(TemplateFinding(ERROR, "template.json", "根节点必须是对象"))
        return TemplateResult(template_name, str(template_dir), findings)

    try:
        contract = template_schema_contract()
    except CliInputError as exc:
        findings.append(TemplateFinding(
            ERROR,
            "references/template.schema.json",
            str(exc),
        ))
        return TemplateResult(template_name, str(template_dir), findings)

    for field in sorted(contract.required_fields - data.keys()):
        findings.append(TemplateFinding(ERROR, field, "缺少必填字段"))
    for field in sorted(data.keys() - contract.root_fields):
        findings.append(TemplateFinding(ERROR, field, "Schema 未声明此字段"))

    template_id = (
        validate_nonempty_string(data, "id", findings)
        if "id" in data else None
    )
    for field in ("name", "description"):
        if field in data:
            validate_nonempty_string(data, field, findings)
    if "bestFor" in data:
        validate_string_list(data, "bestFor", findings, require_items=True)
    if "notes" in data:
        validate_string_list(data, "notes", findings, require_items=False)

    if template_id:
        if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", template_id):
            findings.append(TemplateFinding(
                ERROR,
                "id",
                "只能使用小写字母、数字和单个连字符",
            ))
        if template_id != template_dir.name:
            findings.append(TemplateFinding(
                ERROR,
                "id",
                f"必须与目录名 {template_dir.name!r} 一致",
            ))

    if "palette" in data:
        palette = data["palette"]
        if not isinstance(palette, dict) or not palette:
            findings.append(TemplateFinding(ERROR, "palette", "必须是非空颜色对象"))
        elif not all(
            isinstance(key, str) and isinstance(value, str) and value.strip()
            for key, value in palette.items()
        ):
            findings.append(TemplateFinding(
                ERROR,
                "palette",
                "颜色名称和值必须是字符串",
            ))

    styles = data.get("styles")
    if "styles" not in data:
        styles = None
    elif not isinstance(styles, dict):
        findings.append(TemplateFinding(ERROR, "styles", "必须是样式对象"))
    else:
        for key in sorted(contract.required_style_keys):
            if not isinstance(styles.get(key), str) or not styles[key].strip():
                findings.append(TemplateFinding(
                    ERROR,
                    f"styles.{key}",
                    "必须提供非空内联样式",
                ))
        for key, value in styles.items():
            if key not in contract.style_keys:
                findings.append(TemplateFinding(
                    ERROR,
                    f"styles.{key}",
                    "未知样式键，渲染器不会使用它",
                ))
            if not isinstance(value, str):
                findings.append(TemplateFinding(
                    ERROR,
                    f"styles.{key}",
                    "样式值必须是 CSS 声明字符串",
                ))
            elif any(token in value for token in ("<style", "{", "}")):
                findings.append(TemplateFinding(
                    ERROR,
                    f"styles.{key}",
                    "只填写 CSS 声明，不要包含选择器、花括号或 style 标签",
                ))

    sample = template_dir / "sample.md"
    if not sample.is_file():
        findings.append(TemplateFinding(WARNING, "sample.md", "建议提供渲染样例"))
    elif isinstance(styles, dict):
        try:
            _, markdown = apply_template.split_front_matter(
                sample.read_text(encoding="utf-8")
            )
            rendered = apply_template.render_markdown(markdown, data)
            if not rendered:
                findings.append(TemplateFinding(
                    ERROR,
                    "sample.md",
                    "样例没有生成任何 HTML",
                ))
        except (OSError, UnicodeError, TypeError, AttributeError) as exc:
            findings.append(TemplateFinding(
                ERROR,
                "sample.md",
                f"样例渲染失败：{exc}",
            ))

    if not (template_dir / "preview.png").is_file():
        findings.append(TemplateFinding(WARNING, "preview.png", "建议提供预览图"))

    return TemplateResult(template_name, str(template_dir), findings)


def validation_counts(results: list[TemplateResult]) -> tuple[int, int]:
    findings = [finding for result in results for finding in result.findings]
    errors = sum(finding.level == ERROR for finding in findings)
    warnings = sum(finding.level == WARNING for finding in findings)
    return errors, warnings


def validate_template_for_use(
    template_name: str,
) -> tuple[list[TemplateResult], int, int]:
    results = [
        validate_template_dir(path)
        for path in resolve_template_dirs(template_name)
    ]
    errors, warnings = validation_counts(results)
    return results, errors, warnings


def print_template_results(
    results: list[TemplateResult],
    json_output: bool,
    stream: TextIO | None = None,
) -> int:
    errors, warnings = validation_counts(results)
    if json_output:
        print(json.dumps({
            "templates": len(results),
            "errors": errors,
            "warnings": warnings,
            "results": [asdict(result) for result in results],
        }, ensure_ascii=False, indent=2))
        return 1 if errors else 0

    output = stream or sys.stdout
    for result in results:
        if not result.findings:
            print(f"✓ {result.template}：模版有效", file=output)
            continue
        for finding in result.findings:
            marker = "✗" if finding.level == ERROR else "!"
            print(
                f"{marker} [{result.template}:{finding.field}] {finding.message}",
                file=output,
            )
    print(
        f"\n{len(results)} 个模版，{errors} 个错误，{warnings} 个提示",
        file=output,
    )
    return 1 if errors else 0


def command_check(args: argparse.Namespace) -> int:
    require_article(args.file)
    findings = check_mp.run(args.file, args.title, args.digest)
    return check_mp.print_report(args.file, findings, args.json)


def command_render(args: argparse.Namespace) -> int:
    require_article(args.file)
    require_distinct_output(args.file, args.output)
    template_results, template_errors, template_warnings = (
        validate_template_for_use(args.template)
    )
    if template_errors:
        print_template_results(template_results, False, sys.stderr)
        return 1
    if template_warnings:
        print_template_results(template_results, False, sys.stderr)

    document = render_article(
        args.file,
        args.template,
        args.standalone,
        args.title,
    )
    if args.output:
        write_document(args.output, document)
    else:
        print(document)
    return 0


def command_build(args: argparse.Namespace) -> int:
    require_article(args.file)
    output = args.output or args.file.with_suffix(".html")
    require_distinct_output(args.file, output)

    template_results, template_errors, template_warnings = (
        validate_template_for_use(args.template)
    )
    if template_errors:
        print_template_results(template_results, False)
        print("✗ 模版校验未通过，不会生成 HTML。")
        return 1
    if template_warnings:
        print_template_results(template_results, False)

    findings = check_mp.run(args.file, args.title, args.digest)
    exit_code = check_mp.print_report(args.file, findings)
    if exit_code:
        print("✗ 发布前体检未通过，不会生成 HTML。")
        return exit_code

    document = render_article(
        args.file,
        args.template,
        args.standalone,
        args.title,
    )
    write_document(output, document)
    return 0


def command_validate_template(args: argparse.Namespace) -> int:
    results = [
        validate_template_dir(path)
        for path in resolve_template_dirs(args.target)
    ]
    return print_template_results(results, args.json)


def command_doctor(args: argparse.Namespace) -> int:
    checks: list[DoctorCheck] = []

    if sys.version_info >= (3, 9):
        checks.append(DoctorCheck(
            INFO,
            "python",
            f"Python {sys.version_info.major}.{sys.version_info.minor} 可用",
        ))
    else:
        checks.append(DoctorCheck(ERROR, "python", "需要 Python 3.9 或更高版本"))

    required_files = (
        ROOT / "SKILL.md",
        ROOT / "scripts" / "check_mp.py",
        ROOT / "scripts" / "apply_template.py",
        ROOT / "scripts" / "check_staleness.py",
        ROOT / "scripts" / "wechat_mp.py",
        ROOT / "references" / "platform-limits.json",
        TEMPLATE_SCHEMA_FILE,
    )
    missing = [
        str(path.relative_to(ROOT))
        for path in required_files
        if not path.is_file()
    ]
    if missing:
        checks.append(DoctorCheck(
            ERROR,
            "files",
            f"缺少必要文件：{', '.join(missing)}",
        ))
    else:
        checks.append(DoctorCheck(INFO, "files", "核心脚本和配置文件完整"))

    try:
        contract = template_schema_contract()
        checks.append(DoctorCheck(
            INFO,
            "template-schema",
            (
                f"Schema 有 {len(contract.required_fields)} 个必填字段、"
                f"{len(contract.style_keys)} 个样式键"
            ),
        ))
    except CliInputError as exc:
        checks.append(DoctorCheck(ERROR, "template-schema", str(exc)))

    try:
        limits = check_staleness.load_limits(check_staleness.LIMITS_FILE)
        _, _, reports = check_staleness.inspect_staleness(limits)
        stale = [report for report in reports if report.is_stale or report.is_invalid]
        critical = [
            report
            for report in stale
            if report.severity == check_staleness.SEVERITY_CRITICAL
        ]
        if critical:
            checks.append(DoctorCheck(
                ERROR,
                "platform-limits",
                f"{len(critical)} 个强制规则已过期或异常",
            ))
        elif stale:
            checks.append(DoctorCheck(
                WARNING,
                "platform-limits",
                f"{len(stale)} 个提示型规则已过期或异常",
            ))
        else:
            checks.append(DoctorCheck(INFO, "platform-limits", "平台限制配置有效"))
    except (
        OSError,
        UnicodeError,
        json.JSONDecodeError,
        TypeError,
        AttributeError,
        KeyError,
        ValueError,
    ) as exc:
        checks.append(DoctorCheck(ERROR, "platform-limits", f"配置读取失败：{exc}"))

    try:
        template_results = [
            validate_template_dir(path) for path in resolve_template_dirs(None)
        ]
        template_errors, template_warnings = validation_counts(template_results)
        if template_errors:
            checks.append(DoctorCheck(
                ERROR,
                "templates",
                f"{template_errors} 个模版错误",
            ))
        elif template_warnings:
            checks.append(DoctorCheck(
                WARNING,
                "templates",
                f"模版有效，另有 {template_warnings} 个提示",
            ))
        else:
            checks.append(DoctorCheck(
                INFO,
                "templates",
                f"{len(template_results)} 个模版均有效",
            ))
    except CliInputError as exc:
        checks.append(DoctorCheck(ERROR, "templates", str(exc)))

    errors = sum(check.level == ERROR for check in checks)
    warnings = sum(check.level == WARNING for check in checks)
    if args.json:
        print(json.dumps({
            "ok": errors == 0,
            "errors": errors,
            "warnings": warnings,
            "checks": [asdict(check) for check in checks],
        }, ensure_ascii=False, indent=2))
    else:
        for check in checks:
            marker = (
                "✗" if check.level == ERROR
                else "!" if check.level == WARNING
                else "✓"
            )
            print(f"{marker} [{check.name}] {check.message}")
        print(f"\n{errors} 个错误，{warnings} 个提示")
    return 1 if errors else 0


def add_article_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("file", type=Path, help="Markdown 文件")
    parser.add_argument("--title", help="覆盖 front matter 标题")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="微信公众号发布前体检与排版流水线",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    check_parser = subparsers.add_parser("check", help="只做发布前体检")
    add_article_arguments(check_parser)
    check_parser.add_argument("--digest", help="覆盖 front matter 摘要")
    check_parser.add_argument("--json", action="store_true", help="输出 JSON")
    check_parser.set_defaults(handler=command_check)

    render_parser = subparsers.add_parser("render", help="只套排版模版")
    add_article_arguments(render_parser)
    render_parser.add_argument("-t", "--template", required=True, help="模版 id")
    render_parser.add_argument("-o", "--output", type=Path, help="输出 HTML")
    render_parser.add_argument(
        "--standalone",
        action="store_true",
        help="生成浏览器独立预览页",
    )
    render_parser.set_defaults(handler=command_render)

    build_command = subparsers.add_parser("build", help="体检通过后生成 HTML")
    add_article_arguments(build_command)
    build_command.add_argument("--digest", help="覆盖 front matter 摘要")
    build_command.add_argument("-t", "--template", required=True, help="模版 id")
    build_command.add_argument("-o", "--output", type=Path, help="输出 HTML")
    build_command.add_argument(
        "--standalone",
        action="store_true",
        help="生成浏览器独立预览页",
    )
    build_command.set_defaults(handler=command_build)

    validate_parser = subparsers.add_parser(
        "validate-template",
        help="校验单个或全部模版",
    )
    validate_parser.add_argument(
        "target",
        nargs="?",
        help="模版 id、模版目录或 template.json；默认校验全部",
    )
    validate_parser.add_argument("--json", action="store_true", help="输出 JSON")
    validate_parser.set_defaults(handler=command_validate_template)

    doctor_parser = subparsers.add_parser("doctor", help="检查本地运行环境")
    doctor_parser.add_argument("--json", action="store_true", help="输出 JSON")
    doctor_parser.set_defaults(handler=command_doctor)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.handler(args)
    except CliInputError as exc:
        print(f"✗ {exc}", file=sys.stderr)
        return 2
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        print(f"✗ 操作失败：{exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\n已取消", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
