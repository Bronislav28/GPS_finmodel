#!/usr/bin/env python3
"""Расчет token load -> GPU -> CAPEX -> OPEX по assumptions.yaml."""

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
    return {int(k): v for k, v in src.items()}


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
    ("GPU Calculation", ["weighted_throughput", "tokens_per_second", "required_gpu", "required_gpu_increment"]),
    ("CAPEX", ["gpu_capex", "total_capex", "annual_depreciation"]),
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
    ("Total OPEX", ["total_datacenter_opex", "annual_team_opex", "total_opex"]),
    ("Summary", ["workplace_token_share", "contact_center_token_share", "required_gpu", "total_capex", "total_opex"]),
]


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


def calculate(ass: dict[str, Any]) -> list[dict[str, Any]]:
    years = ass.get("years") or TARGET_YEARS
    years = [int(y) for y in years]

    usage = ass["usage_assumptions"]
    token_model = ass["token_load_model"]
    compute = ass["compute_model"]
    capex = ass.get("capex", {})

    # OPEX-блоки: поддержка как top-level datacenter/team, так и legacy opex.datacenter/team
    opex_root = ass.get("opex", {}) if isinstance(ass.get("opex"), dict) else {}
    datacenter = ass.get("datacenter", opex_root.get("datacenter", {}))
    team = ass.get("team", opex_root.get("team", {}))
    drivers = datacenter.get("drivers", {}) if isinstance(datacenter.get("drivers"), dict) else {}

    wp_usage = usage["Workplace.ai"]
    cc_usage = usage["Contact_Center.ai"]

    wp_activation = to_year_map(wp_usage.get("activation_rate"))
    wp_tokens_per_user = to_year_map(token_model["Workplace.ai"].get("tokens_per_active_user_per_day"))
    cc_automation = to_year_map(cc_usage.get("automation_rate"))

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
    working_hours = float(compute["infra"]["working_hours_per_day"])
    peak_factor = float(compute["infra"].get("peak_factor", 1.0))

    gpu_unit_cost = as_float(capex.get("gpu", {}).get("unit_cost"))
    infra_multiplier = as_float(capex.get("infra_multiplier", {}).get("value"))
    useful_life = int(capex.get("depreciation", {}).get("useful_life_years", capex.get("gpu", {}).get("useful_life_years", 5)))
    useful_life = max(useful_life, 1)

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
    annual_growth_cfg = electricity_price_cfg.get("annual_growth")
    annual_growth_map: dict[int, float] = {}
    if isinstance(annual_growth_cfg, dict) and "value" in annual_growth_cfg:
        growth_val = as_float(annual_growth_cfg.get("value"))
        if growth_val is not None:
            annual_growth_map = {y: growth_val for y in years}
    elif isinstance(annual_growth_cfg, dict):
        for y_key, y_val in annual_growth_cfg.items():
            try:
                y_int = int(y_key)
            except (TypeError, ValueError):
                continue
            if isinstance(y_val, dict) and "value" in y_val:
                growth = as_float(y_val.get("value"))
            else:
                growth = as_float(y_val)
            annual_growth_map[y_int] = 0.0 if growth is None else float(growth)
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

    seconds_per_year = working_days * working_hours * 3600.0
    if seconds_per_year <= 0:
        raise ValueError("working_days_per_year * working_hours_per_day * 3600 должно быть > 0")

    rows: list[dict[str, Any]] = []
    prev_required_gpu = 0
    total_capex_history: list[float] = []
    prev_electricity_price: float | None = None
    salary_growth_factor = 1.0
    warned_missing_salary: set[tuple[str, ...]] = set()

    for year in years:
        # Token Load
        active_users = safe_mul(as_float(wp_usage.get("total_employees")), as_float(wp_activation.get(year)))
        wp_daily_tokens = safe_mul(active_users, as_float(wp_tokens_per_user.get(year)))
        wp_annual_tokens = safe_mul(wp_daily_tokens, working_days)

        automated_interactions = safe_mul(as_float(cc_usage.get("interactions_per_day")), as_float(cc_automation.get(year)))
        cc_daily_tokens = safe_mul(automated_interactions, as_float(cc_usage.get("tokens_per_interaction")))
        cc_annual_tokens = safe_mul(cc_daily_tokens, calendar_days)

        total_daily_tokens = safe_add(wp_daily_tokens, cc_daily_tokens)
        total_annual_tokens = safe_add(wp_annual_tokens, cc_annual_tokens)

        if is_nan(total_annual_tokens) or total_annual_tokens == 0:
            wp_share = float("nan")
            cc_share = float("nan")
        else:
            wp_share = float(wp_annual_tokens) / float(total_annual_tokens)
            cc_share = float(cc_annual_tokens) / float(total_annual_tokens)

        # GPU
        mix = {model: float(share) for model, share in model_mix_by_year[year].items()}
        weighted_tp = harmonic_weighted_throughput(mix, throughput)

        utilization = as_float(util_by_year.get(year))
        if is_nan(utilization) or float(utilization) <= 0:
            raise ValueError(f"compute_model.infra.utilization[{year}] должен быть > 0")

        tokens_per_second = float(total_annual_tokens) / seconds_per_year
        required_gpu_raw = tokens_per_second / (weighted_tp * float(utilization)) * peak_factor
        required_gpu = int(math.ceil(required_gpu_raw))

        required_gpu_increment = required_gpu if year == years[0] else max(required_gpu - prev_required_gpu, 0)

        # CAPEX
        if gpu_unit_cost is None or infra_multiplier is None:
            gpu_capex = float("nan")
            total_capex = float("nan")
        else:
            gpu_capex = required_gpu_increment * gpu_unit_cost
            total_capex = gpu_capex * infra_multiplier

        total_capex_history.append(total_capex)
        window = total_capex_history[-useful_life:]
        annual_depreciation = float("nan") if any(math.isnan(v) for v in window) else sum(window) / useful_life

        # Datacenter OPEX
        gpu_beginning_of_year = float(prev_required_gpu)
        gpu_end_of_year = float(required_gpu)
        average_gpu = (gpu_beginning_of_year + gpu_end_of_year) / 2.0

        it_load_mw = safe_mul(average_gpu, gpu_power_kw, 1 / 1000)
        total_load_mw = safe_mul(it_load_mw, pue)
        electricity_kwh = safe_mul(total_load_mw, 1000, operating_hours_per_day, calendar_days)

        if base_price_per_kwh is None:
            electricity_price_t = float("nan")
        elif year == years[0]:
            electricity_price_t = base_price_per_kwh
        else:
            growth_t = as_float(annual_growth_map.get(year, 0.0))
            if prev_electricity_price is None or is_nan(prev_electricity_price) or growth_t is None:
                electricity_price_t = float("nan")
            else:
                electricity_price_t = prev_electricity_price * (1 + growth_t)
        prev_electricity_price = electricity_price_t

        electricity_cost = safe_mul(electricity_kwh, electricity_price_t)
        maintenance_cost = safe_mul(total_capex, maintenance_pct)
        network_cost = safe_mul(total_load_mw, network_cost_per_mw)
        land_rent = safe_mul(total_load_mw, land_rent_per_mw)

        datacenter_opex = safe_add(electricity_cost, maintenance_cost, network_cost, land_rent)
        other_opex = safe_mul(datacenter_opex, other_opex_percent)
        total_datacenter_opex = safe_add(datacenter_opex, other_opex)

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

        total_opex = safe_add(total_datacenter_opex, annual_team_opex)

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
                "gpu_beginning_of_year": gpu_beginning_of_year,
                "gpu_end_of_year": gpu_end_of_year,
                "average_gpu": average_gpu,
                "it_load_mw": it_load_mw,
                "total_load_mw": total_load_mw,
                "electricity_kwh": electricity_kwh,
                "electricity_price_t": electricity_price_t,
                "electricity_cost": electricity_cost,
                "maintenance_cost": maintenance_cost,
                "network_cost": network_cost,
                "land_rent": land_rent,
                "datacenter_opex": datacenter_opex,
                "other_opex": other_opex,
                "total_datacenter_opex": total_datacenter_opex,
                "monthly_fte": monthly_fte,
                "monthly_gross": monthly_gross,
                "monthly_bonus": monthly_bonus,
                "monthly_social": monthly_social,
                "monthly_cost_per_fte": monthly_cost_per_fte,
                "monthly_team_cost": monthly_team_cost,
                "annual_team_opex": annual_team_opex,
                "total_opex": total_opex,
            }
        )

        prev_required_gpu = required_gpu

    return rows


