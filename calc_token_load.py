#!/usr/bin/env python3
"""GPS Finmodel: token load, GPU sizing, CAPEX and depreciation."""

from __future__ import annotations

import csv
import math
import sys
from pathlib import Path
from typing import Any

OUT_DIR = Path("output")
OUT_HTML = OUT_DIR / "gps_finmodel.html"
OUT_CSV = OUT_DIR / "gps_finmodel_results.csv"
TARGET_YEARS = [2026, 2027, 2028, 2029, 2030]


def _load_yaml(path: Path) -> dict[str, Any]:
    try:
        import yaml  # type: ignore
    except ModuleNotFoundError as exc:
        python = Path(sys.executable).name
        raise SystemExit(
            "PyYAML не установлен. Установите зависимость и повторите запуск:\n"
            f"  {python} -m pip install -r requirements.txt"
        ) from exc

    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _num(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _year_map(mapping: dict[str, Any] | dict[int, Any]) -> dict[int, Any]:
    return {int(k): v for k, v in mapping.items()}


def _fmt_num(value: float | None, digits: int = 2) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "NaN"
    if digits == 0:
        return f"{int(round(value)):,}"
    return f"{value:,.{digits}f}"


def _fmt_ratio(value: float | None) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "NaN"
    return f"{value * 100:.2f}%"


def _resolve_years(assumptions: dict[str, Any]) -> list[int]:
    usage = assumptions["Usage_assumptions"]
    token_cfg = assumptions["Token_load_model"]
    compute = assumptions["compute_model"]

    sources = [
        _year_map(usage["Workplace.ai"]["activation_rate"]),
        _year_map(token_cfg["Workplace.ai"]["tokens_per_active_user_per_day"]),
        _year_map(usage["Contact_Center.ai"]["automation_rate"]),
        _year_map(compute["infra"]["utilization"]),
        _year_map(compute["model_mix"]),
    ]

    years = set(TARGET_YEARS)
    for src in sources:
        years &= set(src.keys())

    if not years:
        raise ValueError("Не удалось определить годы расчета: проверьте year-ключи в assumptions.yaml")

    return sorted(years)


def _weighted_throughput(model_mix: dict[str, float], throughput_per_gpu: dict[str, float]) -> float:
    total_share = sum(model_mix.values())
    if total_share <= 0:
        raise ValueError("model_mix должен иметь сумму долей > 0")

    normalized_mix = {model: share / total_share for model, share in model_mix.items()}
    denom = 0.0
    for model_name, share in normalized_mix.items():
        throughput = throughput_per_gpu.get(model_name)
        if throughput is None:
            raise KeyError(f"throughput_per_gpu не содержит модель '{model_name}'")
        if throughput <= 0:
            raise ValueError(f"throughput_per_gpu['{model_name}'] должен быть > 0")
        denom += share / throughput

    if denom <= 0:
        raise ValueError("Некорректные model_mix/throughput_per_gpu: делитель <= 0")

    return 1.0 / denom


def build_model(assumptions: dict[str, Any]) -> list[dict[str, Any]]:
    years = _resolve_years(assumptions)
    usage = assumptions["Usage_assumptions"]
    token_cfg = assumptions["Token_load_model"]
    time_cfg = token_cfg["time_assumptions"]
    compute = assumptions["compute_model"]
    capex = assumptions["capex"]

    wp_usage = usage["Workplace.ai"]
    cc_usage = usage["Contact_Center.ai"]

    activation = _year_map(wp_usage["activation_rate"])
    wp_tokens_per_user_day = _year_map(token_cfg["Workplace.ai"]["tokens_per_active_user_per_day"])
    automation = _year_map(cc_usage["automation_rate"])

    utilization = _year_map(compute["infra"]["utilization"])
    model_mix_by_year = _year_map(compute["model_mix"])
    throughput_per_gpu = {name: float(value) for name, value in compute["throughput_per_gpu"].items()}

    working_days = int(time_cfg["working_days_per_year"])
    calendar_days = int(time_cfg["calendar_days_per_year"])
    working_hours = float(compute["infra"]["working_hours_per_day"])
    peak_factor = float(compute["infra"]["peak_factor"])

    gpu_unit_cost = _num(capex.get("gpu_unit_cost_usd"))
    if gpu_unit_cost is None:
        gpu_unit_cost = _num(capex.get("gpu", {}).get("unit_cost"))

    infra_cost_per_gpu = _num(capex.get("infra_cost_per_gpu_usd"))
    infra_multiplier = _num(capex.get("infra_multiplier", {}).get("value"))

    platform_capex_map = _year_map(capex.get("platform_capex_usd", {}))
    useful_life = max(int(capex.get("useful_life_years", 4)), 1)

    rows: list[dict[str, Any]] = []
    capex_history: list[float] = []
    prev_required_gpu = 0

    seconds_per_year = working_days * working_hours * 3600
    if seconds_per_year <= 0:
        raise ValueError("working_days_per_year * working_hours_per_day * 3600 должно быть > 0")

    for year in years:
        active_users = float(wp_usage["total_employees"]) * float(activation[year])
        wp_daily_tokens = active_users * float(wp_tokens_per_user_day[year])
        wp_annual_tokens = wp_daily_tokens * working_days

        automated_interactions = float(cc_usage["interactions_per_day"]) * float(automation[year])
        cc_daily_tokens = automated_interactions * float(cc_usage["tokens_per_interaction"])
        cc_annual_tokens = cc_daily_tokens * calendar_days

        total_daily_tokens = wp_daily_tokens + cc_daily_tokens
        total_annual_tokens = wp_annual_tokens + cc_annual_tokens

        wp_share = wp_annual_tokens / total_annual_tokens if total_annual_tokens else float("nan")
        cc_share = cc_annual_tokens / total_annual_tokens if total_annual_tokens else float("nan")

        mix = {model: float(share) for model, share in model_mix_by_year[year].items()}
        weighted_tp = _weighted_throughput(mix, throughput_per_gpu)

        util = float(utilization[year])
        if util <= 0:
            raise ValueError(f"utilization[{year}] должен быть > 0")

        tokens_per_second = total_annual_tokens / seconds_per_year
        req_gpu_raw = tokens_per_second / (weighted_tp * util) * peak_factor
        required_gpu = int(math.ceil(req_gpu_raw))

        required_gpu_increment = required_gpu if year == years[0] else max(required_gpu - prev_required_gpu, 0)

        if gpu_unit_cost is None or (infra_multiplier is None and infra_cost_per_gpu is None):
            gpu_capex = float("nan")
        elif infra_cost_per_gpu is not None:
            gpu_capex = required_gpu_increment * (gpu_unit_cost + infra_cost_per_gpu)
        else:
            gpu_capex = required_gpu_increment * gpu_unit_cost * infra_multiplier

        platform_capex = float(platform_capex_map.get(year, 0.0))
        total_capex = float("nan") if math.isnan(gpu_capex) else gpu_capex + platform_capex

        capex_history.append(total_capex)
        recent = capex_history[-useful_life:]
        annual_depreciation = float("nan") if any(math.isnan(v) for v in recent) else sum(recent) / useful_life

        rows.append(
            {
                "year": year,
                "active_users": active_users,
                "wp_daily_tokens": wp_daily_tokens,
                "wp_annual_tokens": wp_annual_tokens,
                "automated_interactions": automated_interactions,
                "cc_daily_tokens": cc_daily_tokens,
                "cc_annual_tokens": cc_annual_tokens,
                "total_daily_tokens": total_daily_tokens,
                "total_annual_tokens": total_annual_tokens,
                "wp_token_share": wp_share,
                "cc_token_share": cc_share,
                "weighted_throughput": weighted_tp,
                "tokens_per_second": tokens_per_second,
                "required_gpu": required_gpu,
                "required_gpu_increment": required_gpu_increment,
                "gpu_capex": gpu_capex,
                "platform_capex": platform_capex,
                "total_capex": total_capex,
                "annual_depreciation": annual_depreciation,
            }
        )

        prev_required_gpu = required_gpu

    return rows


def write_csv(rows: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "year",
        "active_users",
        "wp_daily_tokens",
        "wp_annual_tokens",
        "automated_interactions",
        "cc_daily_tokens",
        "cc_annual_tokens",
        "total_daily_tokens",
        "total_annual_tokens",
        "wp_token_share",
        "cc_token_share",
        "weighted_throughput",
        "tokens_per_second",
        "required_gpu",
        "required_gpu_increment",
        "gpu_capex",
        "platform_capex",
        "total_capex",
        "annual_depreciation",
    ]

    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            out = row.copy()
            for key in ("gpu_capex", "total_capex", "annual_depreciation"):
                if isinstance(out[key], float) and math.isnan(out[key]):
                    out[key] = "NaN"
            writer.writerow(out)


def build_html(rows: list[dict[str, Any]]) -> str:
    token_rows = "\n".join(
        f"<tr><td>{r['year']}</td><td>{_fmt_num(r['active_users'], 0)}</td><td>{_fmt_num(r['wp_daily_tokens'], 0)}</td>"
        f"<td>{_fmt_num(r['wp_annual_tokens'], 0)}</td><td>{_fmt_num(r['automated_interactions'], 0)}</td>"
        f"<td>{_fmt_num(r['cc_daily_tokens'], 0)}</td><td>{_fmt_num(r['cc_annual_tokens'], 0)}</td></tr>"
        for r in rows
    )

    gpu_rows = "\n".join(
        f"<tr><td>{r['year']}</td><td>{_fmt_num(r['weighted_throughput'], 2)}</td><td>{_fmt_num(r['tokens_per_second'], 2)}</td>"
        f"<td>{_fmt_num(r['required_gpu'], 0)}</td><td>{_fmt_num(r['required_gpu_increment'], 0)}</td></tr>"
        for r in rows
    )

    capex_rows = "\n".join(
        f"<tr><td>{r['year']}</td><td>{_fmt_num(r['gpu_capex'], 2)}</td><td>{_fmt_num(r['platform_capex'], 2)}</td>"
        f"<td>{_fmt_num(r['total_capex'], 2)}</td><td>{_fmt_num(r['annual_depreciation'], 2)}</td></tr>"
        for r in rows
    )

    summary_rows = "\n".join(
        f"<tr><td>{r['year']}</td><td>{_fmt_num(r['total_daily_tokens'], 0)}</td><td>{_fmt_num(r['total_annual_tokens'], 0)}</td>"
        f"<td>{_fmt_ratio(r['wp_token_share'])}</td><td>{_fmt_ratio(r['cc_token_share'])}</td></tr>"
        for r in rows
    )

    return f"""<!doctype html>
<html lang=\"ru\"><head><meta charset=\"utf-8\"><title>GPS Finmodel</title>
<style>
body{{font-family:Arial,sans-serif;margin:24px;color:#1f2937}}
table{{border-collapse:collapse;width:100%;margin:10px 0 28px}}
th,td{{border:1px solid #ddd;padding:8px;text-align:right}}
th:first-child,td:first-child{{text-align:center}}
thead{{background:#f3f4f6}} h2{{margin-top:28px}}
.note{{background:#f9fafb;border:1px solid #e5e7eb;padding:12px;border-radius:8px}}
</style></head><body>
<h1>GPS Finmodel Report (2026–2030)</h1>
<div class=\"note\">
<p><b>Формулы (описание):</b></p>
<ul>
<li>weighted_throughput = 1 / Σ(model_share / throughput_per_gpu)</li>
<li>tokens_per_second = total_annual_tokens / (working_days_per_year * working_hours_per_day * 3600)</li>
<li>required_gpu = ceil(tokens_per_second / (weighted_throughput * utilization) * peak_factor)</li>
<li>required_gpu_increment = max(required_gpu_t - required_gpu_(t-1), 0); для первого года = required_gpu</li>
<li>gpu_capex = required_gpu_increment * (gpu_unit_cost + infra_cost_per_gpu) или * infra_multiplier</li>
<li>annual_depreciation = сумма total_capex за последние useful_life_years / useful_life_years</li>
</ul>
</div>

<h2>1) Token Load by Product</h2>
<table><thead><tr><th>Year</th><th>Active users (Workplace)</th><th>Workplace daily tokens</th><th>Workplace annual tokens</th><th>Automated interactions (CC)</th><th>CC daily tokens</th><th>CC annual tokens</th></tr></thead>
<tbody>{token_rows}</tbody></table>

<h2>2) GPU Calculation</h2>
<table><thead><tr><th>Year</th><th>Weighted throughput</th><th>Tokens per second</th><th>Required GPU</th><th>Required GPU increment</th></tr></thead>
<tbody>{gpu_rows}</tbody></table>

<h2>3) CAPEX</h2>
<table><thead><tr><th>Year</th><th>GPU CAPEX</th><th>Platform CAPEX</th><th>Total CAPEX</th><th>Annual depreciation</th></tr></thead>
<tbody>{capex_rows}</tbody></table>

<h2>4) Summary</h2>
<table><thead><tr><th>Year</th><th>Total daily tokens</th><th>Total annual tokens</th><th>Workplace share</th><th>Contact Center share</th></tr></thead>
<tbody>{summary_rows}</tbody></table>
</body></html>"""


def write_html(rows: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(build_html(rows), encoding="utf-8")


def print_console(rows: list[dict[str, Any]]) -> None:
    print("year | total_annual_tokens | required_gpu | required_gpu_increment | total_capex | annual_depreciation")
    print("-" * 110)
    for row in rows:
        print(
            f"{row['year']} | {_fmt_num(row['total_annual_tokens'], 0)} | {_fmt_num(row['required_gpu'], 0)} | "
            f"{_fmt_num(row['required_gpu_increment'], 0)} | {_fmt_num(row['total_capex'], 2)} | {_fmt_num(row['annual_depreciation'], 2)}"
        )


def main() -> None:
    assumptions = _load_yaml(Path("assumptions.yaml"))
    rows = build_model(assumptions)

    write_csv(rows, OUT_CSV)
    write_html(rows, OUT_HTML)
    print_console(rows)
    print(f"\nCSV: {OUT_CSV}")
    print(f"HTML: {OUT_HTML}")


if __name__ == "__main__":
    main()
