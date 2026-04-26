#!/usr/bin/env python3
"""Расчет токеновой нагрузки, GPU и CAPEX по assumptions.yaml (2026–2030)."""

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


def load_yaml(path: Path) -> dict[str, Any]:
    """Load YAML; fail gracefully if PyYAML is missing."""
    try:
        import yaml  # type: ignore
    except ModuleNotFoundError:
        python = Path(sys.executable).name
        print(
            "PyYAML не установлен. Установите зависимости и повторите запуск:\n"
            f"  {python} -m pip install -r requirements.txt",
            file=sys.stderr,
        )
        raise SystemExit(1)

    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)

    if not isinstance(data, dict):
        raise ValueError("assumptions.yaml должен содержать корневой mapping (dict).")
    return data


def to_year_map(src: dict[Any, Any]) -> dict[int, Any]:
    return {int(k): v for k, v in src.items()}


def as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def fmt_num(value: float | int | None, digits: int = 2) -> str:
    if value is None:
        return "NaN"
    if isinstance(value, float) and math.isnan(value):
        return "NaN"
    if digits == 0:
        return f"{int(round(float(value))):,}"
    return f"{float(value):,.{digits}f}"


def fmt_ratio(value: float | None) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "NaN"
    return f"{value * 100:.2f}%"


def harmonic_weighted_throughput(model_share: dict[str, float], throughput: dict[str, float]) -> float:
    """1 / sum(model_share / throughput_per_gpu)."""
    share_sum = sum(model_share.values())
    if share_sum <= 0:
        raise ValueError("compute_model.model_mix: сумма долей должна быть > 0")

    # Нормализуем доли на случай округлений в assumptions
    normalized = {m: s / share_sum for m, s in model_share.items()}

    denom = 0.0
    for model, share in normalized.items():
        tp = throughput.get(model)
        if tp is None:
            raise KeyError(f"Для модели '{model}' нет throughput_per_gpu")
        if tp <= 0:
            raise ValueError(f"throughput_per_gpu['{model}'] должен быть > 0")
        denom += share / tp

    if denom <= 0:
        raise ValueError("Некорректные входные данные для harmonic mean")
    return 1.0 / denom


def resolve_years(ass: dict[str, Any]) -> list[int]:
    usage = ass["usage_assumptions"]
    token_model = ass["token_load_model"]
    compute = ass["compute_model"]

    candidate_sets = [
        set(to_year_map(usage["Workplace.ai"]["activation_rate"]).keys()),
        set(to_year_map(token_model["Workplace.ai"]["tokens_per_active_user_per_day"]).keys()),
        set(to_year_map(usage["Contact_Center.ai"]["automation_rate"]).keys()),
        set(to_year_map(compute["model_mix"]).keys()),
        set(to_year_map(compute["infra"]["utilization"]).keys()),
    ]

    years = set(TARGET_YEARS)
    for year_set in candidate_sets:
        years &= year_set

    if not years:
        raise ValueError("Не удалось определить пересечение годов 2026–2030 в assumptions.yaml")

    return sorted(years)


