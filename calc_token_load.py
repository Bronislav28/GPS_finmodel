#!/usr/bin/env python3
"""Расчет token load -> GPU -> CAPEX -> OPEX по assumptions.yaml."""

from __future__ import annotations

import csv
import copy
import json
import math
import sys
from pathlib import Path
from typing import Any

OUT_DIR = Path("output")
OUT_HTML = OUT_DIR / "gps_finmodel.html"
OUT_CSV = OUT_DIR / "gps_finmodel_results.csv"
TARGET_YEARS = [2026, 2027, 2028, 2029, 2030]


def load_yaml(path: Path) -> dict[str, Any]:
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
        raise ValueError("assumptions.yaml должен содержать mapping в корне")
    return data


def to_year_map(src: dict[Any, Any] | None) -> dict[int, Any]:
    if not isinstance(src, dict):
        return {}
    out: dict[int, Any] = {}
    for k, v in src.items():
        try:
            out[int(k)] = v
        except (TypeError, ValueError):
            continue
    return out


def as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def is_nan(v: float | None) -> bool:
    return v is None or (isinstance(v, float) and math.isnan(v))


def safe_mul(*vals: float | None) -> float:
    if any(is_nan(v) for v in vals):
        return float("nan")
    out = 1.0
    for v in vals:
        out *= float(v)
    return out


def safe_add(*vals: float | None) -> float:
    if any(is_nan(v) for v in vals):
        return float("nan")
    return sum(float(v) for v in vals)


def year_value(value: Any, year: int, default: float | None = None) -> float | None:
    if isinstance(value, dict):
        if "value" in value:
            return as_float(value.get("value"))
        try:
            ym = to_year_map(value)
        except (TypeError, ValueError):
            return default
        return as_float(ym.get(year, default))
    if value is None:
        return default
    return as_float(value)


def flatten_role_values(struct: Any, prefix: tuple[str, ...] = ()) -> dict[tuple[str, ...], float]:
    """Flatten nested team->role numeric trees into {(path...): value}."""
    out: dict[tuple[str, ...], float] = {}
    if isinstance(struct, dict):
        for key, value in struct.items():
            out.update(flatten_role_values(value, prefix + (str(key),)))
    else:
        value = as_float(struct)
        if value is not None:
            out[prefix] = value
    return out


def monthly_multipliers(hiring_plan_monthly: Any, year: int) -> list[float]:
    """Resolve 12 monthly hiring multipliers for a given year."""
    source = hiring_plan_monthly
    if isinstance(hiring_plan_monthly, dict):
        year_map = to_year_map(hiring_plan_monthly)
        source = year_map.get(year, hiring_plan_monthly)

    values: list[float] = []
    if isinstance(source, (list, tuple)):
        values = [float(v) for v in source if as_float(v) is not None]
    elif isinstance(source, dict):
        values = [float(v) for v in source.values() if as_float(v) is not None]
    else:
        scalar = as_float(source)
        if scalar is not None:
            values = [scalar]

    if not values:
        return [1.0] * 12
    if len(values) >= 12:
        return values[:12]
    return values + [values[-1]] * (12 - len(values))


def warn_if_missing(value: float | None, field_name: str) -> float | None:
    if value is None:
        print(f"WARNING: отсутствует значение поля '{field_name}'", file=sys.stderr)
    return value


def driver_value(drivers: dict[str, Any], field_name: str) -> float | None:
    raw = drivers.get(field_name)
    if isinstance(raw, dict) and "value" in raw:
        return as_float(raw.get("value"))
    return as_float(raw)


def inflation_index_map(inflation_growth_by_year: dict[int, float], years: list[int]) -> dict[int, float]:
    """Build inflation index with base year index=1.0 and chained annual growth."""
    index: dict[int, float] = {}
    prev_index = 1.0
    for i, year in enumerate(years):
        if i == 0:
            idx = 1.0
        else:
            growth = as_float(inflation_growth_by_year.get(year))
            if growth is None:
                print(f"WARNING: отсутствует rub_inflation для {year}; используется 0.0.", file=sys.stderr)
                growth = 0.0
            idx = prev_index * (1.0 + float(growth))
        index[year] = idx
        prev_index = idx
    return index


def fmt_num(value: float | int | None, digits: int = 2) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "NaN"
    if digits == 0:
        return f"{int(round(float(value))):,}"
    return f"{float(value):,.{digits}f}"


def fmt_ratio(value: float | None) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "NaN"
    return f"{value * 100:.2f}%"


DEFAULT_BLOCKS: list[tuple[str, list[str]]] = [
    (
        "Infrastructure Scenario",
        [
            "active_scenario",
            "construction_start_year",
            "construction_flag",
            "required_gpu",
            "owned_gpu",
            "rented_gpu",
            "owned_gpu_increment",
        ],
    ),
    (
        "Token Load",
        [
            "active_users",
            "workplace_daily_tokens",
            "workplace_annual_tokens",
            "automated_interactions",
            "contact_center_daily_tokens",
            "contact_center_annual_tokens",
            "total_daily_tokens",
            "total_annual_tokens",
        ],
    ),
    ("GPU Calculation", ["weighted_throughput", "tokens_per_second", "required_gpu"]),
    ("CAPEX", ["gpu_capex", "gpu_infra_capex", "datacenter_construction_capex", "total_office_capex", "total_capex", "annual_depreciation"]),
    (
        "Office CAPEX",
        [
            "office_server_capex",
            "employee_laptops_capex",
            "executive_laptops_capex",
            "mfu_capex",
            "meeting_rooms_capex",
            "office_furniture_capex",
            "total_office_capex",
            "office_capex_depreciation",
        ],
    ),
    (
        "Datacenter OPEX",
        [
            "gpu_beginning_of_year",
            "gpu_end_of_year",
            "average_gpu",
            "it_load_mw",
            "total_load_mw",
            "electricity_kwh",
            "electricity_price_t",
            "electricity_cost",
            "maintenance_cost",
            "network_cost",
            "land_rent",
            "datacenter_opex",
            "other_opex",
            "total_datacenter_opex",
        ],
    ),
    (
        "Team OPEX",
        [
            "monthly_fte",
            "monthly_gross",
            "monthly_bonus",
            "monthly_social",
            "monthly_cost_per_fte",
            "monthly_team_cost",
            "annual_team_opex",
        ],
    ),
    ("SG&A", ["annual_fixed_sga", "required_office_area_sqm", "annual_office_rent", "total_sga"]),
    ("GPU Rental OPEX", ["rental_price_per_gpu_per_year", "annual_gpu_rental_cost"]),
    ("Total OPEX", ["total_datacenter_opex", "annual_team_opex", "annual_gpu_rental_cost", "total_opex"]),
    ("Revenue", ["workplace_ai_revenue", "contact_center_ai_revenue", "total_revenue"]),
    (
        "Intangible Assets",
        [
            "workplace_ai_ip_value",
            "contact_center_ai_ip_value",
            "total_intangible_assets",
            "intangible_capex",
            "ip_amortization",
            "gross_intangible_assets",
            "accumulated_amortization",
            "net_intangible_assets",
        ],
    ),
    (
        "P&L Summary",
        ["total_revenue", "total_cogs", "gross_profit", "total_sga", "ebitda", "total_depreciation", "ebit", "interest_expense", "ebt", "profit_tax", "net_income"],
    ),
    (
        "Cash Flow Statement",
        [
            "net_income",
            "total_depreciation",
            "operating_cash_flow",
            "gpu_capex",
            "gpu_infra_capex",
            "datacenter_construction_capex",
            "office_capex",
            "intangible_capex",
            "investing_cash_flow",
            "financing_cash_flow",
            "net_cash_flow",
            "opening_cash",
            "closing_cash",
            "cumulative_cash",
        ],
    ),
    ("Funding", ["funding_need", "equity_injection", "revolver_drawdown", "revolver_repayment", "revolver_balance", "interest_expense", "closing_cash_after_funding"]),
    (
        "Balance Sheet",
        ["cash", "gross_ppe", "accumulated_depreciation", "net_ppe", "gross_intangible_assets", "accumulated_amortization", "net_intangible_assets", "total_assets", "revolver_balance", "total_liabilities", "paid_in_capital", "retained_earnings", "total_equity", "balance_check"],
    ),
    ("Return Metrics", ["roic", "roe", "roa", "debt_to_equity", "net_debt", "net_debt_to_ebitda", "interest_coverage"]),
]
SCENARIO_ORDER = ["conservative", "base", "aggressive"]
SCENARIO_MULTIPLIERS = {"conservative": 0.85, "base": 1.0, "aggressive": 1.2}


def to_wide_rows(rows: list[dict[str, Any]], metrics: list[str], years: list[int]) -> list[dict[str, Any]]:
    """Universal long->wide transformer: Metric | 2026 | ..."""
    by_year = {int(r["year"]): r for r in rows}
    wide: list[dict[str, Any]] = []
    for metric in metrics:
        row: dict[str, Any] = {"Metric": metric}
        for y in years:
            row[str(y)] = by_year.get(y, {}).get(metric, float("nan"))
        wide.append(row)
    return wide


def build_report_blocks(rows: list[dict[str, Any]], years: list[int]) -> list[dict[str, Any]]:
    """Build all report blocks via shared wide-format mechanism."""
    all_metrics = [k for k in rows[0].keys() if k != "year"]
    blocks: list[dict[str, Any]] = []
    used: set[str] = set()

    for title, metrics in DEFAULT_BLOCKS:
        available = [m for m in metrics if m in all_metrics]
        if not available:
            continue
        used.update(available)
        blocks.append({"title": title, "rows": to_wide_rows(rows, available, years)})

    extra = sorted(m for m in all_metrics if m not in used)
    if extra:
        blocks.append({"title": "Additional Metrics", "rows": to_wide_rows(rows, extra, years)})
    return blocks


def build_revenue_scenario_blocks(rows: list[dict[str, Any]], years: list[int]) -> dict[str, list[dict[str, Any]]]:
    """Build scenario-dependent report blocks for Revenue / Unit Economics / P&L."""
    by_year = {int(r["year"]): r for r in rows}
    payload: dict[str, list[dict[str, Any]]] = {}

    for scenario in SCENARIO_ORDER:
        mult = SCENARIO_MULTIPLIERS[scenario]
        scenario_rows: list[dict[str, Any]] = []
        for y in years:
            r = by_year[y]
            tokens = as_float(r.get("total_annual_tokens")) or 0.0
            total_opex = as_float(r.get("total_opex"))
            total_sga = as_float(r.get("total_sga"))
            # Revenue base is derived deterministically from token volume.
            base_revenue = tokens * 0.002
            revenue = base_revenue * mult
            cogs = revenue * 0.35
            gross_profit = revenue - cogs
            gross_margin = gross_profit / revenue if revenue else float("nan")
            revenue_per_1m_tokens = revenue / (tokens / 1_000_000) if tokens else float("nan")
            ebitda = (
                float("nan")
                if total_opex is None or math.isnan(total_opex) or total_sga is None or math.isnan(total_sga)
                else revenue - total_opex - total_sga
            )
            scenario_rows.append(
                {
                    "year": y,
                    "revenue": revenue,
                    "cogs": cogs,
                    "gross_profit": gross_profit,
                    "gross_margin": gross_margin,
                    "revenue_per_1m_tokens": revenue_per_1m_tokens,
                    "annual_team_opex": r.get("annual_team_opex"),
                    "total_datacenter_opex": r.get("total_datacenter_opex"),
                    "total_opex": total_opex,
                    "total_sga": total_sga,
                    "ebitda": ebitda,
                    "ebitda_margin": ebitda / revenue if revenue and not math.isnan(ebitda) else float("nan"),
                }
            )

        payload[scenario] = [
            {"title": "Revenue", "rows": to_wide_rows(scenario_rows, ["revenue", "cogs", "gross_profit", "gross_margin"], years)},
            {
                "title": "Unit Economics",
                "rows": to_wide_rows(scenario_rows, ["revenue_per_1m_tokens", "gross_margin", "ebitda_margin"], years),
            },
            {
                "title": "P&L / Summary",
                "rows": to_wide_rows(
                    scenario_rows,
                    ["revenue", "total_datacenter_opex", "annual_team_opex", "total_opex", "total_sga", "ebitda"],
                    years,
                ),
            },
        ]
    return payload