def write_csv(rows: list[dict[str, Any]], output: Path) -> None:
    years = [int(r["year"]) for r in rows]
    blocks = build_report_blocks(rows, years)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="") as fh:
        fieldnames = ["Block", "Metric"] + [str(y) for y in years]
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for block in blocks:
            for wide_row in block["rows"]:
                out = {"Block": block["title"], "Metric": wide_row["Metric"]}
                for y in years:
                    out[str(y)] = wide_row[str(y)]
                writer.writerow(out)


def build_html(rows: list[dict[str, Any]]) -> str:
    years = [int(r["year"]) for r in rows]
    blocks = build_report_blocks(rows, years)

    def format_cell(metric: str, value: Any) -> str:
        val = as_float(value)
        if metric.endswith("_share"):
            return fmt_ratio(val)
        if metric in {"required_gpu", "required_gpu_increment"}:
            return fmt_num(val, 0)
        return fmt_num(val, 2)

    block_tables = []
    for block in blocks:
        body_rows = []
        for w_row in block["rows"]:
            cells = "".join(f"<td>{format_cell(w_row['Metric'], w_row[str(y)])}</td>" for y in years)
            body_rows.append(f"<tr><td>{w_row['Metric']}</td>{cells}</tr>")
        header_years = "".join(f"<th>{y}</th>" for y in years)
        table_html = (
            f"<h2>{block['title']}</h2>"
            f"<table><thead><tr><th>Metric</th>{header_years}</tr></thead>"
            f"<tbody>{''.join(body_rows)}</tbody></table>"
        )
        block_tables.append(table_html)

    return f"""<!doctype html>
<html lang=\"ru\"><head><meta charset=\"utf-8\"><title>GPS Finmodel</title>
<style>
body{{font-family:Arial,sans-serif;margin:24px;color:#1f2937}}
table{{border-collapse:collapse;width:100%;margin:10px 0 24px}}
th,td{{border:1px solid #ddd;padding:6px;text-align:right;font-size:13px}}
th:first-child,td:first-child{{text-align:center}}
thead{{background:#f3f4f6}} .note{{background:#f9fafb;border:1px solid #e5e7eb;padding:12px;border-radius:8px}}
</style></head><body>
<h1>GPS Finmodel Report (2026–2030)</h1>
<div class=\"note\"><b>Формулы:</b>
<ul>
<li>weighted_throughput = 1 / Σ(model_share / throughput_per_gpu)</li>
<li>required_gpu_increment = max(required_gpu_t - required_gpu_(t-1), 0), для 2026 = required_gpu</li>
<li>Datacenter OPEX: electricity + maintenance + network + land + other</li>
<li>Team OPEX: monthly_fte × (gross + bonus + social) × 12</li>
<li>Total OPEX = total_datacenter_opex + annual_team_opex</li>
</ul></div>
{''.join(block_tables)}
</body></html>"""


def write_html(rows: list[dict[str, Any]], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(build_html(rows), encoding="utf-8")


def main() -> None:
    assumptions = load_yaml(Path("assumptions.yaml"))
    for section in ("usage_assumptions", "token_load_model"):
        if section not in assumptions:
            raise KeyError(f"В assumptions.yaml отсутствует обязательная секция: {section}")

    rows = calculate(assumptions)
    write_csv(rows, OUT_CSV)
    write_html(rows, OUT_HTML)

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