def calculate(ass: dict[str, Any]) -> list[dict[str, Any]]:
    years = resolve_years(ass)

    usage = ass["usage_assumptions"]
    token_model = ass["token_load_model"]
    compute = ass["compute_model"]
    capex = ass.get("capex", {})

    wp_usage = usage["Workplace.ai"]
    cc_usage = usage["Contact_Center.ai"]

    wp_activation = to_year_map(wp_usage["activation_rate"])
    wp_tokens_per_user = to_year_map(token_model["Workplace.ai"]["tokens_per_active_user_per_day"])
    cc_automation = to_year_map(cc_usage["automation_rate"])

    model_mix_by_year = to_year_map(compute["model_mix"])
    util_by_year = to_year_map(compute["infra"]["utilization"])

    throughput = {name: float(val) for name, val in compute["throughput_per_gpu"].items()}

    working_days = float(token_model["time_assumptions"]["working_days_per_year"])
    calendar_days = float(token_model["time_assumptions"]["calendar_days_per_year"])
    working_hours = float(compute["infra"]["working_hours_per_day"])
    peak_factor = float(compute["infra"].get("peak_factor", 1.0))

    gpu_unit_cost = as_float(capex.get("gpu", {}).get("unit_cost"))
    infra_multiplier = as_float(capex.get("infra_multiplier", {}).get("value"))
    useful_life = int(capex.get("depreciation", {}).get("useful_life_years", capex.get("gpu", {}).get("useful_life_years", 5)))
    useful_life = max(useful_life, 1)

    seconds_per_year = working_days * working_hours * 3600.0
    if seconds_per_year <= 0:
        raise ValueError("working_days_per_year * working_hours_per_day * 3600 должно быть > 0")

    rows: list[dict[str, Any]] = []
    prev_required_gpu = 0
    total_capex_history: list[float] = []

    for year in years:
        active_users = float(wp_usage["total_employees"]) * float(wp_activation[year])

        wp_daily_tokens = active_users * float(wp_tokens_per_user[year])
        wp_annual_tokens = wp_daily_tokens * working_days

        automated_interactions = float(cc_usage["interactions_per_day"]) * float(cc_automation[year])
        cc_daily_tokens = automated_interactions * float(cc_usage["tokens_per_interaction"])
        cc_annual_tokens = cc_daily_tokens * calendar_days

        total_daily_tokens = wp_daily_tokens + cc_daily_tokens
        total_annual_tokens = wp_annual_tokens + cc_annual_tokens

        wp_share = wp_annual_tokens / total_annual_tokens if total_annual_tokens > 0 else float("nan")
        cc_share = cc_annual_tokens / total_annual_tokens if total_annual_tokens > 0 else float("nan")

        mix = {model: float(share) for model, share in model_mix_by_year[year].items()}
        weighted_tp = harmonic_weighted_throughput(mix, throughput)

        utilization = float(util_by_year[year])
        if utilization <= 0:
            raise ValueError(f"compute_model.infra.utilization[{year}] должен быть > 0")

        tokens_per_second = total_annual_tokens / seconds_per_year
        required_gpu_raw = tokens_per_second / (weighted_tp * utilization) * peak_factor
        required_gpu = int(math.ceil(required_gpu_raw))

        if year == years[0]:
            required_gpu_increment = required_gpu
        else:
            required_gpu_increment = max(required_gpu - prev_required_gpu, 0)

        # Если unit_cost или infra_multiplier отсутствуют/null — CAPEX = NaN по условию задачи.
        if gpu_unit_cost is None or infra_multiplier is None:
            gpu_capex = float("nan")
            total_capex = float("nan")
        else:
            gpu_capex = required_gpu_increment * gpu_unit_cost
            total_capex = gpu_capex * infra_multiplier

        total_capex_history.append(total_capex)
        window = total_capex_history[-useful_life:]
        annual_depreciation = float("nan") if any(math.isnan(v) for v in window) else sum(window) / useful_life

        rows.append(
            {
                "year": year,
                "active_users": active_users,
                "workplace_daily_tokens": wp_daily_tokens,
                "workplace_annual_tokens": wp_annual_tokens,
                "automated_interactions": automated_interactions,
                "contact_center_daily_tokens": cc_daily_tokens,
                "contact_center_annual_tokens": cc_annual_tokens,
                "total_daily_tokens": total_daily_tokens,
                "total_annual_tokens": total_annual_tokens,
                "workplace_token_share": wp_share,
                "contact_center_token_share": cc_share,
                "weighted_throughput": weighted_tp,
                "tokens_per_second": tokens_per_second,
                "required_gpu": required_gpu,
                "required_gpu_increment": required_gpu_increment,
                "gpu_capex": gpu_capex,
                "total_capex": total_capex,
                "annual_depreciation": annual_depreciation,
            }
        )

        prev_required_gpu = required_gpu

    return rows