def harmonic_weighted_throughput(model_share: dict[str, float], throughput: dict[str, float]) -> float:
    share_sum = sum(model_share.values())
    if share_sum <= 0:
        raise ValueError("compute_model.model_mix: сумма долей должна быть > 0")
    normalized = {m: s / share_sum for m, s in model_share.items()}

    denom = 0.0
    for model, share in normalized.items():
        tp = throughput.get(model)
        if tp is None:
            raise KeyError(f"Для модели '{model}' отсутствует throughput_per_gpu")
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
    gpu_sizing_cfg = ass.get("gpu_sizing") or ass.get("gpu_calculation", {})

    candidate_sets = [
        set(to_year_map(usage["Workplace.ai"].get("activation_rate")).keys()),
        set(to_year_map(token_model["Workplace.ai"].get("tokens_per_active_user_per_day")).keys()),
        set(to_year_map(usage["Contact_Center.ai"].get("automation_rate")).keys()),
        set(to_year_map(compute.get("model_mix")).keys()),
        set(to_year_map(compute.get("infra", {}).get("utilization")).keys()),
    ]
    years = set(TARGET_YEARS)
    for s in candidate_sets:
        years &= s
    if not years:
        raise ValueError("Не найдено пересечение годов 2026–2030 в assumptions.yaml")
    return sorted(years)

def resolve_years(ass: dict[str, Any]) -> list[int]:
    usage = ass["usage_assumptions"]
    token_model = ass["token_load_model"]
    compute = ass["compute_model"]

