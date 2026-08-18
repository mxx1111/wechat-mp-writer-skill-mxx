#!/usr/bin/env python3
"""检查 platform-limits.json 中的限制规则是否已过期陈旧。

依据 platform-limits.json 中配置的阈值（staleness.thresholdDays），
检查文件根级别与每个具体 limit 的 lastVerified 日期。
对即将或已经过期的限制项输出详细报告（包括最后验证日期、已过去天数、参考来源 URL、是否为强制拦截项）。

用法：
    python3 scripts/check_staleness.py
    python3 scripts/check_staleness.py --json
    python3 scripts/check_staleness.py --threshold 90
    python3 scripts/check_staleness.py --fail-enforced
    python3 scripts/check_staleness.py --fail-all

只用 Python 标准库，无第三方依赖。
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
from dataclasses import dataclass, asdict
from pathlib import Path

LIMITS_FILE = Path(__file__).resolve().parent.parent / "references" / "platform-limits.json"

SEVERITY_CRITICAL = "critical"  # 过期且 enforce=true，或者日期缺失/格式错误
SEVERITY_WARNING = "warning"    # 过期但 enforce=false，或者根文件过期
SEVERITY_INFO = "info"          # 正常有效


@dataclass
class StaleReport:
    target: str          # "file" 或 limit 键名
    name: str            # 可读名称/描述
    enforce: bool        # 是否强制校验
    last_verified: str | None
    age_days: int | None
    threshold_days: int
    is_stale: bool
    is_invalid: bool
    source_url: str
    severity: str
    message: str


def load_limits(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"找不到限制配置文件: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def parse_date(date_str: str | None) -> datetime.date | None:
    if not date_str or not isinstance(date_str, str):
        return None
    try:
        return datetime.datetime.strptime(date_str.strip(), "%Y-%m-%d").date()
    except ValueError:
        return None


def inspect_staleness(
    data: dict,
    override_threshold: int | None = None,
    current_date: datetime.date | None = None,
) -> tuple[int, str, list[StaleReport]]:
    """分析 platform-limits.json 的陈旧度。"""
    today = current_date or datetime.date.today()

    # 从 JSON 配置读取阈值及解释
    staleness_cfg = data.get("staleness", {})
    if isinstance(staleness_cfg, dict):
        threshold_days = staleness_cfg.get("thresholdDays", 180)
        rationale = staleness_cfg.get("rationale", "未提供过期判定理由说明")
    else:
        threshold_days = data.get("stalenessThresholdDays", 180)
        rationale = data.get("stalenessRationale", "未提供过期判定理由说明")

    if override_threshold is not None and override_threshold > 0:
        threshold_days = override_threshold

    global_source = data.get("verifyAgainst") or "https://developers.weixin.qq.com/doc/offiaccount/"
    reports: list[StaleReport] = []

    # 1. 检查根文件 lastVerified
    root_lv_raw = data.get("lastVerified")
    root_date = parse_date(root_lv_raw)
    if not root_lv_raw:
        reports.append(StaleReport(
            target="file",
            name="platform-limits.json (整体文件)",
            enforce=False,
            last_verified=None,
            age_days=None,
            threshold_days=threshold_days,
            is_stale=True,
            is_invalid=True,
            source_url=global_source,
            severity=SEVERITY_WARNING,
            message="根配置缺少 lastVerified 字段，无法追踪整体有效性",
        ))
    elif root_date is None:
        reports.append(StaleReport(
            target="file",
            name="platform-limits.json (整体文件)",
            enforce=False,
            last_verified=str(root_lv_raw),
            age_days=None,
            threshold_days=threshold_days,
            is_stale=True,
            is_invalid=True,
            source_url=global_source,
            severity=SEVERITY_WARNING,
            message=f"根配置 lastVerified '{root_lv_raw}' 格式无效 (需为 YYYY-MM-DD)",
        ))
    else:
        age = (today - root_date).days
        is_stale = age > threshold_days
        reports.append(StaleReport(
            target="file",
            name="platform-limits.json (整体文件)",
            enforce=False,
            last_verified=root_date.isoformat(),
            age_days=age,
            threshold_days=threshold_days,
            is_stale=is_stale,
            is_invalid=False,
            source_url=global_source,
            severity=SEVERITY_WARNING if is_stale else SEVERITY_INFO,
            message=(
                f"整体配置最后核对日期为 {root_date.isoformat()}（已过去 {age} 天，阈值 {threshold_days} 天）"
                if is_stale
                else f"有效（已核对 {age} 天前）"
            ),
        ))

    # 2. 检查各项 limits
    limits = data.get("limits", {})
    for key, item in limits.items():
        if not isinstance(item, dict):
            continue

        enforce = bool(item.get("enforce", False))
        unit = item.get("unit", "")
        val = item.get("value", "")
        note = item.get("note", "")
        name = f"{key} ({val} {unit})" if unit else f"{key} ({val})"
        source = item.get("source") or item.get("verifyAgainst") or global_source
        lv_raw = item.get("lastVerified")
        dt = parse_date(lv_raw)

        if not lv_raw:
            reports.append(StaleReport(
                target=f"limits.{key}",
                name=name,
                enforce=enforce,
                last_verified=None,
                age_days=None,
                threshold_days=threshold_days,
                is_stale=True,
                is_invalid=True,
                source_url=source,
                severity=SEVERITY_CRITICAL if enforce else SEVERITY_WARNING,
                message=f"缺失 lastVerified 字段（强制拦截: {'是' if enforce else '否'}）",
            ))
            continue

        if dt is None:
            reports.append(StaleReport(
                target=f"limits.{key}",
                name=name,
                enforce=enforce,
                last_verified=str(lv_raw),
                age_days=None,
                threshold_days=threshold_days,
                is_stale=True,
                is_invalid=True,
                source_url=source,
                severity=SEVERITY_CRITICAL if enforce else SEVERITY_WARNING,
                message=f"lastVerified '{lv_raw}' 格式无效 (需为 YYYY-MM-DD)",
            ))
            continue

        age = (today - dt).days
        is_stale = age > threshold_days
        if is_stale:
            severity = SEVERITY_CRITICAL if enforce else SEVERITY_WARNING
            urgency_tag = "【高风险·强制拦截】" if enforce else "【提示项】"
            msg = (
                f"{urgency_tag} 已过期！最后核实于 {dt.isoformat()}（已过去 {age} 天，超过阈值 {threshold_days} 天）。"
                f"可能与微信最新平台限制不符。"
            )
        else:
            severity = SEVERITY_INFO
            msg = f"有效（已核对 {age} 天前）"

        reports.append(StaleReport(
            target=f"limits.{key}",
            name=name,
            enforce=enforce,
            last_verified=dt.isoformat(),
            age_days=age,
            threshold_days=threshold_days,
            is_stale=is_stale,
            is_invalid=False,
            source_url=source,
            severity=severity,
            message=msg,
        ))

    return threshold_days, rationale, reports


def write_github_summary(
    threshold_days: int, rationale: str, reports: list[StaleReport]
) -> None:
    """输出 Markdown 到 $GITHUB_STEP_SUMMARY 方便 Actions 面板直接查看。"""
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return

    stale_items = [r for r in reports if r.is_stale or r.is_invalid]
    total_stale = len(stale_items)
    critical_stale = len([r for r in stale_items if r.severity == SEVERITY_CRITICAL])

    lines = [
        "## 📋 WeChat MP Platform Limits Staleness Report",
        "",
        f"- **过期阈值**: `{threshold_days}` 天",
        f"- **阈值依据**: {rationale}",
        f"- **过期/异常项总数**: `{total_stale}`（其中强制拦截项 `{critical_stale}` 个）",
        "",
    ]

    if not stale_items:
        lines.append("✅ **所有平台数值与规则的 lastVerified 均处于有效期内。**")
    else:
        lines.append("| 严重级别 | 限制项 | 强制拦截 | 最后核实日期 | 已过去 | 核对来源 (Source URL) | 说明 |")
        lines.append("| :--- | :--- | :---: | :---: | :---: | :--- | :--- |")
        for r in stale_items:
            icon = "🚨 阻断/高危" if r.severity == SEVERITY_CRITICAL else "⚠️ 警告"
            enforce_str = "✅ 是" if r.enforce else "❌ 否"
            lv_str = r.last_verified or "*(缺失)*"
            age_str = f"{r.age_days} 天" if r.age_days is not None else "*(未知)*"
            source_md = f"[{r.source_url}]({r.source_url})" if r.source_url else "*(无)*"
            lines.append(
                f"| {icon} | `{r.target}`<br><small>{r.name}</small> | {enforce_str} | {lv_str} | {age_str} | {source_md} | {r.message} |"
            )

    try:
        with open(summary_path, "a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    except Exception as e:
        print(f"[提示] 写入 GITHUB_STEP_SUMMARY 失败: {e}", file=sys.stderr)


def main() -> int:
    parser = argparse.ArgumentParser(description="WeChat MP 限制陈旧度检查")
    parser.add_argument(
        "--file",
        type=Path,
        default=LIMITS_FILE,
        help=f"platform-limits.json 文件路径 (默认: {LIMITS_FILE})",
    )
    parser.add_argument(
        "--threshold",
        type=int,
        default=None,
        help="覆盖 JSON 中配置的过期天数阈值",
    )
    parser.add_argument(
        "--current-date",
        type=str,
        default=None,
        help="指定当前基准日期 (YYYY-MM-DD，测试用)",
    )
    parser.add_argument("--json", action="store_true", help="以 JSON 格式输出结果")
    parser.add_argument(
        "--fail-enforced",
        action="store_true",
        help="当存在 enforce=true 的过期项或日期异常时，返回非 0 退出码",
    )
    parser.add_argument(
        "--fail-all",
        action="store_true",
        help="只要存在任何过期或异常项（包括 enforce=false），均返回非 0 退出码",
    )
    args = parser.parse_args()

    ref_date = parse_date(args.current_date) if args.current_date else None

    try:
        data = load_limits(args.file)
    except Exception as e:
        print(f"✗ 读取配置文件失败: {e}", file=sys.stderr)
        return 2

    threshold_days, rationale, reports = inspect_staleness(
        data, override_threshold=args.threshold, current_date=ref_date
    )

    stale_reports = [r for r in reports if r.is_stale or r.is_invalid]
    critical_stale = [r for r in stale_reports if r.severity == SEVERITY_CRITICAL]
    warning_stale = [r for r in stale_reports if r.severity == SEVERITY_WARNING]

    if args.json:
        payload = {
            "file": str(args.file),
            "thresholdDays": threshold_days,
            "rationale": rationale,
            "totalChecked": len(reports),
            "staleCount": len(stale_reports),
            "criticalCount": len(critical_stale),
            "warningCount": len(warning_stale),
            "reports": [asdict(r) for r in reports],
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"=== platform-limits.json 陈旧度检查 ===")
        print(f"检查文件: {args.file}")
        print(f"判定阈值: {threshold_days} 天 ({threshold_days / 30:.1f} 个月)")
        print(f"依据说明: {rationale}\n")

        if not stale_reports:
            print("✓ 所有数值限制 lastVerified 均处于有效期内，未发现陈旧项。")
        else:
            for r in stale_reports:
                if r.severity == SEVERITY_CRITICAL:
                    prefix = "✗ [严重过期/异常·阻断]"
                else:
                    prefix = "! [提示过期/警告]"
                print(f"{prefix} 项: {r.target} ({r.name})")
                print(f"    - 最后核实日期: {r.last_verified or '缺失'}")
                if r.age_days is not None:
                    print(f"    - 距离今天: {r.age_days} 天（阈值 {r.threshold_days} 天）")
                print(f"    - 强制拦截: {'是 (enforce=true)' if r.enforce else '否 (提示项)'}")
                print(f"    - 核对来源: {r.source_url}")
                print(f"    - 详情: {r.message}\n")

            print(
                f"总结: 共发现 {len(stale_reports)} 个过期/异常项（{len(critical_stale)} 个强制拦截项，{len(warning_stale)} 个提示/文件级项）"
            )

    # 导出到 GitHub Actions Step Summary (如果在 CI 中运行)
    write_github_summary(threshold_days, rationale, reports)

    if args.fail_all and stale_reports:
        return 1
    if args.fail_enforced and critical_stale:
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