def write_csv(rows: list[dict[str, Any]], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = [
        "year",
        "active_users",
        "workplace_daily_tokens",
        "workplace_annual_tokens",
        "automated_interactions",
        "contact_center_daily_tokens",
        "contact_center_annual_tokens",
        "total_daily_tokens",
        "total_annual_tokens",
        "workplace_token_share",
        "contact_center_token_share",
        "weighted_throughput",
        "tokens_per_second",
        "required_gpu",
        "required_gpu_increment",
        "gpu_capex",
        "total_capex",
        "annual_depreciation",
    ]

    with output.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def build_html(rows: list[dict[str, Any]]) -> str:
    token_rows = "\n".join(
        (
            f"<tr><td>{r['year']}</td><td>{fmt_num(r['active_users'], 0)}</td>"
            f"<td>{fmt_num(r['workplace_daily_tokens'], 0)}</td><td>{fmt_num(r['workplace_annual_tokens'], 0)}</td>"
            f"<td>{fmt_num(r['automated_interactions'], 0)}</td><td>{fmt_num(r['contact_center_daily_tokens'], 0)}</td>"
            f"<td>{fmt_num(r['contact_center_annual_tokens'], 0)}</td></tr>"
        )
        for r in rows
    )

    gpu_rows = "\n".join(
        (
            f"<tr><td>{r['year']}</td><td>{fmt_num(r['weighted_throughput'], 2)}</td>"
            f"<td>{fmt_num(r['tokens_per_second'], 2)}</td><td>{fmt_num(r['required_gpu'], 0)}</td>"
            f"<td>{fmt_num(r['required_gpu_increment'], 0)}</td></tr>"
        )
        for r in rows
    )

    capex_rows = "\n".join(
        (
            f"<tr><td>{r['year']}</td><td>{fmt_num(r['gpu_capex'], 2)}</td>"
            f"<td>{fmt_num(r['total_capex'], 2)}</td><td>{fmt_num(r['annual_depreciation'], 2)}</td></tr>"
        )
        for r in rows
    )

    summary_rows = "\n".join(
        (
            f"<tr><td>{r['year']}</td><td>{fmt_num(r['total_daily_tokens'], 0)}</td>"
            f"<td>{fmt_num(r['total_annual_tokens'], 0)}</td><td>{fmt_ratio(r['workplace_token_share'])}</td>"
            f"<td>{fmt_ratio(r['contact_center_token_share'])}</td></tr>"
        )
        for r in rows
    )

    return f"""<!doctype html>
<html lang=\"ru\">
<head>
  <meta charset=\"utf-8\" />
  <title>GPS Finmodel</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 24px; color: #1f2937; }}
    table {{ border-collapse: collapse; width: 100%; margin: 12px 0 28px; }}
    th, td {{ border: 1px solid #d1d5db; padding: 8px; text-align: right; }}
    th:first-child, td:first-child {{ text-align: center; }}
    thead {{ background: #f3f4f6; }}
    .note {{ background: #f9fafb; border: 1px solid #e5e7eb; border-radius: 8px; padding: 12px; }}
  </style>
</head>
<body>
  <h1>GPS Finmodel Report (2026–2030)</h1>

  <div class=\"note\">
    <b>Ключевые формулы:</b>
    <ul>
      <li>Workplace annual tokens = active_users × tokens_per_active_user_per_day × working_days_per_year</li>
      <li>Contact Center annual tokens = interactions_per_day × automation_rate × tokens_per_interaction × calendar_days_per_year</li>
      <li>weighted_throughput = 1 / Σ(model_share / throughput_per_gpu)</li>
      <li>tokens_per_second = total_annual_tokens / (working_days_per_year × working_hours_per_day × 3600)</li>
      <li>required_gpu = ceil(tokens_per_second / (weighted_throughput × utilization) × peak_factor)</li>
      <li>required_gpu_increment = max(required_gpu_t − required_gpu_(t−1), 0), для первого года = required_gpu</li>
      <li>gpu_capex = required_gpu_increment × gpu.unit_cost</li>
      <li>total_capex = gpu_capex × infra_multiplier</li>
      <li>annual_depreciation = среднее total_capex за последние useful_life_years</li>
    </ul>
  </div>

  <h2>1. Token Load by Product</h2>
  <table>
    <thead>
      <tr>
        <th>Year</th><th>Workplace active_users</th><th>Workplace daily_tokens</th><th>Workplace annual_tokens</th>
        <th>Contact Center automated_interactions</th><th>Contact Center daily_tokens</th><th>Contact Center annual_tokens</th>
      </tr>
    </thead>
    <tbody>{token_rows}</tbody>
  </table>

  <h2>2. GPU Calculation</h2>
  <table>
    <thead>
      <tr><th>Year</th><th>weighted_throughput</th><th>tokens_per_second</th><th>required_gpu</th><th>required_gpu_increment</th></tr>
    </thead>
    <tbody>{gpu_rows}</tbody>
  </table>

  <h2>3. CAPEX</h2>
  <table>
    <thead>
      <tr><th>Year</th><th>gpu_capex</th><th>total_capex</th><th>annual_depreciation</th></tr>
    </thead>
    <tbody>{capex_rows}</tbody>
  </table>

  <h2>4. Summary</h2>
  <table>
    <thead>
      <tr><th>Year</th><th>total_daily_tokens</th><th>total_annual_tokens</th><th>Workplace token share</th><th>Contact Center token share</th></tr>
    </thead>
    <tbody>{summary_rows}</tbody>
  </table>
</body>
</html>
"""


def write_html(rows: list[dict[str, Any]], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(build_html(rows), encoding="utf-8")


def main() -> None:
    assumptions = load_yaml(Path("assumptions.yaml"))

    # Наличие секций, обязательных по условию задачи
    for section in ("usage_assumptions", "token_load_model"):
        if section not in assumptions:
            raise KeyError(f"В assumptions.yaml отсутствует обязательная секция: {section}")

    rows = calculate(assumptions)
    write_csv(rows, OUT_CSV)
    write_html(rows, OUT_HTML)

    print("year | total_annual_tokens | required_gpu | required_gpu_increment | total_capex")
    print("-" * 90)
    for r in rows:
        print(
            f"{r['year']} | {fmt_num(r['total_annual_tokens'], 0)} | {fmt_num(r['required_gpu'], 0)} | "
            f"{fmt_num(r['required_gpu_increment'], 0)} | {fmt_num(r['total_capex'], 2)}"
        )

    print(f"\nCSV: {OUT_CSV}")
    print(f"HTML: {OUT_HTML}")


if __name__ == "__main__":
    main()
