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
        ym = to_year_map(value)
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
    capex = ass.get("capex", {})

    # OPEX-блоки: поддержка как top-level datacenter/team, так и legacy opex.datacenter/team
    opex_root = ass.get("opex", {}) if isinstance(ass.get("opex"), dict) else {}
    datacenter = ass.get("datacenter", opex_root.get("datacenter", {}))
    team = ass.get("team", opex_root.get("team", {}))

    wp_usage = usage["Workplace.ai"]
    cc_usage = usage["Contact_Center.ai"]

    wp_activation = to_year_map(wp_usage.get("activation_rate"))
    wp_tokens_per_user = to_year_map(token_model["Workplace.ai"].get("tokens_per_active_user_per_day"))
    cc_automation = to_year_map(cc_usage.get("automation_rate"))

    model_mix_by_year = to_year_map(compute.get("model_mix"))
    util_by_year = to_year_map(compute.get("infra", {}).get("utilization"))
    throughput = {name: float(v) for name, v in compute.get("throughput_per_gpu", {}).items()}

    working_days = float(token_model["time_assumptions"]["working_days_per_year"])
    calendar_days = float(token_model["time_assumptions"]["calendar_days_per_year"])
    working_hours = float(compute["infra"]["working_hours_per_day"])
    peak_factor = float(compute["infra"].get("peak_factor", 1.0))

    gpu_unit_cost = as_float(capex.get("gpu", {}).get("unit_cost"))
    infra_multiplier = as_float(capex.get("infra_multiplier", {}).get("value"))
    useful_life = int(capex.get("depreciation", {}).get("useful_life_years", capex.get("gpu", {}).get("useful_life_years", 5)))
    useful_life = max(useful_life, 1)

    # Datacenter OPEX assumptions
    gpu_power_kw = as_float(datacenter.get("gpu_power_kw"))
    pue = as_float(datacenter.get("pue"))
    operating_hours_per_day = as_float(datacenter.get("operating_hours_per_day", 24))
    base_price_per_kwh = as_float(datacenter.get("base_price_per_kwh"))
    annual_growth_map = to_year_map(datacenter.get("annual_growth"))
    maintenance_pct = as_float(datacenter.get("maintenance_percent_of_capex"))
    network_cost_per_mw = as_float(datacenter.get("network_cost_per_mw_per_year"))
    land_rent_per_mw = as_float(datacenter.get("land_rent_per_mw_per_year"))
    other_opex_percent = as_float(datacenter.get("other_opex_percent"))

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

        if year == years[0]:
            required_gpu_increment = required_gpu
        else:
            required_gpu_increment = max(required_gpu - prev_required_gpu, 0)

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
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def build_html(rows: list[dict[str, Any]]) -> str:
    token_rows = "\n".join(
        f"<tr><td>{r['year']}</td><td>{fmt_num(r['active_users'],0)}</td><td>{fmt_num(r['workplace_daily_tokens'],0)}</td>"
        f"<td>{fmt_num(r['workplace_annual_tokens'],0)}</td><td>{fmt_num(r['automated_interactions'],0)}</td>"
        f"<td>{fmt_num(r['contact_center_daily_tokens'],0)}</td><td>{fmt_num(r['contact_center_annual_tokens'],0)}</td>"
        f"<td>{fmt_num(r['total_daily_tokens'],0)}</td><td>{fmt_num(r['total_annual_tokens'],0)}</td></tr>"
        for r in rows
    )

    gpu_rows = "\n".join(
        f"<tr><td>{r['year']}</td><td>{fmt_num(r['weighted_throughput'],2)}</td><td>{fmt_num(r['tokens_per_second'],2)}</td>"
        f"<td>{fmt_num(r['required_gpu'],0)}</td><td>{fmt_num(r['required_gpu_increment'],0)}</td></tr>"
        for r in rows
    )

    capex_rows = "\n".join(
        f"<tr><td>{r['year']}</td><td>{fmt_num(r['gpu_capex'],2)}</td><td>{fmt_num(r['total_capex'],2)}</td>"
        f"<td>{fmt_num(r['annual_depreciation'],2)}</td></tr>"
        for r in rows
    )

    dc_rows = "\n".join(
        f"<tr><td>{r['year']}</td><td>{fmt_num(r['average_gpu'],2)}</td><td>{fmt_num(r['it_load_mw'],4)}</td>"
        f"<td>{fmt_num(r['total_load_mw'],4)}</td><td>{fmt_num(r['electricity_kwh'],0)}</td><td>{fmt_num(r['electricity_price_t'],4)}</td>"
        f"<td>{fmt_num(r['electricity_cost'],2)}</td><td>{fmt_num(r['maintenance_cost'],2)}</td><td>{fmt_num(r['network_cost'],2)}</td>"
        f"<td>{fmt_num(r['land_rent'],2)}</td><td>{fmt_num(r['total_datacenter_opex'],2)}</td></tr>"
        for r in rows
    )

    team_rows = "\n".join(
        f"<tr><td>{r['year']}</td><td>{fmt_num(r['monthly_fte'],2)}</td><td>{fmt_num(r['monthly_gross'],2)}</td>"
        f"<td>{fmt_num(r['monthly_bonus'],2)}</td><td>{fmt_num(r['monthly_social'],2)}</td><td>{fmt_num(r['monthly_cost_per_fte'],2)}</td>"
        f"<td>{fmt_num(r['monthly_team_cost'],2)}</td><td>{fmt_num(r['annual_team_opex'],2)}</td></tr>"
        for r in rows
    )

    opex_rows = "\n".join(
        f"<tr><td>{r['year']}</td><td>{fmt_num(r['total_datacenter_opex'],2)}</td><td>{fmt_num(r['annual_team_opex'],2)}</td>"
        f"<td>{fmt_num(r['total_opex'],2)}</td></tr>"
        for r in rows
    )

    summary_rows = "\n".join(
        f"<tr><td>{r['year']}</td><td>{fmt_ratio(r['workplace_token_share'])}</td><td>{fmt_ratio(r['contact_center_token_share'])}</td>"
        f"<td>{fmt_num(r['required_gpu'],0)}</td><td>{fmt_num(r['total_capex'],2)}</td><td>{fmt_num(r['total_opex'],2)}</td></tr>"
        for r in rows
    )

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

