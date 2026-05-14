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
OUT_MONTHLY_INFRA_CSV = OUT_DIR / "gps_finmodel_monthly_infrastructure.csv"
OUT_MONTHLY_COSTS_CSV = OUT_DIR / "gps_finmodel_monthly_costs.csv"
OUT_MONTHLY_FINANCIALS_CSV = OUT_DIR / "gps_finmodel_monthly_financials.csv"
OUT_MONTHLY_FUNDED_CSV = OUT_DIR / "gps_finmodel_monthly_funded.csv"
OUT_INVESTMENT_METRICS_CSV = OUT_DIR / "gps_finmodel_investment_metrics.csv"
OUT_ANNUAL_REPORT_CSV = OUT_DIR / "gps_finmodel_annual_report.csv"
OUT_SCENARIO_SUMMARY_CSV = OUT_DIR / "gps_finmodel_scenario_summary.csv"
OUT_HTML = OUT_DIR / "gps_finmodel.html"


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



def _shift_month(year: int, month: int, delta: int) -> tuple[int, int]:
    idx = year * 12 + (month - 1) + delta
    return idx // 12, idx % 12 + 1


def _resolve_path(data: dict[str, Any], path: str) -> Any:
    node: Any = data
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def _salary_index(growth_by_year: dict[str, Any], year: int) -> float:
    idx = 1.0
    for y in range(2027, year + 1):
        idx *= 1.0 + _year_value(growth_by_year, y)
    return idx


def _fte_for_month(fte_plan: Any, year: int, month: int, data: dict[str, Any]) -> float:
    if not isinstance(fte_plan, list):
        return 0.0
    current_idx = year * 12 + (month - 1)
    latest_idx = -10**9
    latest_fte = 0.0
    for step in fte_plan:
        if not isinstance(step, dict):
            continue
        if "event_ref" in step:
            event = _resolve_path(data, str(step.get("event_ref", "")))
            if not isinstance(event, dict):
                continue
            ev_y = event.get("start_year", 1900)
            ev_m = event.get("start_month", 1)
            ev_d = event.get("event_duration", 1)
            if not (isinstance(ev_y, int) and isinstance(ev_m, int) and isinstance(ev_d, int)):
                continue
            timing = step.get("timing")
            ref_y, ref_m = (ev_y, ev_m) if timing == "event_start" else _shift_month(ev_y, ev_m, ev_d - 1)
        else:
            ref_y = step.get("start_year")
            ref_m = step.get("start_month")
            if not (isinstance(ref_y, int) and isinstance(ref_m, int)):
                continue
        ref_idx = int(ref_y) * 12 + (int(ref_m) - 1)
        if ref_idx <= current_idx and ref_idx >= latest_idx:
            latest_idx = ref_idx
            latest_fte = float(step.get("fte", 0.0)) if _is_number(step.get("fte")) else 0.0
    return latest_fte