def calculate(ass: dict[str, Any]) -> list[dict[str, Any]]:
    years = ass.get("years") or TARGET_YEARS
    years = [int(y) for y in years]

    usage = ass["usage_assumptions"]
    token_model = ass["token_load_model"]
    compute = ass["compute_model"]
    gpu_sizing_cfg = ass.get("gpu_sizing") or ass.get("gpu_calculation", {})
    capex = ass.get("capex", {})

    # OPEX-блоки: поддержка как top-level datacenter/team, так и legacy opex.datacenter/team
    opex_root = ass.get("opex", {}) if isinstance(ass.get("opex"), dict) else {}
    datacenter = opex_root.get("datacenter", ass.get("datacenter", {}))
    team = opex_root.get("team", ass.get("team", {}))
    sga = ass.get("sga", {})
    drivers = datacenter.get("drivers", {}) if isinstance(datacenter.get("drivers"), dict) else {}
    inflation = ass.get("inflation_assumptions", {}) if isinstance(ass.get("inflation_assumptions"), dict) else {}
    inflation_rub = inflation.get("rub_inflation", {}) if isinstance(inflation.get("rub_inflation"), dict) else {}
    inflation_growth_by_year = to_year_map(inflation_rub.get("annual_growth"))
    inflation_index_by_year = inflation_index_map(inflation_growth_by_year, years)

    wp_usage = usage["Workplace.ai"]
    cc_usage = usage["Contact_Center.ai"]

    wp_activation = to_year_map(wp_usage.get("activation_rate"))
    wp_tokens_per_user = to_year_map(token_model["Workplace.ai"].get("tokens_per_active_user_per_day"))
    cc_automation = to_year_map(cc_usage.get("automation_rate"))
    cc_tokens_per_interaction = year_value(token_model["Contact_Center.ai"].get("tokens_per_interaction"), years[0], None)

    model_mix_by_year = to_year_map(compute.get("model_mix"))
    util_by_year = to_year_map(compute.get("infra", {}).get("utilization"))
    throughput = {name: float(v) for name, v in compute.get("throughput_per_gpu", {}).items()}

    working_days = year_value(token_model["time_assumptions"].get("working_days_per_year"), years[0])
    calendar_days = driver_value(drivers, "calendar_days_per_year")
    if calendar_days is None:
        calendar_days = warn_if_missing(
            year_value(token_model["time_assumptions"].get("calendar_days_per_year"), years[0]),
        "token_load_model.time_assumptions.calendar_days_per_year",
        )
    if working_days is None:
        raise ValueError("Отсутствует token_load_model.time_assumptions.working_days_per_year")
    if calendar_days is None:
        raise ValueError("Отсутствует token_load_model.time_assumptions.calendar_days_per_year")

    working_days = float(working_days)
    calendar_days = float(calendar_days)
    working_hours = float(year_value(gpu_sizing_cfg.get("working_hours_per_day"), years[0], compute["infra"].get("working_hours_per_day", 24)))
    peak_factor = float(year_value(gpu_sizing_cfg.get("peak_factor"), years[0], compute["infra"].get("peak_factor", 1.0)))

    gpu_unit_cost = as_float(capex.get("gpu", {}).get("unit_cost"))
    infra_multiplier = as_float(capex.get("infra_multiplier", {}).get("value"))
    useful_life = int(capex.get("depreciation", {}).get("useful_life_years", capex.get("gpu", {}).get("useful_life_years", 5)))
    useful_life = max(useful_life, 1)
    office_capex_cfg = capex.get("office_capex", {}) if isinstance(capex.get("office_capex"), dict) else {}
    office_server_cfg = office_capex_cfg.get("office_server", {}) if isinstance(office_capex_cfg.get("office_server"), dict) else {}
    employee_laptops_cfg = office_capex_cfg.get("employee_laptops", {}) if isinstance(office_capex_cfg.get("employee_laptops"), dict) else {}
    executive_laptops_cfg = office_capex_cfg.get("executive_laptops", {}) if isinstance(office_capex_cfg.get("executive_laptops"), dict) else {}
    mfu_cfg = office_capex_cfg.get("mfu", {}) if isinstance(office_capex_cfg.get("mfu"), dict) else {}
    meeting_rooms_cfg = office_capex_cfg.get("meeting_rooms", {}) if isinstance(office_capex_cfg.get("meeting_rooms"), dict) else {}
    office_furniture_cfg = office_capex_cfg.get("office_furniture", {}) if isinstance(office_capex_cfg.get("office_furniture"), dict) else {}

    office_server_qty = warn_if_missing(year_value(office_server_cfg.get("quantity"), years[0]), "capex.office_capex.office_server.quantity.value")
    office_server_unit_cost = warn_if_missing(year_value(office_server_cfg.get("unit_cost_rub"), years[0]), "capex.office_capex.office_server.unit_cost_rub.value")
    employee_laptops_unit_cost = warn_if_missing(
        year_value(employee_laptops_cfg.get("unit_cost_rub"), years[0]),
        "capex.office_capex.employee_laptops.unit_cost_rub.value",
    )
    executive_laptops_qty = warn_if_missing(
        year_value(executive_laptops_cfg.get("quantity"), years[0]),
        "capex.office_capex.executive_laptops.quantity.value",
    )
    executive_laptops_unit_cost = warn_if_missing(
        year_value(executive_laptops_cfg.get("unit_cost_rub"), years[0]),
        "capex.office_capex.executive_laptops.unit_cost_rub.value",
    )
    mfu_qty = warn_if_missing(year_value(mfu_cfg.get("quantity"), years[0]), "capex.office_capex.mfu.quantity.value")
    mfu_unit_cost = warn_if_missing(year_value(mfu_cfg.get("unit_cost_rub"), years[0]), "capex.office_capex.mfu.unit_cost_rub.value")
    meeting_rooms_unit_cost = year_value(meeting_rooms_cfg.get("unit_cost_rub"), years[0], 0.0) or 0.0
    meeting_rooms_qty = year_value(meeting_rooms_cfg.get("quantity"), years[0], 0.0) or 0.0
    office_furniture_total_cost = year_value(office_furniture_cfg.get("total_cost_rub"), years[0], 0.0) or 0.0
    office_purchase_year = int(year_value(office_capex_cfg.get("purchase_year"), years[0], years[0]) or years[0])
    office_lives = {
        "office_server": max(1, int(year_value(office_server_cfg.get("useful_life_years"), years[0], 5) or 5)),
        "employee_laptops": max(1, int(year_value(employee_laptops_cfg.get("useful_life_years"), years[0], 3) or 3)),
        "executive_laptops": max(1, int(year_value(executive_laptops_cfg.get("useful_life_years"), years[0], 3) or 3)),
        "mfu": max(1, int(year_value(mfu_cfg.get("useful_life_years"), years[0], 5) or 5)),
        "meeting_rooms": max(1, int(year_value(meeting_rooms_cfg.get("useful_life_years"), years[0], 5) or 5)),
        "office_furniture": max(1, int(year_value(office_furniture_cfg.get("useful_life_years"), years[0], 7) or 7)),
    }

    # Datacenter OPEX assumptions
    gpu_power_kw = warn_if_missing(driver_value(drivers, "gpu_power_kw"), "datacenter.drivers.gpu_power_kw.value")
    pue = warn_if_missing(driver_value(drivers, "pue"), "datacenter.drivers.pue.value")
    operating_hours_per_day = driver_value(drivers, "operating_hours_per_day")
    if operating_hours_per_day is None:
        operating_hours_per_day = 24.0
    electricity_price_cfg = drivers.get("electricity_price", {}) if isinstance(drivers.get("electricity_price"), dict) else {}
    base_price_per_kwh = warn_if_missing(
        year_value(electricity_price_cfg.get("base_price_per_kwh"), years[0]),
        "opex.datacenter.drivers.electricity_price.base_price_per_kwh",
    )
    annual_growth_map = to_year_map(electricity_price_cfg.get("annual_growth"))
    electricity_price_by_year: dict[int, float] = {}
    prev_price = float(base_price_per_kwh or 0.0)
    for i, y in enumerate(years):
        if i == 0:
            electricity_price_by_year[y] = prev_price
        else:
            growth_t = as_float(annual_growth_map.get(y, 0.0))
            growth_t = 0.0 if growth_t is None else float(growth_t)
            prev_price = prev_price * (1.0 + growth_t)
            electricity_price_by_year[y] = prev_price
    maintenance_pct = warn_if_missing(
        driver_value(drivers, "maintenance_percent_of_capex"),
        "datacenter.drivers.maintenance_percent_of_capex.value",
    )
    network_cost_per_mw = warn_if_missing(
        driver_value(drivers, "network_cost_per_mw_per_year"),
        "datacenter.drivers.network_cost_per_mw_per_year.value",
    )
    land_rent_per_mw = warn_if_missing(
        driver_value(drivers, "land_rent_per_mw_per_year"),
        "datacenter.drivers.land_rent_per_mw_per_year.value",
    )
    other_opex_percent = warn_if_missing(
        driver_value(drivers, "other_opex_percent"),
        "datacenter.drivers.other_opex_percent.value",
    )

    # Team assumptions
    target_fte_cfg = team.get("core_team_target_fte")
    salary_cfg = team.get("salary_gross_monthly_rub")
    hiring_plan_cfg = team.get("hiring_plan_monthly")
    payroll = team.get("payroll_assumptions", {}) if isinstance(team.get("payroll_assumptions"), dict) else {}
    salary_growth_map = to_year_map(payroll.get("salary_growth"))
    bonus_cfg = payroll.get("bonus_percent_of_gross")
    social_cfg = payroll.get("social_contribution_sfr_percent_of_gross")
    sga_target_fte_cfg: Any = None
    sga_hiring_plan_cfg: Any = None
    if isinstance(sga, dict):
        for key in ("target_fte", "core_team_target_fte", "team_target_fte"):
            if isinstance(sga.get(key), dict):
                sga_target_fte_cfg = sga.get(key)
                break
        if isinstance(sga.get("hiring_plan_monthly"), (dict, list, tuple, int, float)):
            sga_hiring_plan_cfg = sga.get("hiring_plan_monthly")
    sga_target_fte_map = flatten_role_values(sga.get("target_fte", {})) if isinstance(sga, dict) else {}
    sga_salary_map = flatten_role_values(sga.get("salary_gross_monthly_rub", {})) if isinstance(sga, dict) else {}
    sga_payroll = sga.get("payroll_assumptions", {}) if isinstance(sga.get("payroll_assumptions"), dict) else {}
    office_rent_cfg = sga.get("office_rent", {}) if isinstance(sga.get("office_rent"), dict) else {}
    office_rent_drivers = office_rent_cfg.get("drivers", {}) if isinstance(office_rent_cfg.get("drivers"), dict) else {}
    sqm_per_fte = warn_if_missing(
        year_value(office_rent_drivers.get("sqm_per_fte"), years[0]),
        "sga.office_rent.drivers.sqm_per_fte.value",
    )
    rent_base_2026 = warn_if_missing(
        year_value(office_rent_drivers.get("rent_rub_per_sqm_per_month_base_2026"), years[0]),
        "sga.office_rent.drivers.rent_rub_per_sqm_per_month_base_2026.value",
    )

    seconds_per_year = working_days * working_hours * 3600.0
    if seconds_per_year <= 0:
        raise ValueError("working_days_per_year * working_hours_per_day * 3600 должно быть > 0")

    scenario_cfg = capex.get("strategy_scenarios", {})
    scenario_name = scenario_cfg.get("active_scenario")
    scenarios = scenario_cfg.get("scenarios", {}) if isinstance(scenario_cfg.get("scenarios"), dict) else {}
    if scenario_name not in scenarios:
        print(
            f"WARNING: capex.strategy_scenarios.active_scenario='{scenario_name}' не найден; используется build_own_dc.",
            file=sys.stderr,
        )
        scenario_name = "build_own_dc"
    active_scenario = scenarios.get(scenario_name, {}) if isinstance(scenarios.get(scenario_name), dict) else {}
    construction_start_year = active_scenario.get("construction_start_year")
    construction_flag_map = to_year_map(active_scenario.get("construction_flag"))

    fx_cfg = ass.get("fx_assumptions", {}).get("usd_rub", {}) if isinstance(ass.get("fx_assumptions"), dict) else {}
    fx_base_value = warn_if_missing(as_float(fx_cfg.get("base_value")), "fx_assumptions.usd_rub.base_value")
    fx_growth_map = to_year_map(fx_cfg.get("annual_growth"))
    dc_build = capex.get("datacenter_construction", {})
    benchmark_capacity_mw = warn_if_missing(as_float(dc_build.get("benchmark_capacity_mw")), "capex.datacenter_construction.benchmark_capacity_mw")
    benchmark_components = dc_build.get("benchmark_components_3mw_usd_mln", {})
    component_total_3mw = warn_if_missing(as_float(benchmark_components.get("total")), "capex.datacenter_construction.benchmark_components_3mw_usd_mln.total")

    rental_price_per_gpu_per_year = warn_if_missing(
        year_value(opex_root.get("gpu_rental", {}).get("rental_price_per_gpu_per_year"), years[0]),
        "opex.gpu_rental.rental_price_per_gpu_per_year.value",
    )
    revenue_cfg = ass.get("revenue", {}) if isinstance(ass.get("revenue"), dict) else {}
    revenue_scenario = str(revenue_cfg.get("active_scenario", "base"))
    if revenue_scenario not in revenue_cfg.get("consumption_scenarios", {}):
        print(f"WARNING: revenue.active_scenario='{revenue_scenario}' не найден; используется base.", file=sys.stderr)
        revenue_scenario = "base"
    util_map = to_year_map(
        ((revenue_cfg.get("consumption_scenarios", {}).get(revenue_scenario, {}) or {}).get("utilization_of_token_capacity"))
    )
    margin_map = to_year_map((revenue_cfg.get("target_contribution_margin", {}) or {}).get(revenue_scenario))
    profit_tax_rate = year_value(((ass.get("pnl", {}) or {}).get("tax", {}) or {}).get("profit_tax_rate"), years[0], 0.0)
    if profit_tax_rate is None:
        print("WARNING: pnl.tax.profit_tax_rate отсутствует; используется 0.", file=sys.stderr)
        profit_tax_rate = 0.0
    cash_flow_cfg = ass.get("cash_flow", {}) if isinstance(ass.get("cash_flow"), dict) else {}
    opening_cash_map = to_year_map(cash_flow_cfg.get("opening_cash_balance"))
    funding_cfg = ass.get("funding", {}) if isinstance(ass.get("funding"), dict) else {}
    funding_scenario = funding_cfg.get("active_scenario", "equity_only")
    funding_scenarios = funding_cfg.get("scenarios", {}) if isinstance(funding_cfg.get("scenarios"), dict) else {}
    funding_shares = funding_scenarios.get(funding_scenario, {}) if isinstance(funding_scenarios.get(funding_scenario), dict) else {}
    equity_share = year_value((funding_shares.get("equity_share", {}) or {}).get("value"), years[0], 0.0) or 0.0
    revolver_share = year_value((funding_shares.get("revolver_share", {}) or {}).get("value"), years[0], 0.0) or 0.0
    if funding_scenario == "equity_only":
        equity_share, revolver_share = 1.0, 0.0
    elif funding_scenario == "revolver_only":
        equity_share, revolver_share = 0.0, 1.0
    if abs((equity_share + revolver_share) - 1.0) > 1e-9:
        print(f"WARNING: funding shares sum != 1.0 ({equity_share + revolver_share:.4f})", file=sys.stderr)
    revolver_rate_map = to_year_map((funding_cfg.get("revolver", {}) or {}).get("interest_rate"))
    min_cash_cfg = ((funding_cfg.get("revolver", {}) or {}).get("repayment_logic", {}) or {}).get("minimum_cash_balance", {}) or {}
    min_cash_buffer_months = as_float((min_cash_cfg.get("months_of_fixed_costs", {}) or {}).get("value")) or 0.0

    base_rows: list[dict[str, Any]] = []
    prev_required_gpu = 0
    for year in years:
        active_users = safe_mul(year_value(wp_usage.get("total_employees"), year), as_float(wp_activation.get(year)))
        wp_daily_tokens = safe_mul(active_users, as_float(wp_tokens_per_user.get(year)))
        wp_annual_tokens = safe_mul(wp_daily_tokens, working_days)
        automated_interactions = safe_mul(year_value(cc_usage.get("interactions_per_day"), year), as_float(cc_automation.get(year)))
        cc_daily_tokens = safe_mul(automated_interactions, cc_tokens_per_interaction)
        cc_annual_tokens = safe_mul(cc_daily_tokens, calendar_days)
        total_daily_tokens = safe_add(wp_daily_tokens, cc_daily_tokens)
        total_annual_tokens = safe_add(wp_annual_tokens, cc_annual_tokens)
        if is_nan(total_annual_tokens) or total_annual_tokens == 0:
            wp_share = float("nan")
            cc_share = float("nan")
        else:
            wp_share = float(wp_annual_tokens) / float(total_annual_tokens)
            cc_share = float(cc_annual_tokens) / float(total_annual_tokens)

        mix = {model: float(share) for model, share in model_mix_by_year[year].items()}
        weighted_tp = harmonic_weighted_throughput(mix, throughput)
        utilization = as_float(util_by_year.get(year))
        if utilization is None:
            utilization = year_value(gpu_sizing_cfg.get("utilization"), year, year_value(gpu_sizing_cfg.get("utilization"), years[0], None))
        if is_nan(utilization) or float(utilization) <= 0:
            raise ValueError(f"compute_model.infra.utilization[{year}] должен быть > 0")
        tokens_per_second = float(total_annual_tokens) / seconds_per_year
        required_gpu_raw = tokens_per_second / (weighted_tp * float(utilization)) * peak_factor
        required_gpu = int(math.ceil(required_gpu_raw))
        required_gpu_increment = required_gpu if year == years[0] else max(required_gpu - prev_required_gpu, 0)
        base_rows.append(
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
            }
        )
        prev_required_gpu = required_gpu

    peak_required_gpu = max((int(r["required_gpu"]) for r in base_rows), default=0)
    target_capacity_mw = float("nan")
    if gpu_power_kw is not None and pue is not None:
        it_peak_mw = peak_required_gpu * gpu_power_kw / 1000
        total_peak_mw = it_peak_mw * pue
        target_capacity_mw = float(math.ceil(total_peak_mw))

    products_cfg = (((ass.get("capex", {}) or {}).get("intangible_assets", {}) or {}).get("products", {}) or {})
    wp_go_live_cfg = products_cfg.get("workplace_ai", {}) if isinstance(products_cfg.get("workplace_ai"), dict) else {}
    cc_go_live_cfg = products_cfg.get("contact_center_ai", {}) if isinstance(products_cfg.get("contact_center_ai"), dict) else {}

    def revenue_availability_factor(year: int, go_live_year: Any, go_live_month: Any) -> float:
        try:
            go_year = int(go_live_year)
        except (TypeError, ValueError):
            return 1.0
        try:
            go_month = int(go_live_month) if go_live_month is not None else 1
        except (TypeError, ValueError):
            go_month = 1
        go_month = min(max(go_month, 1), 12)
        if year < go_year:
            return 0.0
        if year > go_year:
            return 1.0
        active_months = max(12 - go_month + 1, 0)
        return active_months / 12.0

    rows: list[dict[str, Any]] = []
    gpu_infra_capex_history: list[float] = []
    datacenter_capex_history: list[float] = []
    office_capex_history: dict[str, list[float]] = {
        "office_server": [],
        "employee_laptops": [],
        "executive_laptops": [],
        "mfu": [],
        "meeting_rooms": [],
        "office_furniture": [],
    }
    intangible_capex_history: list[float] = []
    workplace_ip_history: list[float] = []
    contact_center_ip_history: list[float] = []
    prev_electricity_price: float | None = None
    prev_fx: float | None = None
    prev_owned_gpu = 0
    prev_closing_cash: float | None = None
    prev_revolver_balance = 0.0
    cumulative_equity_injection = 0.0
    cumulative_net_income = 0.0
    cumulative_cash_prev = 0.0
    salary_growth_factor = 1.0
    warned_missing_salary: set[tuple[str, ...]] = set()

    for base in base_rows:
        year = int(base["year"])
        required_gpu = int(base["required_gpu"])

        if scenario_name == "build_own_dc":
            owned_gpu, rented_gpu = required_gpu, 0
        elif scenario_name == "rent_gpu_only":
            owned_gpu, rented_gpu = 0, required_gpu
        elif scenario_name == "hybrid":
            if construction_start_year is None:
                owned_gpu, rented_gpu = 0, required_gpu
            elif year < int(construction_start_year):
                owned_gpu, rented_gpu = 0, required_gpu
            else:
                owned_gpu, rented_gpu = required_gpu, 0
        else:
            owned_gpu, rented_gpu = required_gpu, 0

        owned_gpu_increment = owned_gpu if year == years[0] else max(owned_gpu - prev_owned_gpu, 0)
        construction_flag = 0
        if scenario_name != "rent_gpu_only":
            if construction_start_year is not None and year == int(construction_start_year):
                construction_flag = 1
            elif not construction_flag_map:
                construction_flag = 0
            else:
                construction_flag = int(as_float(construction_flag_map.get(year)) or 0)

        if fx_base_value is None:
            fx_usd_rub_t = float("nan")
        elif year == years[0]:
            fx_usd_rub_t = fx_base_value
        else:
            growth_t = as_float(fx_growth_map.get(year, 0.0))
            fx_usd_rub_t = float("nan") if prev_fx is None or growth_t is None else prev_fx * (1 + growth_t)
        prev_fx = fx_usd_rub_t

        if benchmark_capacity_mw in (None, 0) or component_total_3mw is None or math.isnan(target_capacity_mw):
            datacenter_construction_capex = float("nan")
        else:
            total_component_usd_mln = component_total_3mw * target_capacity_mw / benchmark_capacity_mw
            total_component_rub = total_component_usd_mln * 1_000_000 * fx_usd_rub_t
            datacenter_construction_capex = total_component_rub * construction_flag

        if gpu_unit_cost is None:
            gpu_capex = float("nan")
        else:
            gpu_capex = owned_gpu_increment * gpu_unit_cost
        gpu_infra_capex = safe_mul(gpu_capex, infra_multiplier)
        depreciable_infra_capex = safe_add(gpu_infra_capex, datacenter_construction_capex)

        # Datacenter OPEX (owned infra only)
        gpu_beginning_of_year = float(prev_owned_gpu)
        gpu_end_of_year = float(owned_gpu)
        average_gpu = (gpu_beginning_of_year + gpu_end_of_year) / 2.0
        it_load_mw = safe_mul(average_gpu, gpu_power_kw, 1 / 1000)
        total_load_mw = safe_mul(it_load_mw, pue)
        electricity_kwh = safe_mul(total_load_mw, 1000, operating_hours_per_day, calendar_days)

        electricity_price_t = float(electricity_price_by_year.get(year, 0.0))
        electricity_price = electricity_price_t
        if owned_gpu <= 0:
            electricity_cost = 0.0
            maintenance_cost = 0.0
            network_cost = 0.0
            land_rent = 0.0
            datacenter_opex = 0.0
            other_opex = 0.0
            total_datacenter_opex = 0.0
        else:
            electricity_cost = safe_mul(electricity_kwh, electricity_price_t)
            maintenance_base = safe_add(sum(gpu_infra_capex_history), sum(datacenter_capex_history), gpu_infra_capex, datacenter_construction_capex)
            maintenance_cost = safe_mul(maintenance_base, maintenance_pct)
            network_cost = safe_mul(total_load_mw, network_cost_per_mw)
            land_rent = safe_mul(total_load_mw, land_rent_per_mw)
            datacenter_opex = safe_add(electricity_cost, maintenance_cost, network_cost, land_rent)
            other_opex = safe_mul(datacenter_opex, other_opex_percent)
            total_datacenter_opex = safe_add(datacenter_opex, other_opex)
        prev_electricity_price = electricity_price_t

        annual_gpu_rental_cost = safe_mul(rented_gpu, rental_price_per_gpu_per_year)

        # Team OPEX
        role_target_fte = flatten_role_values(target_fte_cfg)
        role_salary_base = flatten_role_values(salary_cfg)
        multipliers = monthly_multipliers(hiring_plan_cfg, year)
        bonus_percent = year_value(bonus_cfg, year)
        social_percent = year_value(social_cfg, year)

        if year != years[0]:
            salary_growth_t = as_float(salary_growth_map.get(year, 0.0))
            salary_growth_factor *= 1.0 if salary_growth_t is None else 1.0 + salary_growth_t

        total_fte_months = 0.0
        total_gross_cost_year = 0.0
        total_bonus_cost_year = 0.0
        total_social_cost_year = 0.0
        annual_team_opex = 0.0

        for mult in multipliers:
            monthly_total_fte = 0.0
            monthly_total_cost = 0.0
            monthly_gross_cost = 0.0
            monthly_bonus_cost = 0.0
            monthly_social_cost = 0.0

            for role_path, target_fte_role in role_target_fte.items():
                salary_base_role = role_salary_base.get(role_path, 0.0)
                if role_path not in role_salary_base and role_path not in warned_missing_salary:
                    warned_missing_salary.add(role_path)
                    print(
                        f"WARNING: salary_gross_monthly_rub отсутствует для роли {'/'.join(role_path)}; используется 0.",
                        file=sys.stderr,
                    )

                monthly_fte_role = target_fte_role * float(mult)
                role_monthly_gross = salary_base_role * salary_growth_factor
                role_monthly_bonus = role_monthly_gross * float(bonus_percent or 0.0)
                role_monthly_social = (role_monthly_gross + role_monthly_bonus) * float(social_percent or 0.0)
                role_monthly_cost = role_monthly_gross + role_monthly_bonus + role_monthly_social

                monthly_total_fte += monthly_fte_role
                monthly_total_cost += monthly_fte_role * role_monthly_cost
                monthly_gross_cost += monthly_fte_role * role_monthly_gross
                monthly_bonus_cost += monthly_fte_role * role_monthly_bonus
                monthly_social_cost += monthly_fte_role * role_monthly_social

            total_fte_months += monthly_total_fte
            total_gross_cost_year += monthly_gross_cost
            total_bonus_cost_year += monthly_bonus_cost
            total_social_cost_year += monthly_social_cost
            annual_team_opex += monthly_total_cost

        monthly_fte = total_fte_months / 12.0
        monthly_team_cost = annual_team_opex / 12.0
        if total_fte_months > 0:
            monthly_gross = total_gross_cost_year / total_fte_months
            monthly_bonus = total_bonus_cost_year / total_fte_months
            monthly_social = total_social_cost_year / total_fte_months
            monthly_cost_per_fte = monthly_gross + monthly_bonus + monthly_social
        else:
            monthly_gross = 0.0
            monthly_bonus = 0.0
            monthly_social = 0.0
            monthly_cost_per_fte = 0.0

        if sga_target_fte_cfg is not None:
            sga_role_target_fte = flatten_role_values(sga_target_fte_cfg)
            sga_multipliers = monthly_multipliers(sga_hiring_plan_cfg, year)
            sga_total_fte_months = 0.0
            for mult in sga_multipliers:
                sga_total_fte_months += sum(v * float(mult) for v in sga_role_target_fte.values())
            sga_monthly_fte = sga_total_fte_months / 12.0
        else:
            sga_monthly_fte = 0.0

        total_core_team_fte = monthly_fte
        total_sga_fte = sga_monthly_fte
        total_fte = safe_add(total_core_team_fte, total_sga_fte)
        inflation_index_t = inflation_index_by_year.get(year, float("nan"))
        sga_bonus_pct = year_value(sga_payroll.get("annual_bonus_percent_of_gross"), year, 0.0) or 0.0
        sga_social_pct = year_value(sga_payroll.get("social_contribution_sfr_percent_of_gross"), year, 0.0) or 0.0
        annual_fixed_sga = 0.0
        for role_path, role_fte in sga_target_fte_map.items():
            role_salary = sga_salary_map.get(role_path, 0.0)
            salary_idx = safe_mul(role_salary, inflation_index_t)
            role_monthly_total = safe_mul(salary_idx, 1.0 + float(sga_bonus_pct), 1.0 + float(sga_social_pct))
            annual_fixed_sga += role_fte * role_monthly_total * 12.0
        required_office_area_sqm = safe_mul(total_fte, sqm_per_fte)
        rent_rub_per_sqm_per_month_t = safe_mul(rent_base_2026, inflation_index_t)
        monthly_office_rent = safe_mul(required_office_area_sqm, rent_rub_per_sqm_per_month_t)
        annual_office_rent = safe_mul(monthly_office_rent, 12.0)
        total_sga = safe_add(annual_fixed_sga, annual_office_rent)
        purchase_flag = 1.0 if year == office_purchase_year else 0.0
        is_office_capex_purchase_year = purchase_flag == 1.0
        office_server_capex = safe_mul(office_server_qty, office_server_unit_cost) if is_office_capex_purchase_year else 0.0
        employee_laptops_capex = safe_mul(total_fte, employee_laptops_unit_cost) if is_office_capex_purchase_year else 0.0
        executive_laptops_capex = safe_mul(executive_laptops_qty, executive_laptops_unit_cost) if is_office_capex_purchase_year else 0.0
        mfu_capex = safe_mul(mfu_qty, mfu_unit_cost) if is_office_capex_purchase_year else 0.0
        meeting_rooms_capex = safe_mul(meeting_rooms_qty, meeting_rooms_unit_cost, purchase_flag)
        office_furniture_capex = safe_mul(office_furniture_total_cost, purchase_flag)
        total_office_capex = safe_add(
            office_server_capex,
            employee_laptops_capex,
            executive_laptops_capex,
            mfu_capex,
            meeting_rooms_capex,
            office_furniture_capex,
        )

        office_capex_history["office_server"].append(office_server_capex)
        office_capex_history["employee_laptops"].append(employee_laptops_capex)
        office_capex_history["executive_laptops"].append(executive_laptops_capex)
        office_capex_history["mfu"].append(mfu_capex)
        office_capex_history["meeting_rooms"].append(meeting_rooms_capex)
        office_capex_history["office_furniture"].append(office_furniture_capex)

        office_server_window = office_capex_history["office_server"][-office_lives["office_server"] :]
        office_server_depreciation = float("nan") if any(math.isnan(v) for v in office_server_window) else sum(office_server_window) / office_lives["office_server"]
        employee_laptops_window = office_capex_history["employee_laptops"][-office_lives["employee_laptops"] :]
        employee_laptops_depreciation = (
            float("nan") if any(math.isnan(v) for v in employee_laptops_window) else sum(employee_laptops_window) / office_lives["employee_laptops"]
        )
        executive_laptops_window = office_capex_history["executive_laptops"][-office_lives["executive_laptops"] :]
        executive_laptops_depreciation = (
            float("nan") if any(math.isnan(v) for v in executive_laptops_window) else sum(executive_laptops_window) / office_lives["executive_laptops"]
        )
        mfu_window = office_capex_history["mfu"][-office_lives["mfu"] :]
        mfu_depreciation = float("nan") if any(math.isnan(v) for v in mfu_window) else sum(mfu_window) / office_lives["mfu"]
        meeting_rooms_window = office_capex_history["meeting_rooms"][-office_lives["meeting_rooms"] :]
        meeting_rooms_depreciation = (
            float("nan") if any(math.isnan(v) for v in meeting_rooms_window) else sum(meeting_rooms_window) / office_lives["meeting_rooms"]
        )
        office_furniture_window = office_capex_history["office_furniture"][-office_lives["office_furniture"] :]
        office_furniture_depreciation = (
            float("nan") if any(math.isnan(v) for v in office_furniture_window) else sum(office_furniture_window) / office_lives["office_furniture"]
        )
        office_capex_depreciation = safe_add(
            office_server_depreciation,
            employee_laptops_depreciation,
            executive_laptops_depreciation,
            mfu_depreciation,
            meeting_rooms_depreciation,
            office_furniture_depreciation,
        )
        dev_assumptions = (((ass.get("capex", {}) or {}).get("intangible_assets", {}) or {}).get("development_assumptions", {}) or {})
        dev_infra_pct = as_float((dev_assumptions.get("development_infrastructure_percent", {}) or {}).get("value")) or 0.0
        data_acq_pct = as_float((dev_assumptions.get("data_acquisition_percent", {}) or {}).get("value")) or 0.0

        def build_phase_factor(year_value_int: int, product_cfg: dict[str, Any]) -> float:
            go_year = as_float(product_cfg.get("go_live_year"))
            go_month = as_float(product_cfg.get("go_live_month"))
            build_months = as_float(product_cfg.get("build_period_months"))
            if go_year is None or build_months is None:
                return 0.0
            go_year_i = int(go_year)
            go_month_i = int(go_month) if go_month is not None else 1
            go_month_i = min(max(go_month_i, 1), 12)
            build_months_i = max(int(build_months), 0)
            if year_value_int != go_year_i or build_months_i == 0:
                return 0.0
            active_build_months = min(build_months_i, max(go_month_i - 1, 0))
            return active_build_months / 12.0

        wp_effort_share = as_float((wp_go_live_cfg.get("effort_share_of_core_team", {}) or {}).get("value")) or 0.0
        cc_effort_share = as_float((cc_go_live_cfg.get("effort_share_of_core_team", {}) or {}).get("value")) or 0.0
        wp_build_factor = build_phase_factor(year, wp_go_live_cfg)
        cc_build_factor = build_phase_factor(year, cc_go_live_cfg)
        capitalization_multiplier = 1.0 + dev_infra_pct + data_acq_pct
        capitalized_core_team_cost = safe_mul(annual_team_opex, safe_add(wp_effort_share, cc_effort_share), max(wp_build_factor, cc_build_factor))
        annual_core_team_cash_cost = annual_team_opex
        total_team_opex = safe_add(annual_core_team_cash_cost, -capitalized_core_team_cost)
        workplace_ai_ip_value = safe_mul(annual_core_team_cash_cost, wp_effort_share, wp_build_factor, capitalization_multiplier)
        contact_center_ai_ip_value = safe_mul(annual_core_team_cash_cost, cc_effort_share, cc_build_factor, capitalization_multiplier)
        intangible_capex = safe_add(workplace_ai_ip_value, contact_center_ai_ip_value)
        workplace_ip_history.append(workplace_ai_ip_value)
        contact_center_ip_history.append(contact_center_ai_ip_value)
        intangible_capex_history.append(intangible_capex)
        ip_life = max(1, int((((ass.get("depreciation_and_amortization", {}) or {}).get("intangible_amortization", {}) or {}).get("useful_life_years", {}) or {}).get("ip_assets", 5)))
        wp_ip_window = workplace_ip_history[-ip_life:]
        cc_ip_window = contact_center_ip_history[-ip_life:]
        workplace_ai_amortization = float("nan") if any(math.isnan(v) for v in wp_ip_window) else sum(wp_ip_window) / ip_life
        contact_center_ai_amortization = float("nan") if any(math.isnan(v) for v in cc_ip_window) else sum(cc_ip_window) / ip_life
        total_ip_amortization = safe_add(workplace_ai_amortization, contact_center_ai_amortization)
        ip_amortization = total_ip_amortization

        total_capex = safe_add(gpu_infra_capex, datacenter_construction_capex, total_office_capex, intangible_capex)
        gpu_infra_capex_history.append(gpu_infra_capex)
        datacenter_capex_history.append(datacenter_construction_capex)
        gpu_window = gpu_infra_capex_history[-useful_life:]
        datacenter_window = datacenter_capex_history[-useful_life:]
        gpu_depreciation = float("nan") if any(math.isnan(v) for v in gpu_window) else sum(gpu_window) / useful_life
        datacenter_depreciation = float("nan") if any(math.isnan(v) for v in datacenter_window) else sum(datacenter_window) / useful_life
        total_ppe_depreciation = safe_add(gpu_depreciation, datacenter_depreciation, office_capex_depreciation)
        total_depreciation_and_amortization = safe_add(total_ppe_depreciation, total_ip_amortization)

        payroll_gross = total_gross_cost_year
        annual_bonus = total_bonus_cost_year
        social_contribution_sfr = total_social_cost_year
        total_opex = safe_add(total_datacenter_opex, annual_team_opex, annual_gpu_rental_cost)
        total_cogs = safe_add(total_datacenter_opex, total_team_opex, annual_gpu_rental_cost)

        utilization = as_float(util_map.get(year))
        contribution_margin = as_float(margin_map.get(year))
        wp_revenue_factor = revenue_availability_factor(year, wp_go_live_cfg.get("go_live_year"), wp_go_live_cfg.get("go_live_month"))
        cc_revenue_factor = revenue_availability_factor(year, cc_go_live_cfg.get("go_live_year"), cc_go_live_cfg.get("go_live_month"))

        if utilization is None or contribution_margin is None:
            print(f"WARNING: revenue assumptions missing for {year}; revenue set to 0.", file=sys.stderr)
            total_revenue = 0.0
            workplace_ai_revenue = 0.0
            contact_center_ai_revenue = 0.0
            workplace_implied_price_per_1m_tokens = float("nan")
            contact_center_implied_price_per_1m_tokens = float("nan")
        else:
            sold_wp_tokens = safe_mul(safe_mul(as_float(base.get("workplace_annual_tokens")), utilization), wp_revenue_factor)
            sold_cc_tokens = safe_mul(safe_mul(as_float(base.get("contact_center_annual_tokens")), utilization), cc_revenue_factor)
            pricing_base = safe_add(total_cogs, total_depreciation_and_amortization)
            pricing_base_wp = safe_mul(pricing_base, as_float(base.get("workplace_token_share")))
            pricing_base_cc = safe_mul(pricing_base, as_float(base.get("contact_center_token_share")))
            denom = (1.0 - contribution_margin) if contribution_margin < 1 else 0.0
            workplace_revenue_full_year = safe_mul(pricing_base_wp, 1.0 / denom) if denom > 0 else 0.0
            contact_center_revenue_full_year = safe_mul(pricing_base_cc, 1.0 / denom) if denom > 0 else 0.0
            workplace_ai_revenue = safe_mul(workplace_revenue_full_year, wp_revenue_factor)
            contact_center_ai_revenue = safe_mul(contact_center_revenue_full_year, cc_revenue_factor)
            total_revenue = safe_add(workplace_ai_revenue, contact_center_ai_revenue)
            workplace_implied_price_per_1m_tokens = (
                (workplace_ai_revenue / sold_wp_tokens) * 1_000_000 if sold_wp_tokens and sold_wp_tokens > 0 else float("nan")
            )
            contact_center_implied_price_per_1m_tokens = (
                (contact_center_ai_revenue / sold_cc_tokens) * 1_000_000 if sold_cc_tokens and sold_cc_tokens > 0 else float("nan")
            )

        gross_profit = safe_add(total_revenue, -total_cogs)
        ebitda = safe_add(gross_profit, -total_sga)
        ebit = safe_add(ebitda, -total_depreciation_and_amortization)
        office_capex = total_office_capex
        investing_cash_flow = safe_add(-gpu_infra_capex, -datacenter_construction_capex, -office_capex, -intangible_capex)
        financing_cash_flow = 0.0

        opening_revolver_balance = prev_revolver_balance
        revolver_interest_rate = float(as_float(revolver_rate_map.get(year, 0.0)) or 0.0)
        monthly_team_opex = safe_mul(total_team_opex, 1 / 12.0)
        monthly_sga = safe_mul(total_sga, 1 / 12.0)
        monthly_gpu_rental_opex = safe_mul(annual_gpu_rental_cost, 1 / 12.0)
        monthly_fixed_costs = safe_add(monthly_team_opex, monthly_sga, monthly_gpu_rental_opex)
        minimum_cash_balance = safe_mul(monthly_fixed_costs, min_cash_buffer_months)
        interest_expense = ((opening_revolver_balance + opening_revolver_balance) / 2.0) * revolver_interest_rate
        ebt = safe_add(ebit, -interest_expense)
        profit_tax = max(ebt, 0.0) * float(profit_tax_rate) if not math.isnan(ebt) else float("nan")
        net_income = safe_add(ebt, -profit_tax)
        operating_cash_flow = safe_add(net_income, total_depreciation_and_amortization)
        pre_financing_cash_flow = safe_add(operating_cash_flow, investing_cash_flow)
        net_cash_flow = safe_add(pre_financing_cash_flow, financing_cash_flow)
        opening_cash = as_float(opening_cash_map.get(year))
        if opening_cash is None:
            opening_cash = prev_closing_cash if prev_closing_cash is not None else 0.0
        closing_cash_before_funding = safe_add(opening_cash, pre_financing_cash_flow)
        funding_need = max(-(closing_cash_before_funding or 0.0), 0.0)
        equity_injection = funding_need * equity_share
        revolver_drawdown = funding_need * revolver_share
        cash_after_drawdown = safe_add(closing_cash_before_funding, equity_injection, revolver_drawdown)
        excess_cash_available_for_repayment = max((cash_after_drawdown or 0.0) - minimum_cash_balance, 0.0)
        revolver_repayment = min(excess_cash_available_for_repayment, opening_revolver_balance)
        revolver_balance = opening_revolver_balance + revolver_drawdown - revolver_repayment
        avg_revolver_balance = (opening_revolver_balance + revolver_balance) / 2.0
        interest_expense = avg_revolver_balance * revolver_interest_rate
        ebt = safe_add(ebit, -interest_expense)
        profit_tax = max(ebt, 0.0) * float(profit_tax_rate) if not math.isnan(ebt) else float("nan")
        net_income = safe_add(ebt, -profit_tax)
        operating_cash_flow = safe_add(net_income, total_depreciation_and_amortization)
        financing_cash_flow = safe_add(equity_injection, revolver_drawdown, -revolver_repayment)
        pre_financing_cash_flow = safe_add(operating_cash_flow, investing_cash_flow)
        net_cash_flow = safe_add(pre_financing_cash_flow, financing_cash_flow)
        closing_cash_before_funding = safe_add(opening_cash, pre_financing_cash_flow)
        funding_need = max(-(closing_cash_before_funding or 0.0), 0.0)
        equity_injection = funding_need * equity_share
        revolver_drawdown = funding_need * revolver_share
        cash_after_drawdown = safe_add(closing_cash_before_funding, equity_injection, revolver_drawdown)
        excess_cash_available_for_repayment = max((cash_after_drawdown or 0.0) - minimum_cash_balance, 0.0)
        revolver_repayment = min(excess_cash_available_for_repayment, opening_revolver_balance)
        revolver_balance = opening_revolver_balance + revolver_drawdown - revolver_repayment
        closing_cash_after_funding = safe_add(cash_after_drawdown, -revolver_repayment)
        closing_cash = closing_cash_after_funding
        cumulative_cash = safe_add(cumulative_cash_prev, net_cash_flow)
        cumulative_equity_injection += equity_injection
        cumulative_net_income += (net_income or 0.0)
        gross_ppe = sum(gpu_infra_capex_history) + sum(datacenter_capex_history) + sum(sum(v) for v in office_capex_history.values())
        accumulated_depreciation = sum((as_float(r.get("total_ppe_depreciation")) or 0.0) for r in rows) + total_ppe_depreciation
        net_ppe = gross_ppe - accumulated_depreciation
        gross_intangible_assets = sum(intangible_capex_history)
        accumulated_amortization = sum((as_float(r.get("total_ip_amortization")) or 0.0) for r in rows) + total_ip_amortization
        net_intangible_assets = gross_intangible_assets - accumulated_amortization
        cash = closing_cash_after_funding
        total_assets = cash + net_ppe + net_intangible_assets
        total_liabilities = revolver_balance
        paid_in_capital = cumulative_equity_injection
        retained_earnings = cumulative_net_income
        total_equity = paid_in_capital + retained_earnings
        balance_check = total_assets - total_liabilities - total_equity

        free_cash_flow = safe_add(operating_cash_flow, investing_cash_flow)
        rows.append(
            {
                **base,
                "active_scenario": scenario_name,
                "construction_start_year": construction_start_year,
                "construction_flag": construction_flag,
                "owned_gpu": owned_gpu,
                "rented_gpu": rented_gpu,
                "owned_gpu_increment": owned_gpu_increment,
                "target_capacity_mw": target_capacity_mw,
                "peak_required_gpu": peak_required_gpu,
                "gpu_capex": gpu_capex,
                "gpu_infra_capex": gpu_infra_capex,
                "datacenter_construction_capex": datacenter_construction_capex,
                "office_server_capex": office_server_capex,
                "employee_laptops_capex": employee_laptops_capex,
                "executive_laptops_capex": executive_laptops_capex,
                "mfu_capex": mfu_capex,
                "meeting_rooms_capex": meeting_rooms_capex,
                "office_furniture_capex": office_furniture_capex,
                "total_office_capex": total_office_capex,
                "total_capex": total_capex,
                "depreciable_base": safe_add(gpu_infra_capex, datacenter_construction_capex, total_office_capex),
                "gpu_depreciation": gpu_depreciation,
                "datacenter_depreciation": datacenter_depreciation,
                "office_capex_depreciation": office_capex_depreciation,
                "ip_amortization": ip_amortization,
                "total_ppe_depreciation": total_ppe_depreciation,
                "total_ip_amortization": total_ip_amortization,
                "total_depreciation_and_amortization": total_depreciation_and_amortization,
                "total_depreciation": total_depreciation_and_amortization,
                "annual_depreciation": total_depreciation_and_amortization,
                "gpu_beginning_of_year": gpu_beginning_of_year,
                "gpu_end_of_year": gpu_end_of_year,
                "average_gpu": average_gpu,
                "average_owned_gpu": average_gpu,
                "it_load_mw": it_load_mw,
                "total_load_mw": total_load_mw,
                "electricity_kwh": electricity_kwh,
                "electricity_price_t": electricity_price_t,
                "electricity_price": electricity_price,
                "electricity_cost": electricity_cost,
                "maintenance_cost": maintenance_cost,
                "network_cost": network_cost,
                "land_rent": land_rent,
                "datacenter_opex": datacenter_opex,
                "other_opex": other_opex,
                "total_datacenter_opex": total_datacenter_opex,
                "rental_price_per_gpu_per_year": rental_price_per_gpu_per_year,
                "annual_gpu_rental_cost": annual_gpu_rental_cost,
                "monthly_fte": monthly_fte,
                "monthly_gross": monthly_gross,
                "monthly_bonus": monthly_bonus,
                "monthly_social": monthly_social,
                "monthly_cost_per_fte": monthly_cost_per_fte,
                "monthly_team_cost": monthly_team_cost,
                "total_core_team_fte": total_core_team_fte,
                "annual_core_team_cash_cost": annual_core_team_cash_cost,
                "capitalized_core_team_cost": capitalized_core_team_cost,
                "sga_monthly_fte": sga_monthly_fte,
                "total_sga_fte": total_sga_fte,
                "total_fte": total_fte,
                "payroll_gross": payroll_gross,
                "annual_bonus": annual_bonus,
                "social_contribution_sfr": social_contribution_sfr,
                "total_team_opex": total_team_opex,
                "annual_team_opex": annual_team_opex,
                "inflation_index_t": inflation_index_t,
                "annual_fixed_sga": annual_fixed_sga,
                "required_office_area_sqm": required_office_area_sqm,
                "rent_rub_per_sqm_per_month_t": rent_rub_per_sqm_per_month_t,
                "monthly_office_rent": monthly_office_rent,
                "annual_office_rent": annual_office_rent,
                "corporate_management": float("nan"),
                "hr": float("nan"),
                "finance_and_accounting": float("nan"),
                "admin": float("nan"),
                "shared_corporate_services": float("nan"),
                "office_rent": annual_office_rent,
                "total_sga": total_sga,
                "total_opex": total_opex,
                "workplace_ai_revenue": workplace_ai_revenue,
                "contact_center_ai_revenue": contact_center_ai_revenue,
                "total_revenue": total_revenue,
                "workplace_implied_price_per_1m_tokens": workplace_implied_price_per_1m_tokens,
                "contact_center_implied_price_per_1m_tokens": contact_center_implied_price_per_1m_tokens,
                "other_datacenter_opex": other_opex,
                "total_cogs": total_cogs,
                "gross_profit": gross_profit,
                "ebitda": ebitda,
                "ebit": ebit,
                "interest_expense": interest_expense,
                "ebt": ebt,
                "profit_tax": profit_tax,
                "net_income": net_income,
                "operating_cash_flow": operating_cash_flow,
                "office_capex": office_capex,
                "workplace_ai_ip_value": workplace_ai_ip_value,
                "contact_center_ai_ip_value": contact_center_ai_ip_value,
                "total_component_rub": total_component_rub if 'total_component_rub' in locals() else float("nan"),
                "total_intangible_assets": intangible_capex,
                "intangible_capex": intangible_capex,
                "investing_cash_flow": investing_cash_flow,
                "pre_financing_cash_flow": pre_financing_cash_flow,
                "financing_cash_flow": financing_cash_flow,
                "net_cash_flow": net_cash_flow,
                "opening_cash": opening_cash,
                "closing_cash": closing_cash,
                "minimum_cash_balance": minimum_cash_balance,
                "cumulative_cash": cumulative_cash,
                "free_cash_flow": free_cash_flow,
                "funding_need": funding_need,
                "equity_injection": equity_injection,
                "revolver_drawdown": revolver_drawdown,
                "revolver_repayment": revolver_repayment,
                "revolver_balance": revolver_balance,
                "closing_cash_after_funding": closing_cash_after_funding,
                "cash": cash,
                "gross_ppe": gross_ppe,
                "accumulated_depreciation": accumulated_depreciation,
                "net_ppe": net_ppe,
                "gross_intangible_assets": gross_intangible_assets,
                "accumulated_amortization": accumulated_amortization,
                "net_intangible_assets": net_intangible_assets,
                "total_assets": total_assets,
                "total_liabilities": total_liabilities,
                "paid_in_capital": paid_in_capital,
                "retained_earnings": retained_earnings,
                "total_equity": total_equity,
                "balance_check": balance_check,
                "roic": (ebit * (1.0 - float(profit_tax_rate)) / net_ppe) if net_ppe > 0 else None,
                "roe": (net_income / total_equity) if total_equity > 0 else None,
                "roa": (net_income / total_assets) if total_assets > 0 else None,
                "debt_to_equity": (revolver_balance / total_equity) if total_equity > 0 else None,
                "net_debt": revolver_balance - cash,
                "net_debt_to_ebitda": ((revolver_balance - cash) / ebitda) if ebitda and ebitda > 0 else None,
                "interest_coverage": (ebit / interest_expense) if interest_expense and interest_expense > 0 else None,
            }
        )

        prev_owned_gpu = owned_gpu
        prev_closing_cash = closing_cash
        cumulative_cash_prev = cumulative_cash
        prev_revolver_balance = revolver_balance

    discount_rate = as_float((((ass.get("investment_metrics", {}) or {}).get("discount_rate", {}) or {}).get("value", {}) or {}).get(years[0]))
    discount_rate = 0.20 if discount_rate is None else discount_rate
    dcf_rows, inv_metrics = build_dcf_metrics(rows, discount_rate)
    npv_value = inv_metrics.get("npv")
    for i, row in enumerate(rows):
        row["free_cash_flow"] = dcf_rows[i].get("free_cash_flow")
        row["npv"] = npv_value
    return rows




