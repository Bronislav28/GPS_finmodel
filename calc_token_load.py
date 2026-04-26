#!/usr/bin/env python3
"""GPS Finmodel: token load, GPU sizing, CAPEX and depreciation (2026–2030)."""

from __future__ import annotations

from pathlib import Path
import csv
import math
import sys
from typing import Any

YEARS = [2026, 2027, 2028, 2029, 2030]
OUT_DIR = Path("output")
OUT_HTML = OUT_DIR / "gps_finmodel.html"
OUT_CSV = OUT_DIR / "gps_finmodel_results.csv"


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


def _weighted_throughput(model_mix: dict[str, float], throughput_per_gpu: dict[str, float]) -> float:
    denom = 0.0
    for model_name, share in model_mix.items():
        t = throughput_per_gpu.get(model_name)
        if t is None:
            raise KeyError(f"throughput_per_gpu не содержит модель '{model_name}'")
        denom += share / t
    if denom <= 0:
        raise ValueError("Некорректные model_mix/throughput_per_gpu: делитель <= 0")
    return 1.0 / denom


def _fmt_num(value: float | None, digits: int = 2) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "NaN"
    if float(value).is_integer() and digits == 0:
        return f"{int(value):,}"
    return f"{value:,.{digits}f}"


def _fmt_ratio(value: float | None) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "NaN"
    return f"{value * 100:.2f}%"


def build_model(assumptions: dict[str, Any]) -> list[dict[str, Any]]:
    usage = assumptions["Usage_assumptions"]
    token_cfg = assumptions["Token_load_model"]
    time_cfg = token_cfg["time_assumptions"]
    compute = assumptions["compute_model"]
    capex = assumptions["capex"]

    wp_usage = usage["Workplace.ai"]
    cc_usage = usage["Contact_Center.ai"]
    wp_model = token_cfg["Workplace.ai"]

    activation = _year_map(wp_usage["activation_rate"])
    wp_tokens_per_user_day = _year_map(wp_model["tokens_per_active_user_per_day"])
    automation = _year_map(cc_usage["automation_rate"])

    utilization = _year_map(compute["infra"]["utilization"])
    model_mix_by_year = {int(y): mix for y, mix in compute["model_mix"].items()}
    throughput_per_gpu = {k: float(v) for k, v in compute["throughput_per_gpu"].items()}

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
    useful_life = int(capex.get("useful_life_years", 4))

    rows: list[dict[str, Any]] = []
    capex_history: list[float] = []
    prev_required_gpu = 0

    for year in YEARS:
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

        mix = {k: float(v) for k, v in model_mix_by_year[year].items()}
        weighted_tp = _weighted_throughput(mix, throughput_per_gpu)

        seconds_per_year = working_days * working_hours * 3600
        tokens_per_second = total_annual_tokens / seconds_per_year
        req_gpu_raw = tokens_per_second / (weighted_tp * float(utilization[year])) * peak_factor
        required_gpu = int(math.ceil(req_gpu_raw))

        required_gpu_increment = required_gpu if year == YEARS[0] else max(required_gpu - prev_required_gpu, 0)

        if gpu_unit_cost is None or (infra_multiplier is None and infra_cost_per_gpu is None):
            gpu_capex = float("nan")
        else:
            if infra_cost_per_gpu is not None:
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
            for k in ("gpu_capex", "total_capex", "annual_depreciation"):
                if isinstance(out[k], float) and math.isnan(out[k]):
                    out[k] = "NaN"
            writer.writerow(out)


def build_html(rows: list[dict[str, Any]]) -> str:
    token_rows = "\n".join(
        f"<tr><td>{r['year']}</td><td>{_fmt_num(r['active_users'],0)}</td><td>{_fmt_num(r['wp_daily_tokens'],0)}</td>"
        f"<td>{_fmt_num(r['wp_annual_tokens'],0)}</td><td>{_fmt_num(r['automated_interactions'],0)}</td>"
        f"<td>{_fmt_num(r['cc_daily_tokens'],0)}</td><td>{_fmt_num(r['cc_annual_tokens'],0)}</td></tr>"
        for r in rows
    )

    gpu_rows = "\n".join(
        f"<tr><td>{r['year']}</td><td>{_fmt_num(r['weighted_throughput'],2)}</td><td>{_fmt_num(r['tokens_per_second'],2)}</td>"
        f"<td>{_fmt_num(r['required_gpu'],0)}</td><td>{_fmt_num(r['required_gpu_increment'],0)}</td></tr>"
        for r in rows
    )

    capex_rows = "\n".join(
        f"<tr><td>{r['year']}</td><td>{_fmt_num(r['gpu_capex'],2)}</td><td>{_fmt_num(r['platform_capex'],2)}</td>"
        f"<td>{_fmt_num(r['total_capex'],2)}</td><td>{_fmt_num(r['annual_depreciation'],2)}</td></tr>"
        for r in rows
    )

    summary_rows = "\n".join(
        f"<tr><td>{r['year']}</td><td>{_fmt_num(r['total_daily_tokens'],0)}</td><td>{_fmt_num(r['total_annual_tokens'],0)}</td>"
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
<li>required_gpu_increment = max(required_gpu_t - required_gpu_(t-1), 0); для 2026 = required_gpu</li>
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
    for r in rows:
        print(
            f"{r['year']} | {_fmt_num(r['total_annual_tokens'],0)} | {_fmt_num(r['required_gpu'],0)} | "
            f"{_fmt_num(r['required_gpu_increment'],0)} | {_fmt_num(r['total_capex'],2)} | {_fmt_num(r['annual_depreciation'],2)}"
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