def build_monthly_costs(data: dict[str, Any], calendar_rows: list[dict[str, Any]], infra_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    inflation = data.get("inflation_assumptions", {}) if isinstance(data.get("inflation_assumptions"), dict) else {}
    rub_inflation = inflation.get("rub_inflation", {}) if isinstance(inflation.get("rub_inflation"), dict) else {}
    taxes = data.get("finance", {}).get("taxes", {}) if isinstance(data.get("finance", {}).get("taxes"), dict) else {}
    sfr_rate = float(taxes.get("social_contribution_sfr_percent_of_gross", 0.0)) if _is_number(taxes.get("social_contribution_sfr_percent_of_gross")) else 0.0
    team = data.get("opex", {}).get("team", {}) if isinstance(data.get("opex", {}).get("team"), dict) else {}
    sga = data.get("sga", {}) if isinstance(data.get("sga"), dict) else {}
    da = data.get("depreciation_and_amortization", {}) if isinstance(data.get("depreciation_and_amortization"), dict) else {}

    team_bonus = float(team.get("payroll_assumptions", {}).get("bonus_percent_of_gross", {}).get("value", 0.0))
    team_growth = team.get("payroll_assumptions", {}).get("salary_growth", {})
    sga_bonus = float(sga.get("payroll_assumptions", {}).get("annual_bonus_percent_of_gross", {}).get("value", 0.0))
    dc_opex = data.get("opex", {}).get("datacenter", {}) if isinstance(data.get("opex", {}).get("datacenter"), dict) else {}
    dc_drv = dc_opex.get("drivers", {}) if isinstance(dc_opex.get("drivers"), dict) else {}
    elec_price = dc_drv.get("electricity_rub_per_kwh", {})
    pue = float(dc_drv.get("pue", {}).get("value", 1.0))
    gpu_kw = float(dc_drv.get("gpu_power_kw", {}).get("value", 0.0))
    op_hours = float(dc_drv.get("operating_hours_per_day", {}).get("value", 24.0))
    maint = float(dc_drv.get("maintenance_percent_of_capex", {}).get("value", 0.0))
    network = float(dc_drv.get("network_cost_per_mw_per_year", {}).get("value", 0.0))
    land = float(dc_drv.get("land_rent_per_mw_per_year", {}).get("value", 0.0))
    other = float(dc_drv.get("other_opex_percent", {}).get("value", 0.0))

    da_ppe = da.get("ppe_depreciation", {}).get("useful_life_years", {}) if isinstance(da.get("ppe_depreciation", {}).get("useful_life_years"), dict) else {}
    gpu_life = float(da_ppe.get("gpu_infra", 1))
    dc_life = float(da_ppe.get("datacenter_construction", 1))

    role_blocks = []
    for block in [team.get("roles", {}), sga.get("roles", {})]:
        if isinstance(block, dict):
            for grp in block.values():
                if isinstance(grp, dict):
                    for role in grp.values():
                        if isinstance(role, dict):
                            role_blocks.append(role)

    rows: list[dict[str, Any]] = []
    for infra in infra_rows:
        year = int(infra["year"])
        month = int(infra["month"])
        scenario = str(infra["scenario"])
        salary_idx_team = _salary_index(team_growth if isinstance(team_growth, dict) else {}, year)
        salary_idx_sga = _salary_index(rub_inflation, year)
        team_payroll = 0.0
        sga_payroll = 0.0
        for block in team.get("roles", {}).values():
            if isinstance(block, dict):
                for role in block.values():
                    if isinstance(role, dict):
                        fte = _fte_for_month(role.get("fte_plan"), year, month, data)
                        gross = float(role.get("salary_gross_monthly_rub_2026", 0.0)) * salary_idx_team * fte
                        team_payroll += gross * (1.0 + team_bonus) * (1.0 + sfr_rate)
        for block in sga.get("roles", {}).values():
            if isinstance(block, dict):
                for role in block.values():
                    if isinstance(role, dict):
                        fte = _fte_for_month(role.get("fte_plan"), year, month, data)
                        gross = float(role.get("salary_gross_monthly_rub_2026", 0.0)) * salary_idx_sga * fte
                        sga_payroll += gross * (1.0 + sga_bonus) * (1.0 + sfr_rate)

        owned_gpu = float(infra["owned_gpu"])
        elec_price_t = _year_value(elec_price, year)
        it_mw = owned_gpu * gpu_kw / 1000.0
        total_mw = it_mw * pue
        monthly_elec = total_mw * 1000.0 * op_hours * (365.0 / 12.0) * elec_price_t
        monthly_net = total_mw * network / 12.0
        monthly_land = total_mw * land / 12.0
        monthly_maint = (float(infra["gpu_infra_capex"]) + float(infra["datacenter_construction_capex"])) * maint
        datacenter_opex = (monthly_elec + monthly_net + monthly_land + monthly_maint) * (1.0 + other)

        da_monthly = (float(infra["gpu_infra_capex"]) / max(gpu_life, 1.0) + float(infra["datacenter_construction_capex"]) / max(dc_life, 1.0)) / 12.0
        rows.append({
            "scenario": scenario,
            "month_seq": infra["month_seq"],
            "month_id": infra["month_id"],
            "year": year,
            "month": month,
            "core_team_payroll": round(team_payroll, 2),
            "sga_payroll": round(sga_payroll, 2),
            "datacenter_opex": round(datacenter_opex, 2),
            "depreciation_and_amortization": round(da_monthly, 2),
            "monthly_operating_cost_total": round(team_payroll + sga_payroll + datacenter_opex + da_monthly, 2),
        })
    return rows


def build_monthly_infrastructure(data: dict[str, Any], monthly_demand_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    investment = data.get("investment_scenarios", {}) if isinstance(data.get("investment_scenarios"), dict) else {}
    capex = data.get("capex", {}) if isinstance(data.get("capex"), dict) else {}
    strategy = capex.get("strategy_scenarios", {}) if isinstance(capex.get("strategy_scenarios"), dict) else {}

    event = investment.get("construction", {}).get("event_flag", {}) if isinstance(investment.get("construction"), dict) else {}
    start_year = int(event.get("start_year", 1900)) if isinstance(event.get("start_year"), int) else 1900
    start_month = int(event.get("start_month", 1)) if isinstance(event.get("start_month"), int) else 1
    duration = int(event.get("event_duration", 1)) if isinstance(event.get("event_duration"), int) and int(event.get("event_duration", 1)) > 0 else 1
    end_year, end_month = _shift_month(start_year, start_month, duration - 1)
    own_year, own_month = _shift_month(end_year, end_month, 1)

    scenarios = strategy.get("scenarios", {}) if isinstance(strategy.get("scenarios"), dict) else {}
    scenario_names = [name for name in ["build_own_dc", "rent_gpu_only", "hybrid"] if name in scenarios] or ["build_own_dc", "rent_gpu_only", "hybrid"]

    rows: list[dict[str, Any]] = []
    prev_owned_by_scenario = {name: 0.0 for name in scenario_names}

    for demand_row in monthly_demand_rows:
        year = int(demand_row["year"])
        month = int(demand_row["month"])
        month_id = str(demand_row["month_id"])
        required_gpu = float(demand_row["required_gpu"])

        start_flag = int(year == start_year and month == start_month)
        month_idx = year * 12 + (month - 1)
        start_idx = start_year * 12 + (start_month - 1)
        end_idx = end_year * 12 + (end_month - 1)
        own_idx = own_year * 12 + (own_month - 1)
        active_flag = int(start_idx <= month_idx <= end_idx)
        completed_flag = int(month_idx >= own_idx)

        for scenario in scenario_names:
            if scenario == "rent_gpu_only":
                owned_gpu = 0.0
                rented_gpu = required_gpu
            elif scenario in {"build_own_dc", "hybrid"}:
                owned_gpu = required_gpu if completed_flag else 0.0
                rented_gpu = required_gpu if not completed_flag else 0.0
            else:
                owned_gpu = 0.0
                rented_gpu = required_gpu

            prev_owned = prev_owned_by_scenario[scenario]
            owned_gpu_increment = max(owned_gpu - prev_owned, 0.0)
            prev_owned_by_scenario[scenario] = owned_gpu

            rows.append({
                "scenario": scenario,
                "required_gpu": round(required_gpu, 6),
                "month_seq": demand_row["month_seq"],
                "month_id": month_id,
                "year": year,
                "month": month,
                "construction_start_month_key": f"{start_year:04d}-{start_month:02d}",
                "construction_end_month_key": f"{end_year:04d}-{end_month:02d}",
                "owned_gpu_available_month_key": f"{own_year:04d}-{own_month:02d}",
                "construction_start_flag": start_flag,
                "construction_active_flag": active_flag,
                "construction_completed_flag": completed_flag,
                "required_gpu": round(required_gpu, 6),
                "owned_gpu": round(owned_gpu, 6),
                "rented_gpu": round(rented_gpu, 6),
                "owned_gpu_increment": round(owned_gpu_increment, 6),
                "gpu_capex": 0.0 if scenario == "rent_gpu_only" else round(owned_gpu_increment, 6),
                "gpu_infra_capex": 0.0 if scenario == "rent_gpu_only" else round(owned_gpu_increment, 6),
                "datacenter_construction_capex": 0.0 if scenario == "rent_gpu_only" else active_flag,
            })

    return rows


def write_monthly_infrastructure(data: dict[str, Any]) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    calendar_rows = build_monthly_calendar(data)
    monthly_demand_rows = build_monthly_demand_gpu(data, calendar_rows)
    rows = build_monthly_infrastructure(data, monthly_demand_rows)

    with OUT_MONTHLY_INFRA_CSV.open("w", newline="", encoding="utf-8") as fh:
        fieldnames = [
            "scenario",
            "month_seq",
            "month_id",
            "year",
            "month",
            "construction_start_month_key",
            "construction_end_month_key",
            "owned_gpu_available_month_key",
            "construction_start_flag",
            "construction_active_flag",
            "construction_completed_flag",
            "required_gpu",
            "owned_gpu",
            "rented_gpu",
            "owned_gpu_increment",
            "gpu_capex",
            "gpu_infra_capex",
            "datacenter_construction_capex",
        ]
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_monthly_costs(data: dict[str, Any]) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    calendar_rows = build_monthly_calendar(data)
    demand_rows = build_monthly_demand_gpu(data, calendar_rows)
    infra_rows = build_monthly_infrastructure(data, demand_rows)
    rows = build_monthly_costs(data, calendar_rows, infra_rows)
    with OUT_MONTHLY_COSTS_CSV.open("w", newline="", encoding="utf-8") as fh:
        fieldnames = ["scenario", "month_seq", "month_id", "year", "month", "core_team_payroll", "sga_payroll", "datacenter_opex", "depreciation_and_amortization", "monthly_operating_cost_total"]
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _resolve_event_month(data: dict[str, Any], event_ref: str, timing: str) -> tuple[int, int] | None:
    event = _resolve_path(data, event_ref)
    if not isinstance(event, dict):
        return None
    year = event.get("start_year")
    month = event.get("start_month")
    duration = event.get("event_duration", 1)
    if not (isinstance(year, int) and isinstance(month, int) and isinstance(duration, int)):
        return None
    if timing == "after_event":
        return _shift_month(year, month, duration)
    return year, month


def build_monthly_financials(data: dict[str, Any], calendar_rows: list[dict[str, Any]], demand_rows: list[dict[str, Any]], infra_rows: list[dict[str, Any]], cost_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    demand_by_month = {str(r["month_id"]): r for r in demand_rows}
    cost_by_key = {(str(r["scenario"]), str(r["month_id"])): r for r in cost_rows}
    infra_by_scenario: dict[str, list[dict[str, Any]]] = {}
    for row in infra_rows:
        infra_by_scenario.setdefault(str(row["scenario"]), []).append(row)

    revenue = data.get("revenue", {}) if isinstance(data.get("revenue"), dict) else {}
    active_scenario = str(revenue.get("active_scenario", "base"))
    tcm = revenue.get("target_contribution_margin", {}) if isinstance(revenue.get("target_contribution_margin"), dict) else {}
    tcm_map = tcm.get(active_scenario, {}) if isinstance(tcm.get(active_scenario), dict) else {}
    profit_tax_rate = float(data.get("finance", {}).get("taxes", {}).get("profit_tax_rate", 0.0))

    product_starts: dict[str, int] = {}
    products = revenue.get("products", {}) if isinstance(revenue.get("products"), dict) else {}
    for product_name in ["workplace_ai", "contact_center_ai"]:
        cfg = products.get(product_name, {}) if isinstance(products.get(product_name), dict) else {}
        start = cfg.get("revenue_start", {}) if isinstance(cfg.get("revenue_start"), dict) else {}
        resolved = _resolve_event_month(data, str(start.get("event_ref", "")), str(start.get("timing", "at_event")))
        if resolved is not None:
            y, m = resolved
            product_starts[product_name] = y * 12 + (m - 1)

    rows: list[dict[str, Any]] = []
    for scenario, s_rows in infra_by_scenario.items():
        s_rows = sorted(s_rows, key=lambda r: int(r["month_seq"]))
        opening_cash = 0.0
        cumulative_ppe_capex = 0.0
        cumulative_intangible_capex = 0.0
        for infra in s_rows:
            year = int(infra["year"])
            month = int(infra["month"])
            month_id = str(infra["month_id"])
            idx = year * 12 + (month - 1)
            demand = demand_by_month.get(month_id, {})
            cost = cost_by_key.get((scenario, month_id), {})

            workplace_tokens = float(demand.get("workplace_monthly_tokens", 0.0))
            cc_tokens = float(demand.get("contact_center_monthly_tokens", 0.0))
            total_tokens = max(float(demand.get("monthly_total_tokens", 0.0)), 0.0)

            cogs = float(cost.get("core_team_payroll", 0.0)) + float(cost.get("datacenter_opex", 0.0))
            da = float(cost.get("depreciation_and_amortization", 0.0))
            pricing_base = cogs + da
            margin = _year_value(tcm_map, year)
            rev_mult = 1.0 / (1.0 - margin) if margin < 1.0 else 0.0

            workplace_share = (workplace_tokens / total_tokens) if total_tokens > 0 else 0.0
            cc_share = (cc_tokens / total_tokens) if total_tokens > 0 else 0.0
            workplace_active = 1 if idx >= product_starts.get("workplace_ai", 10**12) else 0
            cc_active = 1 if idx >= product_starts.get("contact_center_ai", 10**12) else 0
            workplace_revenue = pricing_base * workplace_share * rev_mult * workplace_active
            cc_revenue = pricing_base * cc_share * rev_mult * cc_active
            total_revenue = workplace_revenue + cc_revenue

            sga_payroll = float(cost.get("sga_payroll", 0.0))
            ebit = total_revenue - cogs - sga_payroll - da
            profit_tax = max(ebit, 0.0) * profit_tax_rate
            net_income = ebit - profit_tax
            operating_cf = net_income + da

            gpu_infra_capex = float(infra.get("gpu_infra_capex", 0.0))
            datacenter_capex = float(infra.get("datacenter_construction_capex", 0.0))
            office_capex = 0.0
            intangible_capex = 0.0
            investing_cf = -(gpu_infra_capex + datacenter_capex + office_capex + intangible_capex)
            pre_financing_cf = operating_cf + investing_cf
            closing_cash_before_funding = opening_cash + pre_financing_cf

            cumulative_ppe_capex += gpu_infra_capex + datacenter_capex + office_capex
            cumulative_intangible_capex += intangible_capex
            net_ppe = max(cumulative_ppe_capex - da * int(infra["month_seq"]), 0.0)
            net_intangible_assets = cumulative_intangible_capex
            total_assets_pre_funding = closing_cash_before_funding + net_ppe + net_intangible_assets
            revolver_balance = 0.0
            total_liabilities_pre_funding = revolver_balance
            total_equity_pre_funding = total_assets_pre_funding - total_liabilities_pre_funding

            rows.append({
                "scenario": scenario,
                "required_gpu": round(float(demand.get("required_gpu", 0.0)), 6),
                "month_seq": infra["month_seq"],
                "month_id": month_id,
                "year": year,
                "month": month,
                "workplace_revenue": round(workplace_revenue, 2),
                "contact_center_revenue": round(cc_revenue, 2),
                "total_revenue": round(total_revenue, 2),
                "cogs": round(cogs, 2),
                "sga": round(sga_payroll, 2),
                "depreciation_and_amortization": round(da, 2),
                "ebit": round(ebit, 2),
                "profit_tax": round(profit_tax, 2),
                "net_income": round(net_income, 2),
                "operating_cash_flow": round(operating_cf, 2),
                "investing_cash_flow": round(investing_cf, 2),
                "pre_financing_cash_flow": round(pre_financing_cf, 2),
                "opening_cash_before_funding": round(opening_cash, 2),
                "closing_cash_before_funding": round(closing_cash_before_funding, 2),
                "net_ppe": round(net_ppe, 2),
                "net_intangible_assets": round(net_intangible_assets, 2),
                "total_assets_pre_funding": round(total_assets_pre_funding, 2),
                "total_liabilities_pre_funding": round(total_liabilities_pre_funding, 2),
                "total_equity_pre_funding": round(total_equity_pre_funding, 2),
            })
            opening_cash = closing_cash_before_funding
    return rows


def write_monthly_financials(data: dict[str, Any]) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    calendar_rows = build_monthly_calendar(data)
    demand_rows = build_monthly_demand_gpu(data, calendar_rows)
    infra_rows = build_monthly_infrastructure(data, demand_rows)
    cost_rows = build_monthly_costs(data, calendar_rows, infra_rows)
    rows = build_monthly_financials(data, calendar_rows, demand_rows, infra_rows, cost_rows)
    with OUT_MONTHLY_FINANCIALS_CSV.open("w", newline="", encoding="utf-8") as fh:
        fieldnames = ["scenario", "required_gpu", "month_seq", "month_id", "year", "month", "workplace_revenue", "contact_center_revenue", "total_revenue", "cogs", "sga", "depreciation_and_amortization", "ebit", "profit_tax", "net_income", "operating_cash_flow", "investing_cash_flow", "pre_financing_cash_flow", "opening_cash_before_funding", "closing_cash_before_funding", "net_ppe", "net_intangible_assets", "total_assets_pre_funding", "total_liabilities_pre_funding", "total_equity_pre_funding"]
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def normalize_funding_scenarios(data: dict[str, Any], items: list[ValidationItem]) -> dict[str, tuple[float, float]]:
    funding = data.get("funding", {}) if isinstance(data.get("funding"), dict) else {}
    scenarios = funding.get("scenarios", {}) if isinstance(funding.get("scenarios"), dict) else {}
    result: dict[str, tuple[float, float]] = {}
    for name in ["equity_only", "revolver_only", "mix"]:
        sc = scenarios.get(name, {}) if isinstance(scenarios.get(name), dict) else {}
        e = sc.get("equity_share", {}) if isinstance(sc.get("equity_share"), dict) else {}
        r = sc.get("revolver_share", {}) if isinstance(sc.get("revolver_share"), dict) else {}
        es = float(e.get("value", 0.0)) if _is_number(e.get("value")) else 0.0
        rs = float(r.get("value", 0.0)) if _is_number(r.get("value")) else 0.0
        total = es + rs
        if total > 1.000001 and total <= 100.000001:
            es /= 100.0
            rs /= 100.0
            total = es + rs
        if total <= 0:
            items.append(ValidationItem("ERROR", f"funding.scenarios.{name}", "Funding shares are missing or zero."))
            continue
        if abs(total - 1.0) > 1e-6:
            items.append(ValidationItem("WARNING", f"funding.scenarios.{name}", f"Shares sum to {total:.6f}; normalized to 1.0."))
            es /= total
            rs /= total
        result[name] = (es, rs)
    if not result:
        items.append(ValidationItem("ERROR", "funding.scenarios", "No valid funding scenarios found."))
    return result


def minimum_cash_balance_for_row(data: dict[str, Any], fin_row: dict[str, Any], cost_row: dict[str, Any], items: list[ValidationItem]) -> float:
    mcb = data.get("funding", {}).get("minimum_cash_balance", {}) if isinstance(data.get("funding", {}).get("minimum_cash_balance"), dict) else {}
    months = mcb.get("months_of_fixed_costs", {}) if isinstance(mcb.get("months_of_fixed_costs"), dict) else {}
    m = float(months.get("value", 1.0)) if _is_number(months.get("value")) else 1.0
    fixed = float(cost_row.get("core_team_payroll", 0.0)) + float(cost_row.get("sga_payroll", 0.0)) + max(float(cost_row.get("datacenter_opex", 0.0)), 0.0)
    if not _is_number(m):
        items.append(ValidationItem("WARNING", "funding.minimum_cash_balance", "Using fallback convention for minimum cash balance."))
        m = 1.0
    return max(fixed * m, 0.0)


def calculate_monthly_funding(data, financial_rows, cost_rows, funding_shares, items):
    cost_by_key = {(str(r["scenario"]), str(r["month_id"])): r for r in cost_rows}
    annual_rate = data.get("finance", {}).get("funding", {}).get("revolver_interest_rate")
    if not _is_number(annual_rate):
        items.append(ValidationItem("ERROR", "finance.funding.revolver_interest_rate", "Missing or non-numeric."))
        annual_rate = 0.0
    annual_rate = float(annual_rate)
    monthly_rate = (1 + annual_rate) ** (1 / 12) - 1
    if monthly_rate < 0:
        items.append(ValidationItem("WARNING", "finance.funding.revolver_interest_rate", "Monthly interest rate is negative."))
    by_scenario = {}
    for r in financial_rows:
        by_scenario.setdefault(str(r["scenario"]), []).append(r)
    funded=[]
    for infra,rows in by_scenario.items():
        rows=sorted(rows,key=lambda x:int(x["month_seq"]))
        for f_name,(eq_share,rev_share) in funding_shares.items():
            cash=0.0; rev_bal=0.0; paid_in=0.0; retained=0.0
            for r in rows:
                cost=cost_by_key.get((infra,str(r["month_id"])),{})
                min_cash=minimum_cash_balance_for_row(data,r,cost,items)
                base_cf=float(r["pre_financing_cash_flow"]); ebit=float(r["ebit"])
                pre_cash=cash+base_cf
                funding_need=max(min_cash-pre_cash,0.0)
                eq_inj=funding_need*eq_share
                rev_draw=funding_need*rev_share
                cash_after_draw=pre_cash+eq_inj+rev_draw
                excess=max(cash_after_draw-min_cash,0.0)
                rev_repay=min(excess,rev_bal+rev_draw)
                close_rev=rev_bal+rev_draw-rev_repay
                avg_rev=(rev_bal+close_rev)/2.0
                interest=avg_rev*monthly_rate
                ebt_ai=ebit-interest
                tax=max(ebt_ai,0.0)*float(data.get("finance",{}).get("taxes",{}).get("profit_tax_rate",0.0))
                ni=ebt_ai-tax
                ocf_ai=ni+float(r["depreciation_and_amortization"])
                fcf_af=ocf_ai+float(r["investing_cash_flow"])
                close_cash=cash_after_draw-rev_repay-interest
                paid_in+=eq_inj; retained+=ni
                total_assets=close_cash+float(r["net_ppe"])+float(r["net_intangible_assets"])
                total_liab=close_rev; total_eq=paid_in+retained
                balance_check=total_assets-total_liab-total_eq
                funded.append({**r,"infrastructure_scenario":infra,"funding_scenario":f_name,"equity_share":round(eq_share,6),"revolver_share":round(rev_share,6),"minimum_cash_balance":round(min_cash,2),"funding_need":round(funding_need,2),"equity_injection":round(eq_inj,2),"revolver_drawdown":round(rev_draw,2),"revolver_repayment":round(rev_repay,2),"opening_revolver_balance":round(rev_bal,2),"closing_revolver_balance":round(close_rev,2),"average_revolver_balance":round(avg_rev,2),"monthly_revolver_interest_rate":round(monthly_rate,8),"interest_expense":round(interest,2),"ebt_after_interest":round(ebt_ai,2),"profit_tax_after_interest":round(tax,2),"net_income_after_interest":round(ni,2),"operating_cash_flow_after_interest":round(ocf_ai,2),"free_cash_flow_after_financing_costs":round(fcf_af,2),"closing_cash_after_funding":round(close_cash,2),"cash":round(close_cash,2),"revolver_balance":round(close_rev,2),"paid_in_capital":round(paid_in,2),"retained_earnings":round(retained,2),"total_assets":round(total_assets,2),"total_liabilities":round(total_liab,2),"total_equity":round(total_eq,2),"balance_check":round(balance_check,2)})
                cash=close_cash; rev_bal=close_rev
    return funded


def monthly_irr(cfs: list[float]) -> float | None:
    if not any(x < 0 for x in cfs) or not any(x > 0 for x in cfs):
        return None
    rate = 0.01
    for _ in range(100):
        npv = 0.0; d=0.0
        for t,cf in enumerate(cfs):
            den=(1+rate)**t
            npv += cf/den
            if t>0: d += -t*cf/((1+rate)**(t+1))
        if abs(npv) < 1e-7: return rate
        if d == 0: break
        rate -= npv/d
        if rate <= -0.9999 or rate > 10: break
    return None


def calculate_investment_metrics(data, funded_rows, items):
    annual_discount=float(data.get("finance",{}).get("valuation",{}).get("discount_rate",0.0))
    mdr=(1+annual_discount)**(1/12)-1
    grouped={}
    for r in funded_rows: grouped.setdefault((r["infrastructure_scenario"],r["funding_scenario"]),[]).append(r)
    metrics=[]
    for (infra,fund),rows in grouped.items():
        rows=sorted(rows,key=lambda x:int(x["month_seq"]))
        cfs=[float(r["free_cash_flow_after_financing_costs"]) for r in rows]
        npv=0.0; cum=0.0; cumd=0.0; sp='Not reached'; dp='Not reached'
        for i,cf in enumerate(cfs, start=1):
            disc=1/((1+mdr)**i)
            dcf=cf*disc; npv+=dcf; cum+=cf; cumd+=dcf
            if sp=='Not reached' and cum>=0: sp=rows[i-1]["month_id"]
            if dp=='Not reached' and cumd>=0: dp=rows[i-1]["month_id"]
        mirr=monthly_irr(cfs); airr=((1+mirr)**12-1) if mirr is not None else None
        if mirr is None: items.append(ValidationItem("WARNING", f"investment_metrics.{infra}.{fund}", "IRR could not be calculated."))
        req_inv=abs(sum(float(r["investing_cash_flow"]) for r in rows if float(r["investing_cash_flow"])<0))
        peak=max(float(r["required_gpu"]) for r in rows) if rows else 0.0
        last=rows[-1]
        metrics.append({"infrastructure_scenario":infra,"funding_scenario":fund,"npv":round(npv,2),"irr_annualized":round(airr,6) if airr is not None else None,"simple_payback_month_key":sp,"discounted_payback_month_key":dp,"required_investments":round(req_inv,2),"peak_required_gpu":round(peak,6),"ending_revolver_balance":last["closing_revolver_balance"],"ending_cash":last["closing_cash_after_funding"],"ending_balance_check":last["balance_check"]})
    return metrics


def build_annual_report(funded_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    flow_fields = [
        "workplace_revenue", "contact_center_revenue", "total_revenue", "cogs", "sga",
        "depreciation_and_amortization", "ebit", "profit_tax", "net_income", "operating_cash_flow",
        "investing_cash_flow", "pre_financing_cash_flow", "funding_need", "equity_injection",
        "revolver_drawdown", "revolver_repayment", "interest_expense", "ebt_after_interest",
        "profit_tax_after_interest", "net_income_after_interest", "operating_cash_flow_after_interest",
        "free_cash_flow_after_financing_costs",
    ]
    stock_fields = [
        "required_gpu", "opening_cash_before_funding", "closing_cash_before_funding", "closing_cash_after_funding",
        "cash", "net_ppe", "net_intangible_assets", "total_assets", "total_liabilities", "total_equity",
        "revolver_balance", "closing_revolver_balance", "paid_in_capital", "retained_earnings", "balance_check",
    ]

    grouped: dict[tuple[str, str, int], list[dict[str, Any]]] = {}
    for row in funded_rows:
        key = (str(row["infrastructure_scenario"]), str(row["funding_scenario"]), int(row["year"]))
        grouped.setdefault(key, []).append(row)

    annual_rows: list[dict[str, Any]] = []
    for (infra, fund, year), rows in sorted(grouped.items(), key=lambda x: (x[0][0], x[0][1], x[0][2])):
        s_rows = sorted(rows, key=lambda r: int(r["month_seq"]))
        out: dict[str, Any] = {
            "infrastructure_scenario": infra,
            "funding_scenario": fund,
            "year": year,
            "months_in_year": len(s_rows),
            "first_month_id": s_rows[0]["month_id"],
            "last_month_id": s_rows[-1]["month_id"],
        }
        for field in flow_fields:
            out[field] = round(sum(float(r.get(field, 0.0)) for r in s_rows), 2)
        for field in stock_fields:
            out[field] = round(float(s_rows[-1].get(field, 0.0)), 2)
        annual_rows.append(out)
    return annual_rows


def build_scenario_summary(annual_rows: list[dict[str, Any]], metrics_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    annual_by_key = {(str(r["infrastructure_scenario"]), str(r["funding_scenario"])): r for r in annual_rows}
    summary: list[dict[str, Any]] = []
    for m in sorted(metrics_rows, key=lambda x: (str(x["infrastructure_scenario"]), str(x["funding_scenario"]))):
        key = (str(m["infrastructure_scenario"]), str(m["funding_scenario"]))
        relevant = [r for (i, f), r in annual_by_key.items() if i == key[0] and f == key[1]]
        latest = sorted(relevant, key=lambda r: int(r["year"]))[-1] if relevant else {}
        summary.append({
            "infrastructure_scenario": key[0],
            "funding_scenario": key[1],
            "npv": m.get("npv"),
            "irr_annualized": m.get("irr_annualized"),
            "simple_payback_month_key": m.get("simple_payback_month_key"),
            "discounted_payback_month_key": m.get("discounted_payback_month_key"),
            "required_investments": m.get("required_investments"),
            "peak_required_gpu": m.get("peak_required_gpu"),
            "latest_year": latest.get("year"),
            "latest_year_total_revenue": latest.get("total_revenue"),
            "latest_year_net_income_after_interest": latest.get("net_income_after_interest"),
            "latest_year_closing_cash": latest.get("closing_cash_after_funding"),
            "latest_year_revolver_balance": latest.get("closing_revolver_balance"),
        })
    return summary


def _format_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:,.2f}"
    return str(value)


def _table_html(title: str, rows: list[dict[str, Any]], max_rows: int | None = None) -> str:
    if not rows:
        return f"<h3>{title}</h3><p>No data.</p>"
    body_rows = rows[:max_rows] if max_rows is not None else rows
    headers = list(rows[0].keys())
    th = "".join(f"<th>{h}</th>" for h in headers)
    tr_parts = []
    for row in body_rows:
        tds = "".join(f"<td>{_format_value(row.get(h))}</td>" for h in headers)
        tr_parts.append(f"<tr>{tds}</tr>")
    tbody = "".join(tr_parts)
    return f"<h3>{title}</h3><table><thead><tr>{th}</tr></thead><tbody>{tbody}</tbody></table>"


def build_key_assumptions_planner(data: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    planner: dict[str, list[dict[str, Any]]] = {}
    model = data.get("model", {}) if isinstance(data.get("model"), dict) else {}
    finance = data.get("finance", {}) if isinstance(data.get("finance"), dict) else {}
    usage = data.get("usage_assumptions", {}) if isinstance(data.get("usage_assumptions"), dict) else {}
    compute = data.get("compute_model", {}) if isinstance(data.get("compute_model"), dict) else {}
    infra = compute.get("infra", {}) if isinstance(compute.get("infra"), dict) else {}
    revenue = data.get("revenue", {}) if isinstance(data.get("revenue"), dict) else {}

    def add_row(section: str, row: dict[str, Any]) -> None:
        planner.setdefault(section, []).append(row)

    add_row("Model Timeline", {"label": "forecast_start.year", "path": "model.forecast_start.year", "value": model.get("forecast_start", {}).get("year", ""), "editable": True})
    add_row("Model Timeline", {"label": "forecast_start.month", "path": "model.forecast_start.month", "value": model.get("forecast_start", {}).get("month", ""), "editable": True})
    add_row("Model Timeline", {"label": "forecast_end.year", "path": "model.forecast_end.year", "value": model.get("forecast_end", {}).get("year", ""), "editable": True})
    add_row("Model Timeline", {"label": "forecast_end.month", "path": "model.forecast_end.month", "value": model.get("forecast_end", {}).get("month", ""), "editable": True})

    add_row("Finance", {"label": "discount_rate", "path": "finance.valuation.discount_rate", "value": finance.get("valuation", {}).get("discount_rate", "") if isinstance(finance.get("valuation"), dict) else "", "editable": True})
    add_row("Finance", {"label": "profit_tax_rate", "path": "finance.taxes.profit_tax_rate", "value": finance.get("taxes", {}).get("profit_tax_rate", "") if isinstance(finance.get("taxes"), dict) else "", "editable": True})
    add_row("Finance", {"label": "social_contribution_sfr_percent_of_gross", "path": "finance.taxes.social_contribution_sfr_percent_of_gross", "value": finance.get("taxes", {}).get("social_contribution_sfr_percent_of_gross", "") if isinstance(finance.get("taxes"), dict) else "", "editable": True})
    add_row("Finance", {"label": "revolver_interest_rate", "path": "finance.funding.revolver_interest_rate", "value": finance.get("funding", {}).get("revolver_interest_rate", "") if isinstance(finance.get("funding"), dict) else "", "editable": True})

    for product_name, product_data in usage.items():
        if isinstance(product_data, dict):
            add_row("Usage", {"label": f"{product_name}.usage_metric", "path": f"usage_assumptions.{product_name}.usage_metric", "value": product_data.get("usage_metric", ""), "editable": True})
            if "activation_rate" in product_data:
                add_row("Usage", {"label": f"{product_name}.activation_rate", "path": f"usage_assumptions.{product_name}.activation_rate", "value": product_data.get("activation_rate", ""), "editable": True})
            if "automation_rate" in product_data:
                add_row("Usage", {"label": f"{product_name}.automation_rate", "path": f"usage_assumptions.{product_name}.automation_rate", "value": product_data.get("automation_rate", ""), "editable": True})

    add_row("Compute", {"label": "throughput_per_gpu", "path": "compute_model.throughput_per_gpu", "value": compute.get("throughput_per_gpu", ""), "editable": False})
    add_row("Compute", {"label": "utilization", "path": "compute_model.infra.utilization", "value": infra.get("utilization", ""), "editable": True})
    add_row("Compute", {"label": "peak_factor", "path": "compute_model.infra.peak_factor", "value": infra.get("peak_factor", ""), "editable": True})

    add_row("Infrastructure", {"label": "owned_gpu_available_policy", "path": "compute_model.infra.owned_gpu_available_policy", "value": infra.get("owned_gpu_available_policy", ""), "editable": True})
    add_row("Infrastructure", {"label": "gpu_power_kw", "path": "compute_model.infra.opex_own_datacenter.gpu_power_kw.value", "value": infra.get("opex_own_datacenter", {}).get("gpu_power_kw", {}).get("value", "") if isinstance(infra.get("opex_own_datacenter"), dict) else "", "editable": True})
    add_row("Infrastructure", {"label": "pue", "path": "compute_model.infra.opex_own_datacenter.pue.value", "value": infra.get("opex_own_datacenter", {}).get("pue", {}).get("value", "") if isinstance(infra.get("opex_own_datacenter"), dict) else "", "editable": True})

    add_row("Revenue", {"label": "active_scenario", "path": "revenue.active_scenario", "value": revenue.get("active_scenario", ""), "editable": True})
    add_row("Revenue", {"label": "pricing_base_year", "path": "revenue.base_year", "value": revenue.get("base_year", ""), "editable": True})
    return planner


def write_static_html_report(
    funded_rows: list[dict[str, Any]],
    annual_rows: list[dict[str, Any]],
    summary_rows: list[dict[str, Any]],
    metrics_rows: list[dict[str, Any]],
    items: list[ValidationItem],
    assumptions_data: dict[str, Any],
) -> None:
    import json

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    infra_names = sorted({str(r["infrastructure_scenario"]) for r in funded_rows})
    funding_names = sorted({str(r["funding_scenario"]) for r in funded_rows})
    base_infra = "base" if "base" in infra_names else (infra_names[0] if infra_names else "")
    base_funding = "base" if "base" in funding_names else (funding_names[0] if funding_names else "")

    diagnostics_rows = [{
        "metric": "validation_errors",
        "value": sum(1 for x in items if x.level == "ERROR"),
    }, {
        "metric": "validation_warnings",
        "value": sum(1 for x in items if x.level == "WARNING"),
    }, {
        "metric": "base_infrastructure_scenario",
        "value": base_infra,
    }, {
        "metric": "base_funding_scenario",
        "value": base_funding,
    }]
    planner_sections = build_key_assumptions_planner(assumptions_data)

    calendar_rows = build_monthly_calendar(assumptions_data)
    demand_rows = build_monthly_demand_gpu(assumptions_data, calendar_rows)

    html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>GPS Finmodel Report</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 24px; color: #111; }}
    h1 {{ margin-bottom: 0.2rem; }}
    h2 {{ margin-top: 2rem; border-bottom: 1px solid #ddd; padding-bottom: 0.3rem; }}
    table {{ border-collapse: collapse; width: 100%; margin: 12px 0 24px; font-size: 12px; }}
    th, td {{ border: 1px solid #ddd; padding: 6px; text-align: left; }}
    th {{ background: #f5f5f5; }}
    .controls {{ display: flex; gap: 16px; margin: 12px 0 18px; flex-wrap: wrap; }}
    label {{ font-weight: bold; font-size: 13px; }}
    select {{ margin-left: 8px; padding: 4px; }}
    .card {{ border: 1px solid #ddd; padding: 10px; margin: 12px 0; border-radius: 6px; }}
    .note {{ font-size: 12px; color: #555; margin-bottom: 8px; }}
    .override-changed td {{ background: #fff6bf; }}
    button {{ padding: 4px 8px; }}
  </style>
</head>
<body>
  <h1>GPS Finmodel Report</h1>
  <p>Generated from precomputed CSV outputs. Select scenarios to switch displayed tables; no browser-side financial recalculation is performed.</p>

  <div class="controls">
    <label>Infrastructure scenario
      <select id="infra-select"></select>
    </label>
    <label>Funding mode
      <select id="funding-mode-select"></select>
    </label>
    <label>Funding scenario
      <select id="funding-select"></select>
    </label>
    <label id="equity-share-label" style="display:none;">Custom equity share (%)
      <input id="equity-share-input" type="range" min="0" max="100" step="1" value="50" />
      <span id="equity-share-value">50</span>
    </label>
  </div>

  <h2>Executive Summary</h2>
  <div id="executive-summary"></div>

  <h2>Scenario Summary</h2>
  {_table_html("Scenario summary", summary_rows)}

  <h2>Annual Report</h2>
  <div id="annual-report"></div>

  <h2>Monthly Detail</h2>
  <div id="monthly-detail"></div>

  <h2>Diagnostics</h2>
  {_table_html("Validation and report diagnostics", diagnostics_rows)}
  {_table_html("Investment metrics", metrics_rows)}

  <h2>Key Assumptions Planner</h2>
  <div class="card">
    <div class="note">Edit mode stores browser-only assumption overrides JSON (no YAML export, no Workbench, no server calls).</div>
    <div class="controls">
      <button id="planner-mode-toggle" type="button">Switch to Edit mode</button>
      <button id="planner-reset" type="button">Reset overrides</button>
      <button id="planner-export" type="button">Export overrides JSON</button>
      <button id="planner-import" type="button">Import overrides JSON</button>
      <span id="planner-override-count">Overrides: 0</span>
      <input id="planner-import-file" type="file" accept="application/json" style="display:none;" />
    </div>
    <div id="planner-demand-preview"></div>
    <div id="planner-operating-preview"></div>
    <div id="key-assumptions-planner"></div>
  </div>

  <script>
    const reportData = {json.dumps({'funded_rows': funded_rows, 'annual_rows': annual_rows})};
    const demandBaseRows = {json.dumps(demand_rows)};
    const plannerSections = {json.dumps(planner_sections)};
    const baseAssumptions = {json.dumps(assumptions_data)};
    const infraNames = {json.dumps(infra_names)};
    const fundingNames = {json.dumps(funding_names)};
    const baseInfra = {json.dumps(base_infra)};
    const baseFunding = {json.dumps(base_funding)};

    function formatValue(value) {{
      if (value === null || value === undefined) return '';
      if (typeof value === 'number') return value.toLocaleString(undefined, {{minimumFractionDigits: 0, maximumFractionDigits: 2}});
      return String(value);
    }}

    function tableHtml(title, rows) {{
      if (!rows.length) return `<h3>${{title}}</h3><p>No data.</p>`;
      const headers = Object.keys(rows[0]);
      const th = headers.map((h) => `<th>${{h}}</th>`).join('');
      const body = rows.map((row) => `<tr>${{headers.map((h) => `<td>${{formatValue(row[h])}}</td>`).join('')}}</tr>`).join('');
      return `<h3>${{title}}</h3><table><thead><tr>${{th}}</tr></thead><tbody>${{body}}</tbody></table>`;
    }}

    function filterRows(rows, infra, funding) {{
      return rows.filter((r) => r.infrastructure_scenario === infra && r.funding_scenario === funding);
    }}

    function render(infra, funding) {{
      const annual = filterRows(reportData.annual_rows, infra, funding).sort((a,b)=>a.year-b.year);
      const monthly = filterRows(reportData.funded_rows, infra, funding).sort((a,b)=>a.month_seq-b.month_seq);
      const latest = annual.length ? annual[annual.length - 1] : {{}};
      const executive = [{{
        infrastructure_scenario: infra,
        funding_scenario: funding,
        latest_year: latest.year,
        months_in_latest_year: latest.months_in_year,
        total_revenue: latest.total_revenue,
        net_income_after_interest: latest.net_income_after_interest,
        closing_cash_after_funding: latest.closing_cash_after_funding,
        closing_revolver_balance: latest.closing_revolver_balance,
      }}];
      document.getElementById('executive-summary').innerHTML = tableHtml('Selected scenario snapshot', executive);
      document.getElementById('annual-report').innerHTML = tableHtml('Annual aggregation by scenario', annual);
      document.getElementById('monthly-detail').innerHTML = tableHtml('Monthly funded detail', monthly);
    }}

    function initSelect(id, options, selected) {{
      const el = document.getElementById(id);
      options.forEach((name) => {{
        const opt = document.createElement('option');
        opt.value = name; opt.textContent = name;
        if (name === selected) opt.selected = true;
        el.appendChild(opt);
      }});
      return el;
    }}

    function blendRows(eqRows, revRows, equityShare) {{
      const revByMonth = new Map(revRows.map((r) => [String(r.month_id), r]));
      return eqRows.map((eq) => {{
        const rev = revByMonth.get(String(eq.month_id)) || {{}};
        const out = {{}};
        Object.keys(eq).forEach((k) => {{
          const ev = eq[k];
          const rv = rev[k];
          if (typeof ev === 'number' && typeof rv === 'number') {{
            out[k] = ev * equityShare + rv * (1 - equityShare);
          }} else {{
            out[k] = ev;
          }}
        }});
        out.funding_scenario = 'custom_mix';
        out.equity_share = equityShare;
        out.revolver_share = 1 - equityShare;
        return out;
      }});
    }}

    function buildCustomView(infra, equityShare) {{
      const eqAnnual = filterRows(reportData.annual_rows, infra, 'equity_only').sort((a,b)=>a.year-b.year);
      const revAnnual = filterRows(reportData.annual_rows, infra, 'revolver_only').sort((a,b)=>a.year-b.year);
      const eqMonthly = filterRows(reportData.funded_rows, infra, 'equity_only').sort((a,b)=>a.month_seq-b.month_seq);
      const revMonthly = filterRows(reportData.funded_rows, infra, 'revolver_only').sort((a,b)=>a.month_seq-b.month_seq);
      return {{
        annual: blendRows(eqAnnual, revAnnual, equityShare),
        monthly: blendRows(eqMonthly, revMonthly, equityShare),
      }};
    }}

    const infraSelect = initSelect('infra-select', infraNames, baseInfra);
    const fundingModeSelect = initSelect('funding-mode-select', ['precomputed', 'custom_mix'], 'precomputed');
    const fundingSelect = initSelect('funding-select', fundingNames, baseFunding);
    const equityShareInput = document.getElementById('equity-share-input');
    const equityShareLabel = document.getElementById('equity-share-label');
    const equityShareValue = document.getElementById('equity-share-value');

    function onChange() {{
      const mode = fundingModeSelect.value;
      if (mode === 'custom_mix') {{
        equityShareLabel.style.display = 'inline-block';
        fundingSelect.disabled = true;
        const eq = Number(equityShareInput.value) / 100;
        equityShareValue.textContent = String(Math.round(eq * 100));
        const custom = buildCustomView(infraSelect.value, eq);
        const latest = custom.annual.length ? custom.annual[custom.annual.length - 1] : {{}};
        const executive = [{{
          infrastructure_scenario: infraSelect.value,
          funding_scenario: 'custom_mix',
          custom_equity_share_percent: Math.round(eq * 100),
          custom_revolver_share_percent: Math.round((1 - eq) * 100),
          latest_year: latest.year,
          months_in_latest_year: latest.months_in_year,
          total_revenue: latest.total_revenue,
          net_income_after_interest: latest.net_income_after_interest,
          closing_cash_after_funding: latest.closing_cash_after_funding,
          closing_revolver_balance: latest.closing_revolver_balance,
        }}];
        document.getElementById('executive-summary').innerHTML = tableHtml('Selected scenario snapshot', executive);
        document.getElementById('annual-report').innerHTML = tableHtml('Annual aggregation by scenario', custom.annual);
        document.getElementById('monthly-detail').innerHTML = tableHtml('Monthly funded detail', custom.monthly);
      }} else {{
        equityShareLabel.style.display = 'none';
        fundingSelect.disabled = false;
        render(infraSelect.value, fundingSelect.value);
      }}
    }}
    infraSelect.addEventListener('change', onChange);
    fundingModeSelect.addEventListener('change', onChange);
    fundingSelect.addEventListener('change', onChange);
    equityShareInput.addEventListener('input', onChange);
    onChange();

    let plannerEditMode = false;
    let plannerOverrides = {{}};

    function normalizeOverrideValue(value) {{
      if (typeof value === 'string' && value.trim() !== '' && !Number.isNaN(Number(value))) return Number(value);
      return value;
    }}

    function updateOverrideCount() {{
      document.getElementById('planner-override-count').textContent = `Overrides: ${{Object.keys(plannerOverrides).length}}`;
    }}

    function yearValue(mapping, year) {{
      if (!mapping || typeof mapping !== 'object') return 0;
      const value = mapping[year] ?? mapping[String(year)];
      const parsed = Number(value);
      return Number.isFinite(parsed) ? parsed : 0;
    }}

    function getOverridden(path, base) {{
      if (!Object.prototype.hasOwnProperty.call(plannerOverrides, path)) return base;
      return plannerOverrides[path];
    }}

    function recomputeDemandPreview() {{
      const usage = baseAssumptions.usage_assumptions || {{}};
      const tokenModel = baseAssumptions.token_load_model || {{}};
      const compute = baseAssumptions.compute_model || {{}};
      const infra = compute.infra || {{}};
      const throughput = compute.throughput_per_gpu || {{}};
      const modelMix = compute.model_mix || {{}};

      const wpUsage = usage['Workplace.ai'] || {{}};
      const wpToken = tokenModel['Workplace.ai'] || {{}};
      const ccUsage = usage['Contact_Center.ai'] || {{}};
      const ccToken = tokenModel['Contact_Center.ai'] || {{}};
      const timeAssumptions = tokenModel.time_assumptions || {{}};

      const totalEmployees = Number(wpUsage.total_employees || 0);
      const interactionsPerDay = Number(ccUsage.interactions_per_day || 0);
      const ccTokensPerInteraction = Number(ccToken.tokens_per_interaction || 0);
      const workingDaysPerYear = Number(timeAssumptions.working_days_per_year || 247);
      const workingHoursPerDay = Number(infra.working_hours_per_day || 12);
      const peakFactor = Number(getOverridden('compute_model.infra.peak_factor', infra.peak_factor || 1.0));

      const yearly = new Map();
      demandBaseRows.forEach((row) => {{
        const year = Number(row.year);
        const activationRate = yearValue(getOverridden('usage_assumptions.Workplace.ai.activation_rate', wpUsage.activation_rate), year);
        const tokensPerUserDay = yearValue(wpToken.tokens_per_active_user_per_day, year);
        const automationRate = yearValue(ccUsage.automation_rate, year);
        const utilization = yearValue(getOverridden('compute_model.infra.utilization', infra.utilization), year);
        const mixYear = modelMix[year] || modelMix[String(year)] || {{}};
        let harmonic = 0;
        ['frontier', 'large', 'medium', 'small'].forEach((klass) => {{
          const share = Number(mixYear[klass] || 0);
          const tput = Number(throughput[klass] || 0);
          if (share > 0 && tput > 0) harmonic += share / tput;
        }});
        const weightedThroughput = harmonic > 0 ? (1 / harmonic) : 0;
        const activeUsers = totalEmployees * activationRate;
        const workplaceTokens = activeUsers * tokensPerUserDay * (workingDaysPerYear / 12);
        const ccTokens = interactionsPerDay * automationRate * ccTokensPerInteraction * (365 / 12);
        const monthlyTotalTokens = workplaceTokens + ccTokens;
        const tps = workingHoursPerDay > 0 ? monthlyTotalTokens / (30 * workingHoursPerDay * 3600) : 0;
        const requiredGpu = (weightedThroughput > 0 && utilization > 0) ? (tps / (weightedThroughput * utilization) * peakFactor) : 0;
        if (!yearly.has(year)) yearly.set(year, {{tokens: 0, required_gpu_max: 0, weighted_throughput: weightedThroughput}});
        const agg = yearly.get(year);
        agg.tokens += monthlyTotalTokens;
        agg.required_gpu_max = Math.max(agg.required_gpu_max, requiredGpu);
        agg.weighted_throughput = weightedThroughput;
      }});
      return Array.from(yearly.entries()).sort((a, b) => a[0] - b[0]).map(([year, data]) => ({{
        year,
        preview_total_tokens: Math.round(data.tokens * 100) / 100,
        preview_weighted_throughput_tokens_per_sec_per_gpu: Math.round(data.weighted_throughput * 1e6) / 1e6,
        preview_required_gpu_peak: Math.round(data.required_gpu_max * 1e6) / 1e6,
      }}));
    }}

    function renderDemandPreview() {{
      const rows = recomputeDemandPreview();
      document.getElementById('planner-demand-preview').innerHTML = tableHtml('Demand/GPU preview from current overrides (browser-side only)', rows);
    }}

    function monthlyAnnualizedValue(base, year, path) {{
      const mapping = getOverridden(path, base);
      return yearValue(mapping, year);
    }}

    function recomputeOperatingPreview() {{
      const rows = filterRows(reportData.funded_rows, infraSelect.value, fundingSelect.value).sort((a,b)=>a.month_seq-b.month_seq);
      if (!rows.length) return [];
      const usage = baseAssumptions.usage_assumptions || {{}};
      const revenue = baseAssumptions.revenue || {{}};
      const baseMargin = Number((revenue.target_margins || {{}}).contribution_margin_pct || 0);
      const targetMargin = Number(getOverridden('revenue.target_margins.contribution_margin_pct', baseMargin));
      const marginRatio = baseMargin > 0 ? targetMargin / baseMargin : 1.0;
      const baseGpuUnitCost = Number((((baseAssumptions.compute_model || {{}}).infra || {{}}).capex_own_datacenter || {{}}).gpu_unit_cost || 0);
      const targetGpuUnitCost = Number(getOverridden('compute_model.infra.capex_own_datacenter.gpu_unit_cost', baseGpuUnitCost));
      const gpuUnitCostRatio = baseGpuUnitCost > 0 ? targetGpuUnitCost / baseGpuUnitCost : 1.0;
      const baseConstructionMonth = Number((((baseAssumptions.compute_model || {{}}).infra || {{}}).construction || {{}}).start_month_seq || 1);
      const targetConstructionMonth = Number(getOverridden('compute_model.infra.construction.start_month_seq', baseConstructionMonth));
      const constructionShift = targetConstructionMonth - baseConstructionMonth;
      const baseActivationMap = (usage['Workplace.ai'] || {{}}).activation_rate || {{}};
      const targetActivationMap = getOverridden('usage_assumptions.Workplace.ai.activation_rate', baseActivationMap);
      const salaryRows = Object.values(plannerSections).flat().filter((r) => String(r.path || '').includes('team_plan'));
      const salaryFactorByYear = new Map();
      rows.forEach((r) => {{
        const year = Number(r.year);
        let num = 0, den = 0;
        salaryRows.forEach((sr) => {{
          const baseVal = yearValue(sr.value, year);
          const tgtVal = yearValue(getOverridden(sr.path, sr.value), year);
          if (baseVal > 0) {{ num += tgtVal; den += baseVal; }}
        }});
        salaryFactorByYear.set(year, den > 0 ? num / den : 1.0);
      }});

      const monthly = rows.map((r) => {{
        const year = Number(r.year);
        const baseActivation = yearValue(baseActivationMap, year);
        const targetActivation = yearValue(targetActivationMap, year);
        const activationRatio = baseActivation > 0 ? targetActivation / baseActivation : 1.0;
        const salaryFactor = salaryFactorByYear.get(year) || 1.0;
        const shiftedSeq = Number(r.month_seq) - constructionShift;
        const infraProxy = shiftedSeq >= 1 ? 1.0 : 0.0;
        const totalRevenue = Number(r.total_revenue || 0) * activationRatio;
        const cogs = Number(r.cogs || 0) * activationRatio / (marginRatio || 1.0);
        const sga = Number(r.sga || 0) * salaryFactor;
        const capex = Math.abs(Number(r.investing_cash_flow || 0)) * gpuUnitCostRatio * infraProxy;
        const ebit = totalRevenue - cogs - sga - Number(r.depreciation_and_amortization || 0);
        return {{
          month_id: r.month_id,
          year,
          preview_total_revenue: Math.round(totalRevenue * 100) / 100,
          preview_cogs: Math.round(cogs * 100) / 100,
          preview_sga: Math.round(sga * 100) / 100,
          preview_capex: Math.round(capex * 100) / 100,
          preview_ebit: Math.round(ebit * 100) / 100,
        }};
      }});
      const byYear = new Map();
      monthly.forEach((r) => {{
        if (!byYear.has(r.year)) byYear.set(r.year, {{year: r.year, preview_total_revenue:0, preview_cogs:0, preview_sga:0, preview_capex:0, preview_ebit:0}});
        const agg = byYear.get(r.year);
        agg.preview_total_revenue += r.preview_total_revenue;
        agg.preview_cogs += r.preview_cogs;
        agg.preview_sga += r.preview_sga;
        agg.preview_capex += r.preview_capex;
        agg.preview_ebit += r.preview_ebit;
      }});
      return Array.from(byYear.values()).sort((a,b)=>a.year-b.year).map((r)=>({{
        ...r,
        preview_total_revenue: Math.round(r.preview_total_revenue * 100) / 100,
        preview_cogs: Math.round(r.preview_cogs * 100) / 100,
        preview_sga: Math.round(r.preview_sga * 100) / 100,
        preview_capex: Math.round(r.preview_capex * 100) / 100,
        preview_ebit: Math.round(r.preview_ebit * 100) / 100,
      }}));
    }}

    function renderOperatingPreview() {{
      const rows = recomputeOperatingPreview();
      document.getElementById('planner-operating-preview').innerHTML = tableHtml('Operating model preview from current overrides (browser-side only)', rows);
    }}

    function renderPlanner() {{
      const host = document.getElementById('key-assumptions-planner');
      const html = Object.entries(plannerSections).map(([sectionName, rows]) => {{
        const sectionRows = rows.map((row) => {{
          const path = row.path || row.label;
          const base = row.value;
          const current = Object.prototype.hasOwnProperty.call(plannerOverrides, path) ? plannerOverrides[path] : base;
          const changed = Object.prototype.hasOwnProperty.call(plannerOverrides, path);
          const editable = plannerEditMode && row.editable !== false;
          const valueCell = editable
            ? `<input data-path="${{path}}" value="${{String(current ?? '').replaceAll('"', '&quot;')}}" />`
            : `${{formatValue(current)}}`;
          return `<tr class="${{changed ? 'override-changed' : ''}}"><td>${{row.label || ''}}</td><td>${{path}}</td><td>${{valueCell}}</td><td>${{row.editable === false ? 'No' : 'Yes'}}</td></tr>`;
        }}).join('');
        return `<h3>${{sectionName}}</h3><table><thead><tr><th>assumption</th><th>path</th><th>value</th><th>editable</th></tr></thead><tbody>${{sectionRows}}</tbody></table>`;
      }}).join('');
      host.innerHTML = html;
      host.querySelectorAll('input[data-path]').forEach((input) => {{
        input.addEventListener('input', (event) => {{
          const path = event.target.getAttribute('data-path');
          const raw = event.target.value;
          const row = Object.values(plannerSections).flat().find((r) => (r.path || r.label) === path);
          const base = row ? row.value : '';
          const normalized = normalizeOverrideValue(raw);
          if (String(normalized) === String(base)) delete plannerOverrides[path];
          else plannerOverrides[path] = normalized;
          updateOverrideCount();
          renderPlanner();
          renderDemandPreview();
          renderOperatingPreview();
        }});
      }});
    }}

    document.getElementById('planner-mode-toggle').addEventListener('click', () => {{
      plannerEditMode = !plannerEditMode;
      document.getElementById('planner-mode-toggle').textContent = plannerEditMode ? 'Switch to View mode' : 'Switch to Edit mode';
      renderPlanner();
    }});
    document.getElementById('planner-reset').addEventListener('click', () => {{ plannerOverrides = {{}}; updateOverrideCount(); renderPlanner(); renderDemandPreview(); renderOperatingPreview(); }});
    document.getElementById('planner-export').addEventListener('click', () => {{
      const payload = {{ schema_version: 'v2-14-assumption-overrides', exported_at_utc: new Date().toISOString(), overrides: plannerOverrides }};
      const blob = new Blob([JSON.stringify(payload, null, 2)], {{ type: 'application/json' }});
      const url = URL.createObjectURL(blob); const a = document.createElement('a'); a.href = url; a.download = 'gps_finmodel_assumption_overrides.json'; a.click(); URL.revokeObjectURL(url);
    }});
    const importFile = document.getElementById('planner-import-file');
    document.getElementById('planner-import').addEventListener('click', () => importFile.click());
    importFile.addEventListener('change', async (event) => {{
      const file = event.target.files && event.target.files[0];
      if (!file) return;
      const text = await file.text();
      const payload = JSON.parse(text);
      plannerOverrides = (payload && typeof payload === 'object' && payload.overrides && typeof payload.overrides === 'object') ? payload.overrides : {{}};
      updateOverrideCount();
      renderPlanner();
      renderDemandPreview();
      renderOperatingPreview();
    }});

    updateOverrideCount();
    renderPlanner();
    renderDemandPreview();
    renderOperatingPreview();
  </script>
</body>
</html>
"""
    with OUT_HTML.open("w", encoding="utf-8") as fh:
        fh.write(html)


def main() -> int:
    assumptions = load_assumptions(ASSUMPTIONS_PATH)
    items = validate(assumptions)
    write_reports(items)
    write_calendar_and_events(assumptions)
    write_monthly_demand_gpu(assumptions)
    write_monthly_infrastructure(assumptions)
    write_monthly_costs(assumptions)
    write_monthly_financials(assumptions)

    calendar_rows = build_monthly_calendar(assumptions)
    demand_rows = build_monthly_demand_gpu(assumptions, calendar_rows)
    infra_rows = build_monthly_infrastructure(assumptions, demand_rows)
    cost_rows = build_monthly_costs(assumptions, calendar_rows, infra_rows)
    fin_rows = build_monthly_financials(assumptions, calendar_rows, demand_rows, infra_rows, cost_rows)
    funding_shares = normalize_funding_scenarios(assumptions, items)
    funded_rows = calculate_monthly_funding(assumptions, fin_rows, cost_rows, funding_shares, items)
    metrics_rows = calculate_investment_metrics(assumptions, funded_rows, items)
    annual_rows = build_annual_report(funded_rows)
    summary_rows = build_scenario_summary(annual_rows, metrics_rows)

    with OUT_MONTHLY_FUNDED_CSV.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(funded_rows[0].keys()) if funded_rows else [])
        if funded_rows:
            writer.writeheader(); writer.writerows(funded_rows)
    with OUT_INVESTMENT_METRICS_CSV.open("w", newline="", encoding="utf-8") as fh:
        fieldnames=["infrastructure_scenario","funding_scenario","npv","irr_annualized","simple_payback_month_key","discounted_payback_month_key","required_investments","peak_required_gpu","ending_revolver_balance","ending_cash","ending_balance_check"]
        writer = csv.DictWriter(fh, fieldnames=fieldnames); writer.writeheader(); writer.writerows(metrics_rows)
    with OUT_ANNUAL_REPORT_CSV.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(annual_rows[0].keys()) if annual_rows else [])
        if annual_rows:
            writer.writeheader(); writer.writerows(annual_rows)
    with OUT_SCENARIO_SUMMARY_CSV.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(summary_rows[0].keys()) if summary_rows else [])
        if summary_rows:
            writer.writeheader(); writer.writerows(summary_rows)
    write_static_html_report(funded_rows, annual_rows, summary_rows, metrics_rows, items, assumptions)

    write_reports(items)
    errors = [x for x in items if x.level == "ERROR"]
    warnings = [x for x in items if x.level == "WARNING"]
    print(f"Validation completed. Errors: {len(errors)}, warnings: {len(warnings)}")
    print(f"TXT: {OUT_TXT}")
    print(f"CSV: {OUT_CSV}")
    print(f"Calendar CSV: {OUT_CALENDAR_CSV}")
    print(f"Events CSV: {OUT_EVENTS_CSV}")
    print(f"Monthly demand/GPU CSV: {OUT_MONTHLY_DEMAND_GPU_CSV}")
    print(f"Monthly infrastructure CSV: {OUT_MONTHLY_INFRA_CSV}")
    print(f"Monthly costs CSV: {OUT_MONTHLY_COSTS_CSV}")
    print(f"Monthly financials CSV: {OUT_MONTHLY_FINANCIALS_CSV}")
    print(f"Monthly funded CSV: {OUT_MONTHLY_FUNDED_CSV}")
    print(f"Investment metrics CSV: {OUT_INVESTMENT_METRICS_CSV}")
    print(f"Annual report CSV: {OUT_ANNUAL_REPORT_CSV}")
    print(f"Scenario summary CSV: {OUT_SCENARIO_SUMMARY_CSV}")
    print(f"Static HTML report: {OUT_HTML}")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