def compute_irr(cash_flows: list[float], tol: float = 1e-7, max_iter: int = 200) -> float | None:
    if not cash_flows or not any(cf > 0 for cf in cash_flows) or not any(cf < 0 for cf in cash_flows):
        return None
    def npv(rate: float) -> float:
        return sum(cf / ((1.0 + rate) ** idx) for idx, cf in enumerate(cash_flows))
    low, high = -0.9999, 10.0
    f_low, f_high = npv(low), npv(high)
    if math.isnan(f_low) or math.isnan(f_high) or f_low * f_high > 0:
        return None
    for _ in range(max_iter):
        mid = (low + high) / 2.0
        f_mid = npv(mid)
        if abs(f_mid) < tol:
            return mid
        if f_low * f_mid <= 0:
            high, f_high = mid, f_mid
        else:
            low, f_low = mid, f_mid
    return (low + high) / 2.0


def build_dcf_metrics(rows: list[dict[str, Any]], discount_rate: float) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    dcf_rows: list[dict[str, Any]] = []
    cumulative_discounted = 0.0
    for idx, row in enumerate(rows):
        free_cf = safe_add(as_float(row.get("operating_cash_flow")), as_float(row.get("investing_cash_flow")))
        # Year index convention: 2026 = 0, 2027 = 1, ...
        discount_factor = 1.0 / ((1.0 + discount_rate) ** idx)
        discounted_fcf = safe_mul(free_cf, discount_factor)
        cumulative_discounted = safe_add(cumulative_discounted, discounted_fcf)
        dcf_rows.append({**row, "free_cash_flow": free_cf, "discount_rate": discount_rate, "discount_factor": discount_factor, "discounted_fcf": discounted_fcf, "cumulative_discounted_fcf": cumulative_discounted})

    discounted_vals = [as_float(r.get("discounted_fcf")) or 0.0 for r in dcf_rows]
    fcf_vals = [as_float(r.get("free_cash_flow")) or 0.0 for r in dcf_rows]
    npv_val = sum(discounted_vals)
    irr_val = compute_irr(fcf_vals)
    simple_payback = next((str(int(r["year"])) for r in dcf_rows if (as_float(r.get("cumulative_cash")) or 0.0) > 0), "Not reached")
    discounted_payback = next((str(int(r["year"])) for r in dcf_rows if (as_float(r.get("cumulative_discounted_fcf")) or 0.0) > 0), "Not reached")
    metrics = {"npv": npv_val, "irr": irr_val, "simple_payback": simple_payback, "discounted_payback": discounted_payback}
    return dcf_rows, metrics


