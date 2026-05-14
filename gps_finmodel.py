#!/usr/bin/env python3
"""GPS finmodel YAML validator (issue #119 scope)."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

try:
    import yaml  # type: ignore
except ModuleNotFoundError as exc:  # pragma: no cover
    raise SystemExit("PyYAML is required. Install dependencies with: python -m pip install -r requirements.txt") from exc

ASSUMPTIONS_PATH = Path("assumptions.yaml")
OUT_DIR = Path("output")
OUT_TXT = OUT_DIR / "gps_finmodel_validation_report.txt"
OUT_CSV = OUT_DIR / "gps_finmodel_validation_report.csv"
OUT_CALENDAR_CSV = OUT_DIR / "gps_finmodel_calendar.csv"
OUT_EVENTS_CSV = OUT_DIR / "gps_finmodel_events.csv"
OUT_MONTHLY_DEMAND_GPU_CSV = OUT_DIR / "gps_finmodel_monthly_demand_gpu.csv"


@dataclass
class ValidationItem:
    level: str
    path: str
    message: str


def load_assumptions(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict):
        raise ValueError("Root of assumptions.yaml must be a mapping.")
    return data


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _require_mapping(items: list[ValidationItem], data: dict[str, Any], key: str) -> dict[str, Any]:
    value = data.get(key)
    if not isinstance(value, dict):
        items.append(ValidationItem("ERROR", key, "Missing section or expected mapping."))
        return {}
    return value


def validate(data: dict[str, Any]) -> list[ValidationItem]:
    items: list[ValidationItem] = []

    for key in ["model", "products", "usage_assumptions", "token_load_model", "compute_model"]:
        if key not in data:
            items.append(ValidationItem("ERROR", key, "Missing required top-level key."))

    model = _require_mapping(items, data, "model")
    fs = model.get("forecast_start", {}) if isinstance(model.get("forecast_start"), dict) else {}
    fe = model.get("forecast_end", {}) if isinstance(model.get("forecast_end"), dict) else {}
    for edge_name, edge in [("model.forecast_start", fs), ("model.forecast_end", fe)]:
        y = edge.get("year")
        m = edge.get("month")
        if not isinstance(y, int):
            items.append(ValidationItem("ERROR", f"{edge_name}.year", "Must be integer."))
        if not isinstance(m, int) or not (1 <= m <= 12):
            items.append(ValidationItem("ERROR", f"{edge_name}.month", "Must be integer in [1..12]."))

    products = data.get("products")
    if not isinstance(products, list) or not products:
        items.append(ValidationItem("ERROR", "products", "Must be a non-empty list."))
    else:
        token_share_sum = 0.0
        names: set[str] = set()
        for i, product in enumerate(products):
            ppath = f"products[{i}]"
            if not isinstance(product, dict):
                items.append(ValidationItem("ERROR", ppath, "Each product must be a mapping."))
                continue
            name = product.get("name")
            if not isinstance(name, str) or not name.strip():
                items.append(ValidationItem("ERROR", f"{ppath}.name", "Must be non-empty string."))
            elif name in names:
                items.append(ValidationItem("ERROR", f"{ppath}.name", "Duplicate product name."))
            else:
                names.add(name)
            share = product.get("token_distribution_assumption")
            if _is_number(share):
                token_share_sum += float(share)
            else:
                items.append(ValidationItem("ERROR", f"{ppath}.token_distribution_assumption", "Must be numeric."))
        if abs(token_share_sum - 1.0) > 1e-6:
            items.append(ValidationItem("WARNING", "products", f"token_distribution_assumption sum is {token_share_sum:.6f}, expected 1.0."))

    usage = _require_mapping(items, data, "usage_assumptions")
    token_model = _require_mapping(items, data, "token_load_model")
    for product_name in usage:
        if product_name not in token_model:
            items.append(ValidationItem("WARNING", f"token_load_model.{product_name}", "Product missing in token_load_model."))

    compute = _require_mapping(items, data, "compute_model")
    throughput = compute.get("throughput_per_gpu") if isinstance(compute.get("throughput_per_gpu"), dict) else {}
    for klass in ["frontier", "large", "medium", "small"]:
        value = throughput.get(klass)
        if not _is_number(value) or float(value) <= 0:
            items.append(ValidationItem("ERROR", f"compute_model.throughput_per_gpu.{klass}", "Must be positive numeric."))

    if not items:
        items.append(ValidationItem("OK", "root", "Validation passed with no findings."))
    return items


def write_reports(items: list[ValidationItem]) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    with OUT_CSV.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["level", "path", "message"])
        for item in items:
            writer.writerow([item.level, item.path, item.message])

    errors = sum(1 for x in items if x.level == "ERROR")
    warnings = sum(1 for x in items if x.level == "WARNING")
    oks = sum(1 for x in items if x.level == "OK")

    with OUT_TXT.open("w", encoding="utf-8") as fh:
        fh.write("GPS finmodel YAML validation report\n")
        fh.write("===================================\n")
        fh.write(f"Errors: {errors}\n")
        fh.write(f"Warnings: {warnings}\n")
        fh.write(f"OK: {oks}\n\n")
        fh.write("Findings:\n")
        for item in items:
            fh.write(f"- [{item.level}] {item.path}: {item.message}\n")


def build_monthly_calendar(data: dict[str, Any]) -> list[dict[str, Any]]:
    model = data.get("model", {}) if isinstance(data.get("model"), dict) else {}
    fs = model.get("forecast_start", {}) if isinstance(model.get("forecast_start"), dict) else {}
    fe = model.get("forecast_end", {}) if isinstance(model.get("forecast_end"), dict) else {}

    start_year = fs.get("year")
    start_month = fs.get("month")
    end_year = fe.get("year")
    end_month = fe.get("month")

    if not all(isinstance(x, int) for x in [start_year, start_month, end_year, end_month]):
        return []
    if not (1 <= start_month <= 12 and 1 <= end_month <= 12):
        return []

    start_idx = start_year * 12 + (start_month - 1)
    end_idx = end_year * 12 + (end_month - 1)
    if end_idx < start_idx:
        return []

    rows: list[dict[str, Any]] = []
    for idx in range(start_idx, end_idx + 1):
        year = idx // 12
        month = idx % 12 + 1
        month_start = date(year, month, 1)
        month_seq = idx - start_idx + 1
        forecast_year = year - start_year + 1
        rows.append({
            "month_seq": month_seq,
            "year": year,
            "month": month,
            "month_id": f"{year:04d}-{month:02d}",
            "month_start": month_start.isoformat(),
            "is_forecast_start": int(idx == start_idx),
            "is_forecast_end": int(idx == end_idx),
            "forecast_year": forecast_year,
        })
    return rows


def resolve_events(calendar_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not calendar_rows:
        return []

    events: list[dict[str, Any]] = []
    for row in calendar_rows:
        month_seq = int(row["month_seq"])
        year = int(row["year"])
        month = int(row["month"])

        if row["is_forecast_start"]:
            events.append({
                "event_id": "forecast_start",
                "event_type": "boundary",
                "event_name": "Forecast start",
                "month_seq": month_seq,
                "month_id": row["month_id"],
                "year": year,
                "month": month,
            })
        if row["is_forecast_end"]:
            events.append({
                "event_id": "forecast_end",
                "event_type": "boundary",
                "event_name": "Forecast end",
                "month_seq": month_seq,
                "month_id": row["month_id"],
                "year": year,
                "month": month,
            })
        if month == 1:
            events.append({
                "event_id": f"year_start_{year}",
                "event_type": "period",
                "event_name": "Year start",
                "month_seq": month_seq,
                "month_id": row["month_id"],
                "year": year,
                "month": month,
            })
        if month == 12:
            events.append({
                "event_id": f"year_end_{year}",
                "event_type": "period",
                "event_name": "Year end",
                "month_seq": month_seq,
                "month_id": row["month_id"],
                "year": year,
                "month": month,
            })

    return events


def write_calendar_and_events(data: dict[str, Any]) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    calendar_rows = build_monthly_calendar(data)
    event_rows = resolve_events(calendar_rows)

    with OUT_CALENDAR_CSV.open("w", newline="", encoding="utf-8") as fh:
        fieldnames = [
            "month_seq",
            "year",
            "month",
            "month_id",
            "month_start",
            "is_forecast_start",
            "is_forecast_end",
            "forecast_year",
        ]
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(calendar_rows)

    with OUT_EVENTS_CSV.open("w", newline="", encoding="utf-8") as fh:
        fieldnames = ["event_id", "event_type", "event_name", "month_seq", "month_id", "year", "month"]
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(event_rows)


def _year_value(mapping: Any, year: int) -> float:
    if not isinstance(mapping, dict):
        return 0.0
    value = mapping.get(year, mapping.get(str(year)))
    return float(value) if _is_number(value) else 0.0


def build_monthly_demand_gpu(data: dict[str, Any], calendar_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    usage = data.get("usage_assumptions", {}) if isinstance(data.get("usage_assumptions"), dict) else {}
    token_model = data.get("token_load_model", {}) if isinstance(data.get("token_load_model"), dict) else {}
    compute = data.get("compute_model", {}) if isinstance(data.get("compute_model"), dict) else {}

    workplace_usage = usage.get("Workplace.ai", {}) if isinstance(usage.get("Workplace.ai"), dict) else {}
    workplace_token = token_model.get("Workplace.ai", {}) if isinstance(token_model.get("Workplace.ai"), dict) else {}
    cc_usage = usage.get("Contact_Center.ai", {}) if isinstance(usage.get("Contact_Center.ai"), dict) else {}
    cc_token = token_model.get("Contact_Center.ai", {}) if isinstance(token_model.get("Contact_Center.ai"), dict) else {}

    time_assumptions = token_model.get("time_assumptions", {}) if isinstance(token_model.get("time_assumptions"), dict) else {}
    working_days_per_year = float(time_assumptions.get("working_days_per_year", 247))

    total_employees = float(workplace_usage.get("total_employees", 0))
    interactions_per_day = float(cc_usage.get("interactions_per_day", 0))
    cc_tokens_per_interaction = float(cc_token.get("tokens_per_interaction", 0))

    model_mix = compute.get("model_mix", {}) if isinstance(compute.get("model_mix"), dict) else {}
    throughput = compute.get("throughput_per_gpu", {}) if isinstance(compute.get("throughput_per_gpu"), dict) else {}
    infra = compute.get("infra", {}) if isinstance(compute.get("infra"), dict) else {}
    working_hours_per_day = float(infra.get("working_hours_per_day", 12))
    peak_factor = float(infra.get("peak_factor", 1.0))
    rows: list[dict[str, Any]] = []

    for cal in calendar_rows:
        year = int(cal["year"])

        activation_rate = _year_value(workplace_usage.get("activation_rate"), year)
        tokens_per_active_user_per_day = _year_value(workplace_token.get("tokens_per_active_user_per_day"), year)
        automation_rate = _year_value(cc_usage.get("automation_rate"), year)
        utilization = _year_value(infra.get("utilization"), year)

        active_users = total_employees * activation_rate
        workplace_daily_tokens = active_users * tokens_per_active_user_per_day
        cc_daily_tokens = interactions_per_day * automation_rate * cc_tokens_per_interaction

        workplace_monthly_tokens = workplace_daily_tokens * (working_days_per_year / 12.0)
        cc_monthly_tokens = cc_daily_tokens * (365.0 / 12.0)
        monthly_total_tokens = workplace_monthly_tokens + cc_monthly_tokens

        mix_for_year = model_mix.get(year, model_mix.get(str(year), {})) if isinstance(model_mix, dict) else {}
        harmonic_denom = 0.0
        for klass in ["frontier", "large", "medium", "small"]:
            share = float(mix_for_year.get(klass, 0.0)) if isinstance(mix_for_year, dict) else 0.0
            tput = float(throughput.get(klass, 0.0)) if _is_number(throughput.get(klass)) else 0.0
            if share > 0 and tput > 0:
                harmonic_denom += share / tput
        weighted_throughput = (1.0 / harmonic_denom) if harmonic_denom > 0 else 0.0

        tokens_per_second = monthly_total_tokens / (30.0 * working_hours_per_day * 3600.0) if working_hours_per_day > 0 else 0.0
        required_gpu = 0.0
        if weighted_throughput > 0 and utilization > 0:
            required_gpu = tokens_per_second / (weighted_throughput * utilization) * peak_factor

        rows.append({
            "month_seq": cal["month_seq"],
            "month_id": cal["month_id"],
            "year": year,
            "month": cal["month"],
            "workplace_monthly_tokens": round(workplace_monthly_tokens, 2),
            "contact_center_monthly_tokens": round(cc_monthly_tokens, 2),
            "monthly_total_tokens": round(monthly_total_tokens, 2),
            "weighted_throughput_tokens_per_sec_per_gpu": round(weighted_throughput, 6),
            "utilization": round(utilization, 6),
            "tokens_per_second": round(tokens_per_second, 6),
            "required_gpu": round(required_gpu, 6),
        })
    return rows


def write_monthly_demand_gpu(data: dict[str, Any]) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    calendar_rows = build_monthly_calendar(data)
    rows = build_monthly_demand_gpu(data, calendar_rows)
    with OUT_MONTHLY_DEMAND_GPU_CSV.open("w", newline="", encoding="utf-8") as fh:
        fieldnames = [
            "month_seq",
            "month_id",
            "year",
            "month",
            "workplace_monthly_tokens",
            "contact_center_monthly_tokens",
            "monthly_total_tokens",
            "weighted_throughput_tokens_per_sec_per_gpu",
            "utilization",
            "tokens_per_second",
            "required_gpu",
        ]
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    assumptions = load_assumptions(ASSUMPTIONS_PATH)
    items = validate(assumptions)
    write_reports(items)
    write_calendar_and_events(assumptions)
    write_monthly_demand_gpu(assumptions)

    errors = [x for x in items if x.level == "ERROR"]
    warnings = [x for x in items if x.level == "WARNING"]
    print(f"Validation completed. Errors: {len(errors)}, warnings: {len(warnings)}")
    print(f"TXT: {OUT_TXT}")
    print(f"CSV: {OUT_CSV}")
    print(f"Calendar CSV: {OUT_CALENDAR_CSV}")
    print(f"Events CSV: {OUT_EVENTS_CSV}")
    print(f"Monthly demand/GPU CSV: {OUT_MONTHLY_DEMAND_GPU_CSV}")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
