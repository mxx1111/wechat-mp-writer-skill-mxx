#!/usr/bin/env python3
"""检查 references/platform-limits.json 里的 lastVerified 是否过期。

默认策略：
- enforce=true 的过期/无效日期返回 error，并用退出码 1 提醒 CI。
- enforce=false 的过期日期只 warning，因为它不会阻塞发布。
- 文件级 lastVerified 过期返回 warning；缺失或格式错误返回 error。

只用标准库，不需要安装依赖。
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path

LIMITS_FILE = Path(__file__).resolve().parent.parent / "references" / "platform-limits.json"
ERROR = "error"
WARNING = "warning"


@dataclass
class Finding:
    level: str
    entry: str
    date: str
    ageDays: int | None
    source: str
    message: str


def parse_iso_day(value: object) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def source_for(root: dict, config: dict) -> str:
    value = config.get("source") or root.get("verifyAgainst")
    return value if isinstance(value, str) and value else "(no source)"


def check_entry(name: str, config: dict, root: dict, today: date, threshold: int, *, file_level: bool = False) -> Finding | None:
    raw = config.get("lastVerified")
    source = source_for(root, config)
    verified = parse_iso_day(raw)
    enforce = bool(config.get("enforce"))

    if verified is None:
        urgency = ERROR if enforce or file_level else WARNING
        return Finding(
            urgency,
            name,
            str(raw) if raw is not None else "(missing)",
            None,
            source,
            "lastVerified is missing or not YYYY-MM-DD; verify the value before trusting this limit.",
        )

    age = (today - verified).days
    if age <= threshold:
        return None

    if enforce:
        level = ERROR
        message = "URGENT: stale enforced limit can block publishing with an outdated number."
    elif file_level:
        level = WARNING
        message = "File-level verification is stale; review the whole limits file."
    else:
        level = WARNING
        message = "Stale advisory limit; it currently warns only, but should still be reviewed."

    return Finding(level, name, verified.isoformat(), age, source, message)


def run(path: Path, today: date | None = None) -> list[Finding]:
    today = today or date.today()
    root = json.loads(path.read_text(encoding="utf-8"))
    staleness = root.get("staleness", {})
    threshold = staleness.get("thresholdDays")
    if not isinstance(threshold, int) or threshold < 1:
        raise SystemExit("references/platform-limits.json: staleness.thresholdDays must be a positive integer")

    findings: list[Finding] = []
    file_finding = check_entry("file", root, root, today, threshold, file_level=True)
    if file_finding:
        findings.append(file_finding)

    limits = root.get("limits", {})
    if not isinstance(limits, dict):
        raise SystemExit("references/platform-limits.json: limits must be an object")

    for name, config in limits.items():
        if not isinstance(config, dict):
            findings.append(Finding(ERROR, f"limits.{name}", "(invalid)", None, "(no source)", "limit config must be an object"))
            continue
        finding = check_entry(f"limits.{name}", config, root, today, threshold)
        if finding:
            findings.append(finding)

    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description="检查平台限制 lastVerified 是否过期")
    parser.add_argument("--file", type=Path, default=LIMITS_FILE, help="platform-limits.json 路径")
    parser.add_argument("--today", help="测试用日期 YYYY-MM-DD，默认今天")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    args = parser.parse_args()

    today = parse_iso_day(args.today) if args.today else date.today()
    if today is None:
        print("--today must be YYYY-MM-DD", file=sys.stderr)
        return 2

    findings = run(args.file, today)
    errors = [f for f in findings if f.level == ERROR]
    warnings = [f for f in findings if f.level == WARNING]

    if args.json:
        print(json.dumps({
            "file": str(args.file),
            "errors": len(errors),
            "warnings": len(warnings),
            "findings": [asdict(f) for f in findings],
        }, ensure_ascii=False, indent=2))
        return 1 if errors else 0

    if not findings:
        print(f"✓ {args.file}：lastVerified entries are within the configured staleness threshold")
        return 0

    for finding in sorted(findings, key=lambda f: (f.level != ERROR, f.entry)):
        marker = "✗" if finding.level == ERROR else "!"
        age = "unknown age" if finding.ageDays is None else f"{finding.ageDays} days old"
        print(f"{marker} [{finding.level}] {finding.entry}: {finding.date} ({age})")
        print(f"  source: {finding.source}")
        print(f"  {finding.message}")

    print(f"\n{len(errors)} errors, {len(warnings)} warnings")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