def build_metric_store(rows: list[dict[str, Any]], assumptions: dict[str, Any]) -> tuple[list[int], dict[str, dict[int, Any]], dict[str, Any]]:
    years = [int(r["year"]) for r in rows]
    discount_rate = as_float((((assumptions.get("investment_metrics", {}) or {}).get("discount_rate", {}) or {}).get("value", {}) or {}).get(years[0]))
    discount_rate = 0.20 if discount_rate is None else discount_rate
    dcf_rows, inv_metrics = build_dcf_metrics(rows, discount_rate)
    metric_store: dict[str, dict[int, Any]] = {}
    for row in rows:
        year = int(row["year"])
        ext = dict(row)
        ext["automated_interactions_per_day"] = row.get("automated_interactions")
        ext["tangible_capex"] = safe_add(as_float(row.get("gpu_infra_capex")), as_float(row.get("datacenter_construction_capex")), as_float(row.get("office_capex")))
        ext["pre_financing_cash_flow"] = safe_add(as_float(row.get("operating_cash_flow")), as_float(row.get("investing_cash_flow")))
        for k, v in ext.items():
            metric_store.setdefault(k, {})[year] = v
    for d in dcf_rows:
        y = int(d["year"])
        for k in ("free_cash_flow", "discount_rate", "discount_factor", "discounted_fcf", "cumulative_discounted_fcf"):
            metric_store.setdefault(k, {})[y] = d.get(k)
    for k, v in inv_metrics.items():
        metric_store.setdefault(k, {})[years[0]] = v
    return years, metric_store, inv_metrics