<h2>Token Load</h2><table><thead><tr><th>Year</th><th>Active users</th><th>WP daily</th><th>WP annual</th><th>CC auto interactions</th><th>CC daily</th><th>CC annual</th><th>Total daily</th><th>Total annual</th></tr></thead><tbody>{token_rows}</tbody></table>
<h2>GPU Calculation</h2><table><thead><tr><th>Year</th><th>Weighted throughput</th><th>Tokens/s</th><th>Required GPU</th><th>GPU increment</th></tr></thead><tbody>{gpu_rows}</tbody></table>
<h2>CAPEX</h2><table><thead><tr><th>Year</th><th>GPU CAPEX</th><th>Total CAPEX</th><th>Annual depreciation</th></tr></thead><tbody>{capex_rows}</tbody></table>
<h2>Datacenter OPEX</h2><table><thead><tr><th>Year</th><th>Average GPU</th><th>IT load MW</th><th>Total load MW</th><th>Electricity kWh</th><th>Electricity price</th><th>Electricity cost</th><th>Maintenance</th><th>Network</th><th>Land rent</th><th>Total datacenter OPEX</th></tr></thead><tbody>{dc_rows}</tbody></table>
<h2>Team OPEX</h2><table><thead><tr><th>Year</th><th>Monthly FTE</th><th>Monthly gross</th><th>Monthly bonus</th><th>Monthly social</th><th>Monthly cost/FTE</th><th>Monthly team cost</th><th>Annual team OPEX</th></tr></thead><tbody>{team_rows}</tbody></table>
<h2>Total OPEX</h2><table><thead><tr><th>Year</th><th>Total datacenter OPEX</th><th>Annual team OPEX</th><th>Total OPEX</th></tr></thead><tbody>{opex_rows}</tbody></table>
<h2>Summary</h2><table><thead><tr><th>Year</th><th>WP token share</th><th>CC token share</th><th>Required GPU</th><th>Total CAPEX</th><th>Total OPEX</th></tr></thead><tbody>{summary_rows}</tbody></table>
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