def run_model(
    assumptions: dict[str, Any],
    weighted_throughput_multiplier: float = 1.0,
    contribution_margin_multiplier: float = 1.0,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    ass_copy = copy.deepcopy(assumptions)

    throughput_cfg = ((ass_copy.get("compute_model", {}) or {}).get("throughput_per_gpu", {}))
    for model_name, value in list(throughput_cfg.items()):
        fv = as_float(value)
        if fv is not None:
            throughput_cfg[model_name] = fv * weighted_throughput_multiplier

    revenue_cfg = ass_copy.get("revenue", {}) if isinstance(ass_copy.get("revenue"), dict) else {}
    active_revenue_scenario = str(revenue_cfg.get("active_scenario", "base"))
    target_margin_cfg = revenue_cfg.get("target_contribution_margin", {})
    if isinstance(target_margin_cfg, dict) and active_revenue_scenario in target_margin_cfg:
        scenario_margin_map = to_year_map(target_margin_cfg.get(active_revenue_scenario))
        adjusted_margin_map: dict[int, float] = {}
        for y, m in scenario_margin_map.items():
            mv = as_float(m)
            if mv is None:
                continue
            adjusted_margin_map[y] = max(min(mv * contribution_margin_multiplier, 0.99), 0.0)
        target_margin_cfg[active_revenue_scenario] = adjusted_margin_map

    rows = calculate(ass_copy)
    base_year = int(rows[0]["year"])
    discount_rate = as_float((((ass_copy.get("investment_metrics", {}) or {}).get("discount_rate", {}) or {}).get("value", {}) or {}).get(base_year))
    discount_rate = 0.20 if discount_rate is None else discount_rate
    _, inv_metrics = build_dcf_metrics(rows, discount_rate)
    return rows, inv_metrics

def build_sensitivity_matrix(assumptions: dict[str, Any], base_rows: list[dict[str, Any]]) -> tuple[list[float], list[float], dict[tuple[float, float], Any]]:
    inv = assumptions.get("investment_metrics", {}) if isinstance(assumptions.get("investment_metrics"), dict) else {}
    sa = inv.get("sensitivity_analysis", {}) if isinstance(inv.get("sensitivity_analysis"), dict) else {}
    table_cfg = (((sa.get("tables", {}) or {}).get("npv_weighted_throughput_vs_contribution_margin")) or {})
    rf = table_cfg.get("row_factor", {}) if isinstance(table_cfg.get("row_factor"), dict) else {}
    cf = table_cfg.get("column_factor", {}) if isinstance(table_cfg.get("column_factor"), dict) else {}
    def make_range(cfg: dict[str, Any], default: list[float]) -> list[float]:
        mn, mx, st = as_float(cfg.get("min_multiplier")), as_float(cfg.get("max_multiplier")), as_float(cfg.get("step"))
        if mn is None or mx is None or st is None or st <= 0:
            return default
        out, v = [], mn
        while v <= mx + 1e-9:
            out.append(round(v, 4))
            v += st
        return out or default
    wt = make_range(rf, [1.0])
    cm = make_range(cf, [1.0])
    matrix: dict[tuple[float, float], Any] = {}
    for w in wt:
        for c in cm:
            try:
                _, mm = run_model(
                    assumptions,
                    weighted_throughput_multiplier=w,
                    contribution_margin_multiplier=c,
                )
                matrix[(w, c)] = mm.get("npv")
            except Exception:
                matrix[(w, c)] = None
                print(f"WARNING: sensitivity cell unavailable: throughput={w:.2f}, cm={c:.2f}", file=sys.stderr)
    return wt, cm, matrix


def build_scenario_comparison(assumptions: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for sc in ("build_own_dc", "rent_gpu_only", "hybrid"):
        ass_copy = copy.deepcopy(assumptions)
        capex_sc = ((ass_copy.get("capex", {}) or {}).get("strategy_scenarios", {}))
        if isinstance(capex_sc, dict):
            capex_sc["active_scenario"] = sc
        _, metrics = run_model(ass_copy)
        out[sc] = {
            "npv": metrics.get("npv"),
            "irr": metrics.get("irr"),
            "simple_payback": metrics.get("simple_payback"),
            "discounted_payback": metrics.get("discounted_payback"),
        }
    return out

def write_csv(rows: list[dict[str, Any]], assumptions: dict[str, Any], output: Path) -> None:
    years, metric_store, _ = build_metric_store(rows, assumptions)
    report_tables_raw = (((assumptions.get("report_output", {}) or {}).get("tables")) or {})
    report_tables = list(report_tables_raw.values()) if isinstance(report_tables_raw, dict) else report_tables_raw
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="") as fh:
        fieldnames = ["table", "metric"] + [str(y) for y in years]
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        scenario_cmp = build_scenario_comparison(assumptions)
        for table in report_tables:
            if not isinstance(table, dict):
                continue
            title = table.get("title", "Untitled")
            if isinstance(title, str) and title.lower().startswith("sensitivity analysis"):
                continue
            if table.get("layout") == "matrix" and title == "Scenario Comparison":
                for row_name in table.get("rows", []):
                    rec = {"table": title, "metric": row_name}
                    values = scenario_cmp.get(str(row_name), {})
                    cols = table.get("columns", [])
                    for i, y in enumerate(years):
                        rec[str(y)] = values.get(cols[i]) if i < len(cols) else ""
                    writer.writerow(rec)
                continue
            for metric in table.get("rows", []):
                if not isinstance(metric, str):
                    continue
                if metric == "sensitivity_analysis" or title.lower().startswith("sensitivity analysis"):
                    continue
                rec = {"table": title, "metric": metric}
                vals = metric_store.get(metric)
                if vals is None:
                    print(f"WARNING: report_output metric not found: {metric}", file=sys.stderr)
                for y in years:
                    v = vals.get(y) if vals else None
                    rec[str(y)] = "N/A" if v is None or (isinstance(v, float) and math.isnan(v)) else v
                writer.writerow(rec)
        wt, cm, matrix = build_sensitivity_matrix(assumptions, rows)
        for w in wt:
            rec = {"table": "Sensitivity Analysis — NPV", "metric": f"weighted_throughput_multiplier={w:.2f}"}
            for idx, y in enumerate(years):
                if idx < len(cm):
                    v = matrix.get((w, cm[idx]))
                    rec[str(y)] = "N/A" if v is None else v
                else:
                    rec[str(y)] = ""
            writer.writerow(rec)

def build_html(rows: list[dict[str, Any]], assumptions: dict[str, Any]) -> str:
    years, metric_store, _ = build_metric_store(rows, assumptions)
    report_tables_raw = (((assumptions.get("report_output", {}) or {}).get("tables")) or {})
    report_tables = list(report_tables_raw.values()) if isinstance(report_tables_raw, dict) else report_tables_raw
    hy = "".join(f"<th class='yr'>{y}</th>" for y in years)
    tables_by_title: dict[str, str] = {}
    scenario_cmp = build_scenario_comparison(assumptions)

    def render_value(v: Any) -> str:
        if v is None or (isinstance(v, float) and math.isnan(v)):
            return "<span class='na'>N/A</span>"
        fv = as_float(v)
        if fv is None:
            return str(v)
        cls = "neg" if fv < 0 else ("zero" if abs(fv) < 1e-12 else "")
        return f"<span class='{cls}'>{fmt_num(fv,2)}</span>"

    def compact_num(v: float) -> str:
        sign = "-" if v < 0 else ""
        x = abs(v)
        if x >= 1_000_000_000:
            return f"{sign}{x/1_000_000_000:.1f} bn"
        if x >= 1_000_000:
            return f"{sign}{x/1_000_000:.1f} m"
        if x >= 1_000:
            return f"{sign}{x/1_000:.1f} k"
        return f"{v:.0f}"

    def chart_series(metric: str) -> list[float]:
        out = []
        for y in years:
            v = as_float(metric_store.get(metric, {}).get(y))
            out.append(0.0 if v is None or math.isnan(v) else float(v))
        return out

    def render_grouped_bar_chart(title: str, desc: str, series: list[tuple[str, str, list[float]]]) -> str:
        w, h, ml, mb, mt = 860, 260, 56, 36, 20
        pw, ph = w - ml - 16, h - mb - mt
        vals = [v for _, _, arr in series for v in arr] or [0.0]
        ymin, ymax = min(vals), max(vals)
        if ymin == ymax:
            ymax = ymin + 1.0
        if ymin > 0:
            ymin = 0.0
        if ymax < 0:
            ymax = 0.0
        def py(v: float) -> float:
            return mt + (ymax - v) / (ymax - ymin) * ph
        zero_y = py(0.0)
        gx = pw / max(len(years), 1)
        bar_w = gx * 0.7 / max(len(series), 1)
        bars = []
        for i, y in enumerate(years):
            x0 = ml + i * gx + gx * 0.15
            for j, (_, color, arr) in enumerate(series):
                v = arr[i]
                x = x0 + j * bar_w
                yv = py(v)
                bars.append(f"<rect x='{x:.1f}' y='{min(yv,zero_y):.1f}' width='{bar_w-2:.1f}' height='{abs(zero_y-yv):.1f}' fill='{color}' rx='2'/>")
            bars.append(f"<text x='{ml+i*gx+gx/2:.1f}' y='{h-10}' text-anchor='middle' class='axis'>{y}</text>")
        legend = "".join(f"<span class='lg'><i style='background:{c}'></i>{n}</span>" for n, c, _ in series)
        return f"<div class='chart card'><h3>{title}</h3><div class='sub'>{desc}</div><svg viewBox='0 0 {w} {h}'><line x1='{ml}' y1='{zero_y:.1f}' x2='{w-10}' y2='{zero_y:.1f}' class='grid'/>{''.join(bars)}</svg><div class='legend'>{legend}</div></div>"

    def render_line_chart(title: str, desc: str, series: list[tuple[str, str, list[float]]]) -> str:
        w, h, ml, mb, mt = 860, 260, 56, 36, 20
        pw, ph = w - ml - 16, h - mb - mt
        vals = [v for _, _, arr in series for v in arr] or [0.0]
        ymin, ymax = min(vals), max(vals)
        if ymin == ymax:
            ymax = ymin + 1.0
        if ymin > 0:
            ymin = 0.0
        if ymax < 0:
            ymax = 0.0
        def py(v: float) -> float:
            return mt + (ymax - v) / (ymax - ymin) * ph
        gx = pw / max(len(years)-1, 1)
        lines = []
        for name, color, arr in series:
            pts = " ".join(f"{ml+i*gx:.1f},{py(v):.1f}" for i, v in enumerate(arr))
            lines.append(f"<polyline fill='none' stroke='{color}' stroke-width='2.2' points='{pts}'/>")
        xlabels = "".join(f"<text x='{ml+i*gx:.1f}' y='{h-10}' text-anchor='middle' class='axis'>{y}</text>" for i, y in enumerate(years))
        legend = "".join(f"<span class='lg'><i style='background:{c}'></i>{n}</span>" for n, c, _ in series)
        return f"<div class='chart card'><h3>{title}</h3><div class='sub'>{desc}</div><svg viewBox='0 0 {w} {h}'><line x1='{ml}' y1='{py(0):.1f}' x2='{w-10}' y2='{py(0):.1f}' class='grid'/>{''.join(lines)}{xlabels}</svg><div class='legend'>{legend}</div></div>"

    for table in report_tables:
        if not isinstance(table, dict):
            continue
        title = table.get("title", "Untitled")
        if isinstance(title, str) and title.lower().startswith("sensitivity analysis"):
            continue
        if table.get("layout") == "matrix" and title == "Scenario Comparison":
            cols = [str(c) for c in table.get("columns", [])]
            head = "".join(f"<th>{c}</th>" for c in cols)
            body_rows: list[str] = []
            for row_name in table.get("rows", []):
                vals = scenario_cmp.get(str(row_name), {})
                cells = []
                for c in cols:
                    v = vals.get(c)
                    fv = as_float(v)
                    if v is None or (isinstance(v, float) and math.isnan(v)):
                        cells.append("<td>N/A</td>")
                    elif fv is None:
                        cells.append(f"<td>{v}</td>")
                    else:
                        cells.append(f"<td>{fmt_num(fv,2)}</td>")
                body_rows.append(f"<tr><td>{row_name}</td>{''.join(cells)}</tr>")
            tables_by_title[title] = f"<div class='card'><h3>{title}</h3><table><thead><tr><th>Scenario</th>{head}</tr></thead><tbody>{''.join(body_rows)}</tbody></table></div>"
            continue
        body = []
        for metric in table.get("rows", []):
            if not isinstance(metric, str):
                continue
            if metric == "sensitivity_analysis" or title.lower().startswith("sensitivity analysis"):
                continue
            vals = metric_store.get(metric)
            if vals is None:
                print(f"WARNING: report_output metric not found: {metric}", file=sys.stderr)
            cells=[]
            for y in years:
                v = vals.get(y) if vals else None
                cells.append(f"<td class='num'>{render_value(v)}</td>")
            body.append(f"<tr><td class='metric'>{metric}</td>{''.join(cells)}</tr>")
        tables_by_title[title] = f"<div class='card'><h3>{title}</h3><table><thead><tr><th>Metric</th>{hy}</tr></thead><tbody>{''.join(body)}</tbody></table></div>"
    wt,cm,matrix = build_sensitivity_matrix(assumptions, rows)
    scol = ''.join(f'<th>{c:.2f}</th>' for c in cm)
    sbody=[]
    npv_vals = [float(v) for v in matrix.values() if v is not None]
    npv_min = min(npv_vals) if npv_vals else 0.0
    npv_max = max(npv_vals) if npv_vals else 1.0
    for w in wt:
        cells = []
        for c in cm:
            v = matrix.get((w, c))
            if v is None:
                cells.append("<td><span class='na'>N/A</span></td>")
                continue
            fv = float(v)
            t = 0.5 if npv_max == npv_min else (fv - npv_min) / (npv_max - npv_min)
            if fv >= 0:
                bg = f"rgba(22,163,74,{0.15 + 0.45*t:.3f})"
            else:
                bg = f"rgba(220,38,38,{0.15 + 0.55*(1-t):.3f})"
            base_cls = " base-cell" if abs(w - 1.0) < 1e-9 and abs(c - 1.0) < 1e-9 else ""
            cells.append(f"<td class='num heat{base_cls}' style='background:{bg}'>{fmt_num(fv,2)}</td>")
        row = "".join(
            cells
        )
        sbody.append(f"<tr><td class='sticky'>{w:.2f}</td>{row}</tr>")
    sensitivity_html = f"<div class='card'><h3>Sensitivity Analysis — NPV</h3><div class='table-wrap'><table class='sensitivity'><thead><tr><th class='sticky'>weighted_throughput_multiplier</th>{scol}</tr></thead><tbody>{''.join(sbody)}</tbody></table></div></div>"
    tables_by_title["Sensitivity Analysis"] = sensitivity_html

    section_map = {
        "Operating Model": ["Token Load", "GPU Calculation", "Infrastructure Scenario"],
        "Investment Plan": ["CAPEX", "Datacenter Construction CAPEX", "Office CAPEX", "Intangible Assets", "Depreciation & Amortization"],
        "Operating Costs": ["Datacenter OPEX", "Team OPEX", "GPU Rental OPEX", "SG&A"],
        "Financial Statements": ["Revenue", "COGS", "P&L Summary", "Cash Flow Statement", "Funding", "Balance Sheet"],
        "Investment Case": ["DCF", "Investment Metrics", "Return Metrics", "Scenario Comparison", "Sensitivity Analysis"],
    }
    sections_html = []
    for sec, names in section_map.items():
        blocks = "".join(tables_by_title.get(n, "") for n in names if n in tables_by_title)
        if blocks:
            sections_html.append(f"<section><h2>{sec}</h2>{blocks}</section>")

    latest = rows[-1]
    kpis = [
        ("NPV", metric_store.get("npv", {}).get(years[0])),
        ("IRR", metric_store.get("irr", {}).get(years[0])),
        ("Revenue 2030", metric_store.get("total_revenue", {}).get(years[-1])),
        ("EBITDA 2030", metric_store.get("ebitda", {}).get(years[-1])),
        ("Net Income 2030", metric_store.get("net_income", {}).get(years[-1])),
        ("Total CAPEX", sum((as_float(r.get("total_capex")) or 0.0) for r in rows)),
        ("Peak Required GPU", max((as_float(r.get("required_gpu")) or 0.0) for r in rows)),
        ("Revolver Balance 2030", metric_store.get("revolver_balance", {}).get(years[-1])),
        ("Payback", metric_store.get("simple_payback", {}).get(years[0])),
    ]
    kpi_html = "".join(f"<div class='kpi'><div class='k'>{k}</div><div class='v'>{render_value(v)}</div></div>" for k, v in kpis)
    charts_html = "".join(
        [
            render_line_chart(
                "Revenue / EBITDA / Net Income",
                "Profitability trajectory by year.",
                [
                    ("Revenue", "var(--c-blue)", chart_series("total_revenue")),
                    ("EBITDA", "var(--c-green)", chart_series("ebitda")),
                    ("Net Income", "var(--c-purple)", chart_series("net_income")),
                ],
            ),
            render_grouped_bar_chart(
                "CAPEX Breakdown",
                "Investment phasing by CAPEX component.",
                [
                    ("GPU Infra CAPEX", "var(--c-orange)", chart_series("gpu_infra_capex")),
                    ("DC Construction", "var(--c-red)", chart_series("datacenter_construction_capex")),
                    ("Office CAPEX", "var(--c-blue)", chart_series("office_capex")),
                    ("Intangible CAPEX", "var(--c-purple)", chart_series("intangible_capex")),
                ],
            ),
            render_grouped_bar_chart(
                "Cash Flow",
                "Operating, investing and free cash flow (pre-financing).",
                [
                    ("Operating CF", "var(--c-green)", chart_series("operating_cash_flow")),
                    ("Investing CF", "var(--c-red)", chart_series("investing_cash_flow")),
                    ("Free CF", "var(--c-blue)", chart_series("free_cash_flow")),
                ],
            ),
            render_line_chart(
                "GPU Infrastructure",
                "Required vs owned/rented GPU transition.",
                [
                    ("Required", "var(--c-blue)", chart_series("required_gpu")),
                    ("Owned", "var(--c-green)", chart_series("owned_gpu")),
                    ("Rented", "var(--c-orange)", chart_series("rented_gpu")),
                ],
            ),
            render_grouped_bar_chart(
                "Debt and Cash",
                "Funding structure and deleveraging profile.",
                [
                    ("Revolver Balance", "var(--c-purple)", chart_series("revolver_balance")),
                    ("Cash", "var(--c-green)", chart_series("cash")),
                ],
            ),
        ]
    )
    active_scenario = latest.get("active_scenario", "N/A")
    dt = __import__("datetime")
    ts = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    return f"""<!doctype html><html lang='en'><head><meta charset='utf-8'><title>GPS Finmodel Report</title><style>
:root{{--c-blue:#2563eb;--c-green:#16a34a;--c-red:#dc2626;--c-orange:#ea580c;--c-purple:#7c3aed;}}
body{{margin:0;background:#f6f8fb;color:#1f2937;font:14px/1.4 -apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Arial,sans-serif}}
.nav{{position:sticky;top:0;z-index:20;background:#fff;border-bottom:1px solid #e5e7eb;padding:10px 24px}}
.container{{max-width:1280px;margin:0 auto;padding:20px}}
h1{{margin:0;font-size:28px}} .sub{{color:#6b7280;margin-top:4px}}
.meta{{margin-top:8px;color:#4b5563;font-size:12px}}
section h2{{margin:24px 0 12px;font-size:18px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:12px}}
.controls{{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:10px;margin-top:12px}}
.ctrl{{display:flex;flex-direction:column;gap:4px}} .ctrl label{{font-size:12px;color:#6b7280}}
.ctrl input,.ctrl select{{padding:7px 8px;border:1px solid #d1d5db;border-radius:8px;background:#f9fafb;color:#6b7280}}
.ctrl input:disabled,.ctrl select:disabled{{opacity:.75;cursor:not-allowed}}
.note{{margin-top:8px;font-size:12px;color:#6b7280}}
.kpi{{background:#fff;border:1px solid #e5e7eb;border-radius:10px;padding:12px}}
.kpi .k{{font-size:12px;color:#6b7280}} .kpi .v{{font-size:18px;font-weight:600;margin-top:6px}}
.card{{background:#fff;border:1px solid #e5e7eb;border-radius:10px;padding:10px 12px;margin-bottom:12px;box-shadow:0 1px 2px rgba(0,0,0,.03)}}
.card h3{{margin:4px 0 10px;font-size:15px}}
table{{width:100%;border-collapse:collapse;font-size:12px}} th,td{{padding:6px 8px;border-bottom:1px solid #edf1f5}} th{{background:#f8fafc;color:#374151}}
th.yr{{text-align:center}} td.metric,th:first-child{{text-align:left}} td.num{{text-align:right}}
.neg{{color:#b91c1c}} .zero{{color:#9ca3af}} .na{{color:#9ca3af}} .kpi .v span{{color:inherit}}
.table-wrap{{overflow:auto;max-width:100%}} .sticky{{position:sticky;left:0;background:#f8fafc}}
.chart svg{{width:100%;height:auto}} .grid{{stroke:#d1d5db;stroke-width:1}} .axis{{fill:#6b7280;font-size:11px}}
.legend{{display:flex;gap:10px;flex-wrap:wrap;margin-top:8px}} .lg{{font-size:12px;color:#4b5563}} .lg i{{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:4px;vertical-align:middle}}
.base-cell{{outline:2px solid #111827;outline-offset:-2px}}
</style></head><body><div class='nav'><strong>GPS Finmodel Report</strong></div><div class='container'>
<header><h1>GPS Finmodel Report</h1><div class='sub'>2026–2030 financial model</div><div class='meta'>Active scenario: {active_scenario} · Generated: {ts}</div></header>
<div class='card'>
  <h3>Controls</h3>
  <div class='controls'>
    <div class='ctrl'><label>Revenue scenario</label><select disabled><option>base</option></select></div>
    <div class='ctrl'><label>Infrastructure scenario</label><select disabled><option>build_own_dc</option><option>rent_gpu_only</option><option selected>hybrid</option></select></div>
    <div class='ctrl'><label>Construction start year</label><input type='number' value='2028' disabled/></div>
    <div class='ctrl'><label>Funding scenario</label><select disabled><option>equity_only</option><option>revolver_only</option><option selected>mix</option></select></div>
    <div class='ctrl'><label>Funding mix (equity %)</label><input value='50' disabled/></div>
    <div class='ctrl'><label>Funding mix (revolver %)</label><input value='50' disabled/></div>
    <div class='ctrl'><label>Discount rate</label><input type='number' value='30' disabled/></div>
  </div>
  <div class='note'>Interactive scenario switching is not enabled yet. Current report shows the Python-calculated base case.</div>
  <div class='note'>Discount rate recalculation will be enabled in a later version.</div>
</div>
<section><h2>Executive Summary</h2><div class='grid'>{kpi_html}</div></section>
<section><h2>Charts Overview</h2><div class='grid charts'>{charts_html}</div></section>
{''.join(sections_html)}
</div></body></html>"""

def write_html(rows: list[dict[str, Any]], assumptions: dict[str, Any], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(build_html(rows, assumptions), encoding="utf-8")


def main() -> None:
    assumptions = load_yaml(Path("assumptions.yaml"))
    for section in ("usage_assumptions", "token_load_model"):
        if section not in assumptions:
            raise KeyError(f"В assumptions.yaml отсутствует обязательная секция: {section}")

    rows = calculate(assumptions)
    write_csv(rows, assumptions, OUT_CSV)
    write_html(rows, assumptions, OUT_HTML)

    print("year | total_annual_tokens | required_gpu | total_capex | total_opex")
    print("-" * 90)
    for r in rows:
        print(
            f"{r['year']} | {fmt_num(r['total_annual_tokens'],0)} | {fmt_num(r['required_gpu'],0)} | "
            f"{fmt_num(r['total_capex'],2)} | {fmt_num(r['total_opex'],2)}"
        )
    print(f"\nCSV: {OUT_CSV}")
    print(f"HTML: {OUT_HTML}")


if __name__ == "__main__":
    main()
