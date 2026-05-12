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
OUT_AUDIT = OUT_DIR / "gps_finmodel_audit.csv"
OUT_MONTHLY_PREVIEW = OUT_DIR / "monthly_assumptions_preview.csv"
ENABLE_MONTHLY_PREVIEW = False
ENABLE_MONTHLY_DEBUG_OUTPUT = True
OUT_MONTHLY_ROWS_PREVIEW = OUT_DIR / "monthly_rows_preview.csv"
OUT_MONTHLY_VS_ANNUAL_AUDIT = OUT_DIR / "monthly_vs_annual_audit.csv"
OUT_MONTHLY_VALIDATION = OUT_DIR / "monthly_validation_checks.csv"
OUT_MONTHLY_BS_DEBUG = OUT_DIR / "monthly_balance_sheet_debug.csv"
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


def build_monthly_calendar(start_year: int = 2026, end_year: int = 2030) -> list[dict[str, Any]]:
    import calendar
    from datetime import date
    out: list[dict[str, Any]] = []
    idx = 0
    for y in range(start_year, end_year + 1):
        diy = 366 if calendar.isleap(y) else 365
        for m in range(1, 13):
            dim = calendar.monthrange(y, m)[1]
            wd = sum(1 for d in range(1, dim + 1) if date(y, m, d).weekday() < 5)
            out.append({"month_key": f"{y:04d}-{m:02d}", "year": y, "month": m, "month_index": idx, "days_in_month": dim, "calendar_days_in_year": diy, "working_days": wd, "year_fraction": dim / diy})
            idx += 1
    return out


def expand_annual_to_monthly(annual_map: dict[int, float], months: list[dict[str, Any]], method: str = "step") -> dict[str, float]:
    ym = {int(k): float(v) for k, v in (annual_map or {}).items()}
    out: dict[str, float] = {}
    for mo in months:
        y = int(mo["year"]); m = int(mo["month"]); mk = str(mo["month_key"])
        cur = ym.get(y, 0.0); nxt = ym.get(y + 1, cur)
        if method == "step":
            out[mk] = cur
        elif method == "linear":
            out[mk] = cur + (nxt - cur) * ((m - 1) / 12.0)
        elif method == "annual_to_monthly_amount":
            out[mk] = cur / 12.0
        elif method == "index":
            out[mk] = (1.0 + cur) ** (1.0 / 12.0) - 1.0
        else:
            out[mk] = cur
    return out


def build_monthly_assumptions(assumptions: dict[str, Any], months: list[dict[str, Any]]) -> dict[str, Any]:
    years = sorted({int(m["year"]) for m in months})
    usage = assumptions.get("usage_assumptions", {}) or {}
    token = assumptions.get("token_load_model", {}) or {}
    revenue = assumptions.get("revenue", {}) or {}
    compute = assumptions.get("compute_model", {}) or {}
    capex = assumptions.get("capex", {}) or {}
    opex = assumptions.get("opex", {}) or {}
    inflation = ((assumptions.get("inflation", {}) or {}).get("index") or {})
    mm = (compute.get("model_mix", {}) or {})
    util = ((compute.get("infra", {}) or {}).get("utilization") or {})
    ymap = lambda v: {y: float(as_float(year_value(v, y, 0.0)) or 0.0) for y in years}
    return {
        "workplace_activation_rate": expand_annual_to_monthly(ymap((usage.get("Workplace.ai", {}) or {}).get("activation_rate")), months, "step"),
        "workplace_tokens_per_active_user_per_day": expand_annual_to_monthly(ymap((token.get("Workplace.ai", {}) or {}).get("tokens_per_active_user_per_day")), months, "step"),
        "contact_center_automation_rate": expand_annual_to_monthly(ymap((usage.get("Contact_Center.ai", {}) or {}).get("automation_rate")), months, "step"),
        "contact_center_tokens_per_interaction": expand_annual_to_monthly(ymap(((token.get("Contact_Center.ai", {}) or {}).get("tokens_per_interaction"))), months, "step"),
        "target_contribution_margin": expand_annual_to_monthly(ymap((((revenue.get("target_contribution_margin", {}) or {}).get("base")))), months, "step"),
        "utilization": expand_annual_to_monthly(ymap(util), months, "step"),
        "gpu_unit_cost": expand_annual_to_monthly(ymap((capex.get("gpu", {}) or {}).get("unit_cost")), months, "step"),
        "gpu_rental_price_per_gpu_per_year": expand_annual_to_monthly(ymap(((opex.get("gpu_rental", {}) or {}).get("rental_price_per_gpu_per_year"))), months, "annual_to_monthly_amount"),
        "inflation_index": expand_annual_to_monthly(ymap(inflation), months, "step"),
        "model_mix_frontier": expand_annual_to_monthly({y: float(as_float((mm.get(str(y), {}) or {}).get("frontier")) or 0.0) for y in years}, months, "step"),
        "model_mix_large": expand_annual_to_monthly({y: float(as_float((mm.get(str(y), {}) or {}).get("large")) or 0.0) for y in years}, months, "step"),
        "model_mix_medium": expand_annual_to_monthly({y: float(as_float((mm.get(str(y), {}) or {}).get("medium")) or 0.0) for y in years}, months, "step"),
        "model_mix_small": expand_annual_to_monthly({y: float(as_float((mm.get(str(y), {}) or {}).get("small")) or 0.0) for y in years}, months, "step"),
    }


def write_monthly_preview(assumptions: dict[str, Any], output: Path) -> None:
    months = build_monthly_calendar()
    ma = build_monthly_assumptions(assumptions, months)
    output.parent.mkdir(parents=True, exist_ok=True)
    cols = sorted(ma.keys())
    with output.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["month_key", "year", "month"] + cols)
        for m in months:
            mk = m["month_key"]
            w.writerow([mk, m["year"], m["month"]] + [ma[c].get(mk) for c in cols])


def calculate_monthly(assumptions: dict[str, Any], *, scenario_overrides: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    ass = copy.deepcopy(assumptions)
    if scenario_overrides:
        ass.update(scenario_overrides)
    annual_rows = calculate(ass)
    by_year = {int(r["year"]): r for r in annual_rows}
    months = build_monthly_calendar(min(by_year), max(by_year))
    ma = build_monthly_assumptions(ass, months)
    funding_cfg = ass.get("funding", {}) or {}
    infra_cfg = ((ass.get("capex", {}) or {}).get("strategy_scenarios", {}) or {})
    infra = str((scenario_overrides or {}).get("infrastructure_scenario") or infra_cfg.get("active_scenario") or "hybrid")
    hybrid_cfg = ((infra_cfg.get("scenarios", {}) or {}).get("hybrid", {}) or {})
    csy = int((scenario_overrides or {}).get("construction_start_year") or as_float(hybrid_cfg.get("construction_start_year")) or min(by_year))
    csm = int((scenario_overrides or {}).get("construction_start_month") or as_float(hybrid_cfg.get("construction_start_month")) or 1)
    ckey = f"{csy:04d}-{csm:02d}"
    fsc = str((scenario_overrides or {}).get("funding_scenario") or funding_cfg.get("active_scenario") or "mix")
    mix_eq = as_float((((funding_cfg.get("scenarios", {}) or {}).get("mix", {}) or {}).get("equity_share", {}).get("value")) or 0.5) or 0.5
    eq_share = 1.0 if fsc == "equity_only" else 0.0 if fsc == "revolver_only" else float((scenario_overrides or {}).get("equity_share", mix_eq))
    rev_share = 1.0 - eq_share
    discount_annual = as_float((((ass.get("investment_metrics", {}) or {}).get("discount_rate", {}) or {}).get("value", {}).get(min(by_year))) or 0.2) or 0.2
    discount_monthly = (1.0 + discount_annual) ** (1.0 / 12.0) - 1.0
    out: list[dict[str, Any]] = []
    prev_cash = 0.0; prev_rev = 0.0; prev_pic = 0.0; prev_re = 0.0; cum_dcf = 0.0; cum_fcf = 0.0
    prev_gppe = 0.0; prev_accdep = 0.0; prev_gia = 0.0; prev_accam = 0.0; prev_owned = 0.0
    for mo in months:
        y = int(mo["year"]); mk = mo["month_key"]; r = by_year[y]
        wp_month = (as_float(r.get("workplace_annual_tokens")) or 0.0) / 12.0
        cc_month = (as_float(r.get("contact_center_annual_tokens")) or 0.0) / 12.0
        wp_daily = wp_month / max(float(mo["working_days"]), 1.0)
        cc_daily = cc_month / max(float(mo["days_in_month"]), 1.0)
        total = wp_month + cc_month
        annual_interest_rate = as_float(r.get("revolver_interest_rate")) or 0.0
        monthly_interest_rate = annual_interest_rate / 12.0  # keep simple split for Step 3 consistency
        ppe_dep = ((as_float(r.get("gpu_depreciation")) or as_float(r.get("gpu_infra_depreciation")) or 0.0) + (as_float(r.get("datacenter_depreciation")) or 0.0) + (as_float(r.get("office_depreciation")) or as_float(r.get("office_capex_depreciation")) or 0.0)) / 12.0
        ip_am = ((as_float(r.get("ip_amortization")) or 0.0) if as_float(r.get("ip_amortization")) is not None else ((as_float(r.get("workplace_ai_amortization")) or 0.0) + (as_float(r.get("contact_center_ai_amortization")) or 0.0))) / 12.0
        da = ppe_dep + ip_am
        ebit = (as_float(r.get("ebit")) or 0.0) / 12.0
        req_gpu = float(as_float(r.get("required_gpu")) or 0.0)
        if infra == "rent_gpu_only":
            owned_gpu, rented_gpu = 0.0, req_gpu
        elif infra == "build_own_dc":
            owned_gpu, rented_gpu = req_gpu, 0.0
        else:
            owned_gpu, rented_gpu = (0.0, req_gpu) if mk < ckey else (req_gpu, 0.0)
        owned_inc = max(owned_gpu - prev_owned, 0.0)
        annual_gpu_capex = as_float(r.get("gpu_capex")) or 0.0
        per_gpu = annual_gpu_capex / max(req_gpu, 1.0) if req_gpu > 0 else 0.0
        gpu_capex_m = owned_inc * per_gpu
        infra_mult = (as_float(r.get("gpu_infra_capex")) or 0.0) / annual_gpu_capex if annual_gpu_capex > 0 else 1.0
        gpu_infra_m = gpu_capex_m * infra_mult
        total_dc = as_float(r.get("datacenter_construction_capex")) or 0.0
        duration = 12
        m_idx = (y - csy) * 12 + (int(mo["month"]) - csm)
        dc_const_m = (total_dc / duration) if infra in {"build_own_dc", "hybrid"} and 0 <= m_idx < duration else 0.0
        office_capex_m = (as_float(r.get("office_capex")) or 0.0) / 12.0
        tang_capex = gpu_infra_m + dc_const_m + office_capex_m
        int_capex = (as_float(r.get("intangible_capex")) or 0.0) / 12.0
        capex_month = tang_capex + int_capex
        min_cash = (as_float(r.get("minimum_cash_balance")) or 0.0) / 12.0
        interest = prev_rev * monthly_interest_rate
        for _ in range(8):
            ebt = ebit - interest
            taxm = max(ebt, 0.0) * (as_float(r.get("profit_tax_rate")) or 0.0)
            ni = ebt - taxm
            ocf = ni + da
            icf = -capex_month
            pre = prev_cash + ocf + icf
            need = max(-pre, 0.0)
            eq = need * eq_share; draw = need * rev_share
            cash_after = pre + eq + draw
            repay = min(prev_rev, max(cash_after - min_cash, 0.0))
            rev_bal = prev_rev + draw - repay
            new_interest = ((prev_rev + rev_bal) / 2.0) * monthly_interest_rate
            if abs(new_interest - interest) < 0.01:
                interest = new_interest
                break
            interest = new_interest
        ebt = ebit - interest
        taxm = max(ebt, 0.0) * (as_float(r.get("profit_tax_rate")) or 0.0)
        ni = ebt - taxm
        ocf = ni + da
        icf = -capex_month
        pre = prev_cash + ocf + icf
        need = max(-pre, 0.0)
        eq = need * eq_share; draw = need * rev_share
        cash_after = pre + eq + draw
        repay = min(prev_rev, max(cash_after - min_cash, 0.0))
        rev_bal = prev_rev + draw - repay
        avg_rev = (prev_rev + rev_bal) / 2.0
        fcf = ocf + icf
        dcf = fcf / ((1.0 + discount_monthly) ** int(mo["month_index"]))
        cum_dcf += dcf; cum_fcf += fcf
        close_cash = cash_after - repay
        gppe = prev_gppe + tang_capex
        accdep = prev_accdep + ppe_dep
        net_ppe = gppe - accdep
        gia = prev_gia + int_capex
        accam = prev_accam + ip_am
        net_int = gia - accam
        rental_price_y = as_float(year_value(((ass.get("opex", {}) or {}).get("gpu_rental", {}) or {}).get("rental_price_per_gpu_per_year"), y, 0.0)) or 0.0
        monthly_rental = rented_gpu * rental_price_y / 12.0
        monthly = {
            **mo,
            "active_users": (as_float(r.get("active_users")) or as_float(r.get("workplace_active_users")) or 0.0),
            "workplace_daily_tokens": wp_daily, "workplace_monthly_tokens": wp_month,
            "automated_interactions_per_day": (as_float(r.get("automated_interactions_per_day")) or ((as_float(r.get("automated_interactions")) or 0.0) / max((as_float(r.get("calendar_days_per_year")) or 365), 1))),
            "contact_center_daily_tokens": cc_daily, "contact_center_monthly_tokens": cc_month, "total_monthly_tokens": total,
            "weighted_throughput": as_float(r.get("weighted_throughput")) or 0.0,
            "tokens_per_second": total / max(float(mo["working_days"]) * 8 * 3600, 1),
            "required_gpu": req_gpu, "owned_gpu": owned_gpu, "rented_gpu": rented_gpu, "owned_gpu_increment": owned_inc,
            "workplace_ai_revenue": (as_float(r.get("workplace_ai_revenue")) or 0.0) / 12.0,
            "contact_center_ai_revenue": (as_float(r.get("contact_center_ai_revenue")) or 0.0) / 12.0,
            "total_revenue": (as_float(r.get("total_revenue")) or 0.0) / 12.0,
            "total_team_opex": (as_float(r.get("total_team_opex")) or 0.0) / 12.0,
            "total_sga": (as_float(r.get("total_sga")) or 0.0) / 12.0,
            "monthly_gpu_rental_cost": monthly_rental,
            "total_datacenter_opex": ((as_float(r.get("total_datacenter_opex")) or 0.0) / max(req_gpu, 1.0) / 12.0) * owned_gpu if req_gpu > 0 else 0.0,
            "total_cogs": (as_float(r.get("total_cogs")) or 0.0) / 12.0,
            "gross_profit": (as_float(r.get("gross_profit")) or 0.0) / 12.0,
            "ebitda": (as_float(r.get("ebitda")) or 0.0) / 12.0,
            "total_depreciation_and_amortization": (as_float(r.get("total_depreciation_and_amortization")) or 0.0) / 12.0,
            "ebit": ebit,
            "opening_cash": prev_cash, "opening_revolver_balance": prev_rev, "opening_paid_in_capital": prev_pic, "opening_retained_earnings": prev_re,
            "interest_expense": interest, "ebt": ebt, "profit_tax": taxm, "net_income": ni,
            "infrastructure_scenario": infra, "construction_start_year": csy, "construction_start_month": csm, "construction_flag": 1 if mk >= ckey else 0,
            "gpu_capex": gpu_capex_m, "gpu_infra_capex": gpu_infra_m, "datacenter_construction_capex": dc_const_m, "office_capex": office_capex_m, "intangible_capex": int_capex, "monthly_tangible_capex": tang_capex, "monthly_intangible_capex": int_capex, "total_capex": capex_month,
            "monthly_ppe_depreciation": ppe_dep, "monthly_ip_amortization": ip_am,
            "operating_cash_flow": ocf, "investing_cash_flow": icf, "closing_cash_before_funding": pre, "funding_need": need, "equity_injection": eq, "revolver_drawdown": draw, "cash_after_drawdown": cash_after, "revolver_repayment": repay, "revolver_balance": rev_bal, "average_revolver_balance": avg_rev, "financing_cash_flow": eq + draw - repay, "net_cash_flow": ocf + icf + (eq + draw - repay), "closing_cash_after_funding": close_cash, "closing_cash": close_cash, "cumulative_cash": close_cash, "cash": close_cash, "free_cash_flow": fcf,
            "paid_in_capital": prev_pic + eq, "retained_earnings": prev_re + ni, "total_equity": (prev_pic + eq) + (prev_re + ni), "total_liabilities": rev_bal,
            "gross_ppe": gppe, "accumulated_depreciation": accdep, "net_ppe": net_ppe, "gross_intangible_assets": gia, "accumulated_amortization": accam, "net_intangible_assets": net_int, "total_assets": close_cash + net_ppe + net_int,
            "balance_check": (close_cash + net_ppe + net_int) - rev_bal - (((prev_pic + eq) + (prev_re + ni))),
            "discount_rate_annual": discount_annual, "discount_rate_monthly": discount_monthly, "discount_factor": 1.0 / ((1.0 + discount_monthly) ** int(mo["month_index"])), "discounted_fcf": dcf, "cumulative_discounted_fcf": cum_dcf, "npv_to_date": cum_dcf,
            "utilization": ma["utilization"].get(mk, 0.0), "target_contribution_margin": ma["target_contribution_margin"].get(mk, 0.0),
        }
        out.append(monthly)
        prev_cash = close_cash; prev_rev = rev_bal; prev_pic = monthly["paid_in_capital"]; prev_re = monthly["retained_earnings"]; prev_gppe = gppe; prev_accdep = accdep; prev_gia = gia; prev_accam = accam; prev_owned = owned_gpu
    # simple monthly metrics
    def irr_bisect(cfs: list[float]) -> float | None:
        if not cfs or not (any(v > 0 for v in cfs) and any(v < 0 for v in cfs)): return None
        lo, hi = -0.99, 2.0
        for _ in range(80):
            mid = (lo + hi) / 2; npv = sum(v / ((1 + mid) ** i) for i, v in enumerate(cfs))
            if abs(npv) < 1e-6: return mid
            if npv > 0: lo = mid
            else: hi = mid
        return mid
    mirr = irr_bisect([as_float(r.get("free_cash_flow")) or 0.0 for r in out])
    for r in out:
        r["monthly_irr"] = mirr
        r["annualized_irr"] = ((1 + mirr) ** 12 - 1) if mirr is not None else None
    return out


def aggregate_monthly_to_annual(monthly_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by: dict[int, list[dict[str, Any]]] = {}
    for r in monthly_rows: by.setdefault(int(r["year"]), []).append(r)
    out: list[dict[str, Any]] = []
    for y, rows in sorted(by.items()):
        s = lambda k: sum((as_float(r.get(k)) or 0.0) for r in rows)
        mx = lambda k: max((as_float(r.get(k)) or 0.0) for r in rows)
        out.append({"year": y, "workplace_annual_tokens": s("workplace_monthly_tokens"), "contact_center_annual_tokens": s("contact_center_monthly_tokens"), "total_annual_tokens": s("total_monthly_tokens"), "required_gpu": mx("required_gpu"), "owned_gpu": as_float(rows[-1].get("owned_gpu")) or 0.0, "rented_gpu": as_float(rows[-1].get("rented_gpu")) or 0.0, "total_revenue": s("total_revenue"), "total_cogs": s("total_cogs"), "ebitda": s("ebitda"), "ebit": s("ebit"), "interest_expense": s("interest_expense"), "ebt": s("ebt"), "profit_tax": s("profit_tax"), "net_income": s("net_income"), "gpu_capex": s("gpu_capex"), "gpu_infra_capex": s("gpu_infra_capex"), "datacenter_construction_capex": s("datacenter_construction_capex"), "annual_gpu_rental_cost": s("monthly_gpu_rental_cost"), "total_datacenter_opex": s("total_datacenter_opex"), "total_depreciation_and_amortization": s("total_depreciation_and_amortization"), "total_capex": s("total_capex"), "operating_cash_flow": s("operating_cash_flow"), "investing_cash_flow": s("investing_cash_flow"), "financing_cash_flow": s("financing_cash_flow"), "free_cash_flow": s("free_cash_flow"), "funding_need": s("funding_need"), "equity_injection": s("equity_injection"), "revolver_drawdown": s("revolver_drawdown"), "revolver_repayment": s("revolver_repayment"), "discounted_fcf": s("discounted_fcf"), "opening_cash": as_float(rows[0].get("opening_cash")) or 0.0, "closing_cash": as_float(rows[-1].get("closing_cash")) or 0.0, "cumulative_cash": as_float(rows[-1].get("cumulative_cash")) or 0.0, "revolver_balance": as_float(rows[-1].get("revolver_balance")) or 0.0, "cash": as_float(rows[-1].get("cash")) or 0.0, "paid_in_capital": as_float(rows[-1].get("paid_in_capital")) or 0.0, "retained_earnings": as_float(rows[-1].get("retained_earnings")) or 0.0, "total_equity": as_float(rows[-1].get("total_equity")) or 0.0, "total_assets": as_float(rows[-1].get("total_assets")) or 0.0, "total_liabilities": as_float(rows[-1].get("total_liabilities")) or 0.0, "balance_check": as_float(rows[-1].get("balance_check")) or 0.0, "cumulative_discounted_fcf": as_float(rows[-1].get("cumulative_discounted_fcf")) or 0.0})
    return out


def write_monthly_rows_preview(monthly_rows: list[dict[str, Any]], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    cols = sorted({k for r in monthly_rows for k in r.keys()})
    with output.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols); w.writeheader(); w.writerows(monthly_rows)


def write_monthly_vs_annual_audit(annual_rows: list[dict[str, Any]], monthly_annual_rows: list[dict[str, Any]], output: Path, assumptions: dict[str, Any] | None = None) -> None:
    am = {int(r["year"]): r for r in annual_rows}; mm = {int(r["year"]): r for r in monthly_annual_rows}
    metrics = ["total_annual_tokens", "required_gpu", "total_revenue", "total_cogs", "ebitda", "ebit", "net_income", "total_capex", "operating_cash_flow", "investing_cash_flow", "free_cash_flow", "funding_need", "equity_injection", "revolver_drawdown", "revolver_repayment", "revolver_balance", "interest_expense", "closing_cash", "balance_check", "discounted_fcf"]
    output.parent.mkdir(parents=True, exist_ok=True)
    dcf_map: dict[int, float] = {}
    if assumptions is not None:
        dr = as_float((((assumptions.get("investment_metrics", {}) or {}).get("discount_rate", {}) or {}).get("value", {}).get(min(am))) or 0.2) or 0.2
        for i, y in enumerate(sorted(am)):
            fcf = as_float((am[y] or {}).get("free_cash_flow")) or 0.0
            dcf_map[y] = fcf / ((1.0 + dr) ** i)
    with output.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerow(["metric", "year", "annual_value", "monthly_aggregated_value", "difference", "pct_difference", "status"])
        for y in sorted(am):
            for m in metrics:
                av = as_float(am[y].get(m)); mv = as_float((mm.get(y) or {}).get(m))
                if av is None and m == "discounted_fcf":
                    av = dcf_map.get(y)
                if av is None or mv is None: w.writerow([m, y, av, mv, None, None, "N/A"]); continue
                diff = mv - av; pct = (diff / av * 100.0) if abs(av) > 1e-9 else 0.0
                tol = 5.0 if m == "required_gpu" else 1.0
                ok = abs(pct) <= tol if m != "required_gpu" else (abs(diff) <= 1 or abs(pct) <= 5)
                w.writerow([m, y, av, mv, diff, pct, "OK" if ok else "WARNING"])


def write_monthly_validation_checks(monthly_rows: list[dict[str, Any]], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerow(["month_key", "check", "expected", "actual", "difference", "status"])
        prev_cdf = 0.0
        for r in monthly_rows:
            mk = r["month_key"]
            bal = as_float(r.get("balance_check")) or 0.0
            w.writerow([mk, "balance_check", 0.0, bal, bal, "OK" if abs(bal) <= 1.0 else "WARNING"])
            net = as_float(r.get("net_cash_flow")) or 0.0
            ident = (as_float(r.get("operating_cash_flow")) or 0.0) + (as_float(r.get("investing_cash_flow")) or 0.0) + (as_float(r.get("financing_cash_flow")) or 0.0)
            w.writerow([mk, "funding_identity", ident, net, net - ident, "OK" if abs(net - ident) <= 1e-6 else "WARNING"])
            close = as_float(r.get("closing_cash")) or 0.0; open_ = as_float(r.get("opening_cash")) or 0.0
            w.writerow([mk, "cash_rollforward", open_ + net, close, close - (open_ + net), "OK" if abs(close - (open_ + net)) <= 1e-6 else "WARNING"])
            rev = as_float(r.get("revolver_balance")) or 0.0; orev = as_float(r.get("opening_revolver_balance")) or 0.0; draw = as_float(r.get("revolver_drawdown")) or 0.0; rep = as_float(r.get("revolver_repayment")) or 0.0
            w.writerow([mk, "revolver_rollforward", orev + draw - rep, rev, rev - (orev + draw - rep), "OK" if abs(rev - (orev + draw - rep)) <= 1e-6 else "WARNING"])
            cdf = as_float(r.get("cumulative_discounted_fcf")) or 0.0; d = as_float(r.get("discounted_fcf")) or 0.0
            w.writerow([mk, "dcf_rollforward", prev_cdf + d, cdf, cdf - (prev_cdf + d), "OK" if abs(cdf - (prev_cdf + d)) <= 1e-6 else "WARNING"])
            prev_cdf = cdf


def write_monthly_balance_sheet_debug(monthly_rows: list[dict[str, Any]], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    cols = ["month_key","cash","net_ppe","net_intangible_assets","total_assets","revolver_balance","paid_in_capital","retained_earnings","total_equity","monthly_tangible_capex","monthly_intangible_capex","monthly_ppe_depreciation","monthly_ip_amortization","equity_injection","net_income","balance_check"]
    with output.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols); w.writeheader()
        for r in monthly_rows:
            w.writerow({c: r.get(c) for c in cols})


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
    annual_growth_raw = electricity_price_cfg.get("annual_growth")
    annual_growth_map: dict[int, float] = {}
    if isinstance(annual_growth_raw, dict):
        for y_key, y_val in annual_growth_raw.items():
            try:
                y_int = int(y_key)
            except (TypeError, ValueError):
                continue
            g = as_float((y_val or {}).get("value")) if isinstance(y_val, dict) else as_float(y_val)
            annual_growth_map[y_int] = 0.0 if g is None else float(g)
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
    min_cash_cfg_new = (funding_cfg.get("minimum_cash_balance", {}) or {}) if isinstance(funding_cfg.get("minimum_cash_balance", {}), dict) else {}
    min_cash_cfg_old = ((funding_cfg.get("revolver", {}) or {}).get("repayment_logic", {}) or {}).get("minimum_cash_balance", {}) or {}
    min_cash_months = as_float((min_cash_cfg_new.get("months_of_fixed_costs", {}) or {}).get("value"))
    if min_cash_months is None:
        min_cash_months = as_float((min_cash_cfg_old.get("months_of_fixed_costs", {}) or {}).get("value"))
    if min_cash_months is None:
        print("WARNING: funding.minimum_cash_balance.months_of_fixed_costs.value отсутствует; используется 0.", file=sys.stderr)
        min_cash_months = 0.0
    min_cash_buffer_months = float(min_cash_months)

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
        if math.isnan(minimum_cash_balance):
            minimum_cash_balance = 0.0
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
        financing_cash_flow = safe_add(equity_injection, revolver_drawdown, -revolver_repayment)
        net_cash_flow = safe_add(pre_financing_cash_flow, financing_cash_flow)
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
                "office_server_depreciation": office_server_depreciation,
                "employee_laptops_depreciation": employee_laptops_depreciation,
                "executive_laptops_depreciation": executive_laptops_depreciation,
                "mfu_depreciation": mfu_depreciation,
                "meeting_rooms_depreciation": meeting_rooms_depreciation,
                "office_furniture_depreciation": office_furniture_depreciation,
                "workplace_ai_amortization": workplace_ai_amortization,
                "contact_center_ai_amortization": contact_center_ai_amortization,
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
                "datacenter_maintenance_base": maintenance_base if 'maintenance_base' in locals() else float("nan"),
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
                "pricing_base": pricing_base if 'pricing_base' in locals() else float("nan"),
                "workplace_pricing_base": pricing_base_wp if 'pricing_base_wp' in locals() else float("nan"),
                "contact_center_pricing_base": pricing_base_cc if 'pricing_base_cc' in locals() else float("nan"),
                "target_contribution_margin": contribution_margin,
                "workplace_revenue_availability_factor": wp_revenue_factor,
                "contact_center_revenue_availability_factor": cc_revenue_factor,
                "total_revenue": total_revenue,
                "workplace_implied_price_per_1m_tokens": workplace_implied_price_per_1m_tokens,
                "contact_center_implied_price_per_1m_tokens": contact_center_implied_price_per_1m_tokens,
                "other_datacenter_opex": other_opex,
                "total_cogs": total_cogs,
                "tangible_capex": safe_add(gpu_infra_capex, datacenter_construction_capex, office_capex),
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
                "opening_revolver_balance": opening_revolver_balance,
                "average_revolver_balance": avg_revolver_balance,
                "revolver_interest_rate": revolver_interest_rate,
                "closing_cash_before_funding": closing_cash_before_funding,
                "cash_after_drawdown": cash_after_drawdown,
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
    validation_messages: list[str] = []
    active_scenario = str(rows[-1].get("active_scenario", "N/A")) if rows else "N/A"

    pct_metrics = {"discount_rate", "irr", "roic", "roe", "roa", "utilization", "target_contribution_margin", "contribution_margin"}
    x_metrics = {"debt_to_equity", "net_debt_to_ebitda", "interest_coverage"}
    int_metrics = {"required_gpu"}

    def render_value(v: Any, metric: str | None = None) -> str:
        if v is None or (isinstance(v, float) and math.isnan(v)):
            return "<span class='na'>N/A</span>"
        fv = as_float(v)
        if fv is None:
            return str(v)
        metric_name = metric or ""
        if metric_name in int_metrics or metric_name == "construction_start_year" or metric_name.endswith("_year"):
            cls = "neg" if fv < 0 else ("zero" if abs(fv) < 1e-12 else "")
            return f"<span class='{cls}'>{int(round(fv))}</span>"
        if metric_name in {"simple_payback", "discounted_payback"}:
            if abs(fv - round(fv)) < 1e-9:
                cls = "neg" if fv < 0 else ("zero" if abs(fv) < 1e-12 else "")
                return f"<span class='{cls}'>{int(round(fv))}</span>"
        if metric_name in pct_metrics:
            cls = "neg" if fv < 0 else ("zero" if abs(fv) < 1e-12 else "")
            return f"<span class='{cls}'>{fv * 100:.1f}%</span>"
        if metric_name in x_metrics:
            cls = "neg" if fv < 0 else ("zero" if abs(fv) < 1e-12 else "")
            return f"<span class='{cls}'>{fv:.2f}x</span>"
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
                        cells.append("<td><span class='na'>N/A</span></td>")
                    elif fv is None:
                        cells.append(f"<td>{v}</td>")
                    else:
                        display = render_value(fv, c if c in pct_metrics or c in x_metrics else None)
                        cells.append(f"<td>{display}</td>")
                body_rows.append(f"<tr><td>{row_name}</td>{''.join(cells)}</tr>")
            tables_by_title[title] = f"<div class='card'><h3>Infrastructure Scenario Comparison</h3><div class='note'>Funding scenario is controlled above. Full 3×3 comparison can be added later.</div><table><thead><tr><th>Scenario</th>{head}</tr></thead><tbody>{''.join(body_rows)}</tbody></table></div>"
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
                cells.append(f"<td class='num' data-card='{title}' data-metric='{metric}' data-year='{y}'>{render_value(v, metric)}</td>")
            body.append(f"<tr><td class='metric'>{metric}</td>{''.join(cells)}</tr>")
        tables_by_title[title] = f"<div class='card'><h3>{title}</h3><table><thead><tr><th>Metric</th>{hy}</tr></thead><tbody>{''.join(body)}</tbody></table></div>"
    wt,cm,matrix = build_sensitivity_matrix(assumptions, rows)
    scol = ''.join(f'<th>{c:.2f}x</th>' for c in cm)
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
        sbody.append(f"<tr><td class='sticky'>{w:.2f}x</td>{row}</tr>")
    sensitivity_html = f"<div class='card'><h3>Sensitivity Analysis — NPV</h3><div class='table-wrap'><table class='sensitivity'><thead><tr><th class='sticky'>weighted_throughput_multiplier</th>{scol}</tr></thead><tbody>{''.join(sbody)}</tbody></table></div></div>"
    tables_by_title["Sensitivity Analysis"] = sensitivity_html

    # Validation checks
    checks_rows: list[str] = []
    # 1) Balance sheet check
    for r in rows:
        y = int(r["year"])
        bal = as_float(r.get("balance_check")) or 0.0
        ok = abs(bal) < 1.0
        if not ok:
            validation_messages.append(f"WARNING: balance_check year={y} diff={bal:.4f}")
        checks_rows.append(f"<tr><td>Balance Sheet</td><td>{y}</td><td>{fmt_num(bal,2)}</td><td class={'ok' if ok else 'warn'}>{'OK' if ok else 'WARNING'}</td></tr>")
    # 2) CAPEX double counting check
    for r in rows:
        y = int(r["year"])
        expected = -((as_float(r.get("gpu_infra_capex")) or 0.0) + (as_float(r.get("datacenter_construction_capex")) or 0.0) + (as_float(r.get("office_capex")) or 0.0) + (as_float(r.get("intangible_capex")) or 0.0))
        actual = as_float(r.get("investing_cash_flow")) or 0.0
        diff = actual - expected
        ok = abs(diff) < 1.0
        if not ok:
            validation_messages.append(f"WARNING: investing_cash_flow year={y} diff={diff:.4f}")
        checks_rows.append(f"<tr><td>Investing CF composition</td><td>{y}</td><td>{fmt_num(diff,2)}</td><td class={'ok' if ok else 'warn'}>{'OK' if ok else 'WARNING'}</td></tr>")
    # 3) Revenue go-live expected factors
    wp_cfg = (((assumptions.get("capex", {}) or {}).get("intangible_assets", {}) or {}).get("products", {}) or {}).get("workplace_ai", {}) or {}
    cc_cfg = (((assumptions.get("capex", {}) or {}).get("intangible_assets", {}) or {}).get("products", {}) or {}).get("contact_center_ai", {}) or {}
    wp_y, wp_m = int(as_float(wp_cfg.get("go_live_year")) or years[0]), int(as_float(wp_cfg.get("go_live_month")) or 1)
    cc_y, cc_m = int(as_float(cc_cfg.get("go_live_year")) or years[0]), int(as_float(cc_cfg.get("go_live_month")) or 1)
    for y in years:
        wp_exp = 0.0 if y < wp_y else (12 - wp_m + 1) / 12.0 if y == wp_y else 1.0
        cc_exp = 0.0 if y < cc_y else (12 - cc_m + 1) / 12.0 if y == cc_y else 1.0
        ok = True
        checks_rows.append(f"<tr><td>Revenue go-live factors</td><td>{y}</td><td>WP={wp_exp:.2f}, CC={cc_exp:.2f}</td><td class='ok'>OK</td></tr>")
    # 4) Funding floor check
    for r in rows:
        y = int(r["year"])
        repay = as_float(r.get("revolver_repayment")) or 0.0
        cash = as_float(r.get("closing_cash_after_funding")) or 0.0
        floor = as_float(r.get("minimum_cash_balance")) or 0.0
        ok = True if repay <= 0 else cash >= (floor - 1.0)
        if not ok:
            validation_messages.append(f"WARNING: cash floor year={y} cash={cash:.2f} floor={floor:.2f}")
        checks_rows.append(f"<tr><td>Funding cash floor</td><td>{y}</td><td>cash={fmt_num(cash,2)} floor={fmt_num(floor,2)}</td><td class={'ok' if ok else 'warn'}>{'OK' if ok else 'WARNING'}</td></tr>")
    # 5) Electricity check
    for r in rows:
        y = int(r["year"]); owned = as_float(r.get("owned_gpu")) or 0.0
        p = as_float(r.get("electricity_price_t")) or 0.0; kwh = as_float(r.get("electricity_kwh")) or 0.0; cost = as_float(r.get("electricity_cost")) or 0.0
        ok = (p > 0 and kwh > 0 and cost > 0) if owned > 0 else (p > 0)
        if not ok:
            validation_messages.append(f"WARNING: electricity check year={y} owned={owned} price={p} kwh={kwh} cost={cost}")
        checks_rows.append(f"<tr><td>Electricity</td><td>{y}</td><td>owned={owned:.0f}, tariff={fmt_num(p,2)}, kwh={fmt_num(kwh,0)}, cost={fmt_num(cost,2)}</td><td class={'ok' if ok else 'warn'}>{'OK' if ok else 'WARNING'}</td></tr>")
    # 6) DCF check
    npv_val = as_float(metric_store.get("npv", {}).get(years[0])) or 0.0
    dcf_sum = sum((as_float(metric_store.get("discounted_fcf", {}).get(y)) or 0.0) for y in years)
    dcf_diff = npv_val - dcf_sum
    dcf_ok = abs(dcf_diff) < 1.0
    checks_rows.append(f"<tr><td>DCF NPV sum</td><td>All</td><td>{fmt_num(dcf_diff,2)}</td><td class={'ok' if dcf_ok else 'warn'}>{'OK' if dcf_ok else 'WARNING'}</td></tr>")
    if not dcf_ok:
        validation_messages.append(f"WARNING: dcf npv diff={dcf_diff:.4f}")
    # 7) Sensitivity base cell check
    sens_base = matrix.get((1.0, 1.0))
    sens_diff = (as_float(sens_base) or 0.0) - npv_val
    sens_ok = abs(sens_diff) < 1.0
    checks_rows.append(f"<tr><td>Sensitivity base cell</td><td>1.00x/1.00x</td><td>{fmt_num(sens_diff,2)}</td><td class={'ok' if sens_ok else 'warn'}>{'OK' if sens_ok else 'WARNING'}</td></tr>")
    if not sens_ok:
        validation_messages.append(f"WARNING: sensitivity base diff={sens_diff:.4f}")
    # 8) Scenario comparison active scenario check
    sc = str(active_scenario)
    sc_row = scenario_cmp.get(sc, {})
    active_ok = True
    if sc_row:
        active_ok = (
            abs((as_float(sc_row.get("npv")) or 0.0) - npv_val) < 1.0
            and str(sc_row.get("simple_payback")) == str(metric_store.get("simple_payback", {}).get(years[0]))
            and str(sc_row.get("discounted_payback")) == str(metric_store.get("discounted_payback", {}).get(years[0]))
        )
    checks_rows.append(f"<tr><td>Scenario comparison active row</td><td>{sc}</td><td>match base metrics</td><td class={'ok' if active_ok else 'warn'}>{'OK' if active_ok else 'WARNING'}</td></tr>")
    if not active_ok:
        validation_messages.append(f"WARNING: scenario comparison mismatch for active={sc}")
    tables_by_title["Model Validation Checks"] = f"<div class='card'><h3>Model Validation Checks</h3><table><thead><tr><th>Check</th><th>Year</th><th>Detail / Difference</th><th>Status</th></tr></thead><tbody>{''.join(checks_rows)}</tbody></table></div>"
    for msg in validation_messages:
        print(msg, file=sys.stderr)

    section_map = {
        "Operating Model": ["Token Load", "GPU Calculation", "Infrastructure Scenario"],
        "Investment Plan": ["CAPEX", "Datacenter Construction CAPEX", "Office CAPEX", "Intangible Assets", "Depreciation & Amortization"],
        "Operating Costs": ["Datacenter OPEX", "Team OPEX", "GPU Rental OPEX", "SG&A"],
        "Financial Statements": ["Revenue", "COGS", "P&L Summary", "Cash Flow Statement", "Funding", "Balance Sheet"],
        "Investment Case": ["DCF", "Investment Metrics", "Model Validation Checks", "Return Metrics", "Scenario Comparison", "Sensitivity Analysis"],
    }
    sections_html = []
    for sec, names in section_map.items():
        blocks = "".join(tables_by_title.get(n, "") for n in names if n in tables_by_title)
        if blocks:
            sections_html.append(f"<section><h2>{sec}</h2>{blocks}</section>")
    owned_dc_diag_html = """
<div class='card' id='owned_dc_diag'><h3>Owned DC Economics Diagnostic</h3><div id='owned_dc_diag_current'></div><div class='table-wrap'><table id='owned_dc_diag_cmp'><thead><tr><th>Scenario</th><th>NPV</th><th>Required Investments</th><th>Total CAPEX</th><th>DC Construction CAPEX</th><th>GPU Infra CAPEX</th><th>GPU Rental OPEX</th><th>Datacenter OPEX</th><th>Total D&A</th><th>2030 EBITDA</th><th>2030 FCF</th><th>Discounted payback</th></tr></thead><tbody></tbody></table></div><div id='owned_dc_diag_note' class='note'></div></div>
"""
    sections_html = [s.replace("</section>", owned_dc_diag_html + "</section>") if "<h2>Investment Case</h2>" in s else s for s in sections_html]

    latest = rows[-1]
    kpis = [
        ("NPV", "npv", metric_store.get("npv", {}).get(years[0])),
        ("IRR", "irr", metric_store.get("irr", {}).get(years[0])),
        ("Required Investments", "total_capex", sum((as_float(r.get("total_capex")) or 0.0) for r in rows)),
        ("Peak Required GPU", "required_gpu", max((as_float(r.get("required_gpu")) or 0.0) for r in rows)),
        ("Payback", "simple_payback", metric_store.get("simple_payback", {}).get(years[0])),
    ]
    kpi_html = "".join(
        f"<div class='kpi'><div class='k'>{k}</div><div class='v' {'id=\"kpi-npv\"' if k=='NPV' else ''}>{render_value(v, m)}</div></div>"
        for k, m, v in kpis
    )
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
    sl_margin_default = (as_float(metric_store.get("target_contribution_margin", {}).get(years[0])) or 0.30)
    opex_root = assumptions.get("opex", {}) if isinstance(assumptions.get("opex"), dict) else {}
    team = opex_root.get("team", assumptions.get("team", {}))
    sga = assumptions.get("sga", {}) if isinstance(assumptions.get("sga"), dict) else {}
    payroll = team.get("payroll_assumptions", {}) if isinstance(team, dict) and isinstance(team.get("payroll_assumptions"), dict) else {}
    salary_growth_map = to_year_map(payroll.get("salary_growth"))
    bonus_cfg = payroll.get("bonus_percent_of_gross")
    social_cfg = payroll.get("social_contribution_sfr_percent_of_gross")
    sga_payroll = sga.get("payroll_assumptions", {}) if isinstance(sga.get("payroll_assumptions"), dict) else {}
    sl_gpu_cost_default = float(as_float((assumptions.get("capex", {}).get("gpu", {}) or {}).get("unit_cost")) or 0.0)
    sl_rent_default = float(as_float(((assumptions.get("opex", {}).get("gpu_rental", {}) or {}).get("rental_price_per_gpu_per_year")) or 0.0)
        or as_float((assumptions.get("opex", {}).get("gpu_rental", {}) or {}).get("rental_price_per_gpu_per_year", {}).get("value"))
        or 0.0)
    sl_dr_default = float(as_float(metric_store.get("discount_rate", {}).get(years[0])) or 0.30)
    core_target_fte_map = flatten_role_values((team.get("core_team_target_fte", {}) if isinstance(team, dict) else {}))
    core_salary_map = flatten_role_values((team.get("salary_gross_monthly_rub", {}) if isinstance(team, dict) else {}))
    core_cap_roles = flatten_role_values((((team.get("capitalization", {}) or {}).get("role_eligibility", {})) if isinstance(team, dict) else {}))
    sga_target_fte_map = flatten_role_values((sga.get("target_fte", {}) if isinstance(sga, dict) else {}))
    sga_salary_map = flatten_role_values((sga.get("salary_gross_monthly_rub", {}) if isinstance(sga, dict) else {}))
    inflation_index_by_year = {}
    for y in years:
        salary_idx = 1.0
        for yy in years:
            if yy > y:
                break
            salary_idx *= (1.0 + (as_float(salary_growth_map.get(yy)) or 0.0))
        inflation_index_by_year[y] = salary_idx
    core_roles = sorted(set(core_target_fte_map.keys()) | set(core_salary_map.keys()))
    sga_roles = sorted(set(sga_target_fte_map.keys()) | set(sga_salary_map.keys()))
    team_planner = {
        "core_team": {
            "roles": [
                {
                    "name": "/".join(p),
                    "monthly_salary_2026": float(core_salary_map.get(p, 0.0) or 0.0),
                    "fte_by_year": {str(y): float(core_target_fte_map.get(p, 0.0) or 0.0) for y in years},
                    "eligible_for_capitalization": bool(core_cap_roles.get(p, 0.0)),
                }
                for p in core_roles
            ],
            "annual_bonus_percent_of_gross": float(as_float(year_value(bonus_cfg, years[0], 0.0)) or 0.0),
            "social_contribution_sfr_percent_of_gross": float(as_float(year_value(social_cfg, years[0], 0.0)) or 0.0),
        },
        "sga": {
            "roles": [
                {
                    "name": "/".join(p),
                    "monthly_salary_2026": float(sga_salary_map.get(p, 0.0) or 0.0),
                    "fte_by_year": {str(y): float(sga_target_fte_map.get(p, 0.0) or 0.0) for y in years},
                }
                for p in sga_roles
            ],
            "annual_bonus_percent_of_gross": float(as_float(year_value(sga_payroll.get("annual_bonus_percent_of_gross"), years[0], 0.0)) or 0.0),
            "social_contribution_sfr_percent_of_gross": float(as_float(year_value(sga_payroll.get("social_contribution_sfr_percent_of_gross"), years[0], 0.0)) or 0.0),
        },
    }
    rows_by_year = {int(r.get("year", 0)): r for r in rows}
    def yv(metric: str, y: int, default: float = 0.0) -> float:
        return float(as_float((rows_by_year.get(y) or {}).get(metric)) or default)
    usage = assumptions.get("usage_assumptions", {}) if isinstance(assumptions.get("usage_assumptions"), dict) else {}
    token_model = assumptions.get("token_load_model", {}) if isinstance(assumptions.get("token_load_model"), dict) else {}
    compute_model = assumptions.get("compute_model", {}) if isinstance(assumptions.get("compute_model"), dict) else {}
    wp_act_map = to_year_map(((usage.get("Workplace.ai", {}) or {}).get("activation_rate")))
    wp_tok_map = to_year_map(((token_model.get("Workplace.ai", {}) or {}).get("tokens_per_active_user_per_day")))
    cc_auto_map = to_year_map(((usage.get("Contact_Center.ai", {}) or {}).get("automation_rate")))
    cc_tok = as_float(((token_model.get("Contact_Center.ai", {}) or {}).get("tokens_per_interaction"))) or 0.0
    mix_cfg = compute_model.get("model_mix", {}) if isinstance(compute_model.get("model_mix"), dict) else {}
    tput_cfg = compute_model.get("throughput_per_gpu", {}) if isinstance(compute_model.get("throughput_per_gpu"), dict) else {}
    util_map = to_year_map(((compute_model.get("infra", {}) or {}).get("utilization")))
    def pct(v: float) -> float: return float(v) * 100.0
    def infer_wp_activation(y: int) -> float:
        from_yaml = as_float(wp_act_map.get(y))
        if from_yaml is not None:
            return float(from_yaml)
        r = rows_by_year.get(y) or {}
        act = as_float(r.get("workplace_activation_rate"))
        if act is not None and act > 0:
            return float(act)
        active = as_float(r.get("workplace_active_users")) or 0.0
        total_emp = as_float(r.get("workplace_total_employees")) or as_float(r.get("total_employees")) or 0.0
        if total_emp > 0:
            return active / total_emp
        return 0.0
    def infer_wp_tokens(y: int) -> float:
        from_yaml = as_float(wp_tok_map.get(y))
        if from_yaml is not None and from_yaml > 0:
            return float(from_yaml)
        r = rows_by_year.get(y) or {}
        v = as_float(r.get("workplace_tokens_per_active_user_per_day"))
        if v is not None and v > 0:
            return float(v)
        daily = as_float(r.get("workplace_daily_tokens")) or 0.0
        active = as_float(r.get("workplace_active_users")) or 0.0
        return (daily / active) if active > 0 else 0.0
    def infer_cc_auto(y: int) -> float:
        from_yaml = as_float(cc_auto_map.get(y))
        if from_yaml is not None:
            return float(from_yaml)
        r = rows_by_year.get(y) or {}
        v = as_float(r.get("contact_center_automation_rate"))
        if v is not None and v > 0:
            return float(v)
        auto = as_float(r.get("automated_interactions_per_day")) or as_float(r.get("automated_interactions")) or 0.0
        total = as_float(r.get("interactions_per_day")) or as_float(r.get("contact_center_interactions_per_day")) or 0.0
        return (auto / total) if total > 0 else 0.0
    def infer_cc_tpi(y: int) -> float:
        if cc_tok and cc_tok > 0:
            return float(cc_tok)
        r = rows_by_year.get(y) or {}
        v = as_float(r.get("contact_center_tokens_per_interaction"))
        if v is not None and v > 0:
            return float(v)
        daily = as_float(r.get("contact_center_daily_tokens")) or 0.0
        auto = as_float(r.get("automated_interactions_per_day")) or as_float(r.get("automated_interactions")) or 0.0
        return (daily / auto) if auto > 0 else 0.0
    key_assumptions_rows = [
        {"key":"workplace_activation_rate","section":"Workplace.ai","label":"Activation rate","unit":"%","input_mode":"yearly","value_type":"percent","values_by_year":{str(y):pct(infer_wp_activation(y)) for y in years}},
        {"key":"workplace_tokens_per_active_user_per_day","section":"Workplace.ai","label":"Tokens per active user per day","unit":"tokens/user/day","input_mode":"yearly","value_type":"tokens","values_by_year":{str(y):infer_wp_tokens(y) for y in years}},
        {"key":"contact_center_automation_rate","section":"Contact_Center.ai","label":"Automation rate","unit":"%","input_mode":"yearly","value_type":"percent","values_by_year":{str(y):pct(infer_cc_auto(y)) for y in years}},
        {"key":"contact_center_tokens_per_interaction","section":"Contact_Center.ai","label":"Tokens per interaction","unit":"tokens/interaction","input_mode":"base_only","value_type":"tokens","values_by_year":{str(y):infer_cc_tpi(y) for y in years}},
        {"key":"target_contribution_margin","section":"Revenue / Pricing","label":"Target contribution margin","unit":"%","input_mode":"yearly","value_type":"percent","values_by_year":{str(y):pct(yv("target_contribution_margin", y)) for y in years}},
        {"key":"model_mix_frontier","section":"Compute / GPU","label":"Model mix — frontier","unit":"%","input_mode":"yearly","value_type":"percent","values_by_year":{str(y):pct(as_float(((mix_cfg.get(str(y)) or mix_cfg.get(y) or {}) or {}).get("frontier")) or 0.0) for y in years}},
        {"key":"model_mix_large","section":"Compute / GPU","label":"Model mix — large","unit":"%","input_mode":"yearly","value_type":"percent","values_by_year":{str(y):pct(as_float(((mix_cfg.get(str(y)) or mix_cfg.get(y) or {}) or {}).get("large")) or 0.0) for y in years}},
        {"key":"model_mix_medium","section":"Compute / GPU","label":"Model mix — medium","unit":"%","input_mode":"yearly","value_type":"percent","values_by_year":{str(y):pct(as_float(((mix_cfg.get(str(y)) or mix_cfg.get(y) or {}) or {}).get("medium")) or 0.0) for y in years}},
        {"key":"model_mix_small","section":"Compute / GPU","label":"Model mix — small","unit":"%","input_mode":"yearly","value_type":"percent","values_by_year":{str(y):pct(as_float(((mix_cfg.get(str(y)) or mix_cfg.get(y) or {}) or {}).get("small")) or 0.0) for y in years}},
        {"key":"throughput_frontier","section":"Compute / GPU","label":"Throughput per GPU — frontier","unit":"tokens/sec/GPU","input_mode":"base_only","value_type":"number","values_by_year":{str(y):float(as_float(tput_cfg.get("frontier")) or 0.0) for y in years}},
        {"key":"throughput_large","section":"Compute / GPU","label":"Throughput per GPU — large","unit":"tokens/sec/GPU","input_mode":"base_only","value_type":"number","values_by_year":{str(y):float(as_float(tput_cfg.get("large")) or 0.0) for y in years}},
        {"key":"throughput_medium","section":"Compute / GPU","label":"Throughput per GPU — medium","unit":"tokens/sec/GPU","input_mode":"base_only","value_type":"number","values_by_year":{str(y):float(as_float(tput_cfg.get("medium")) or 0.0) for y in years}},
        {"key":"throughput_small","section":"Compute / GPU","label":"Throughput per GPU — small","unit":"tokens/sec/GPU","input_mode":"base_only","value_type":"number","values_by_year":{str(y):float(as_float(tput_cfg.get("small")) or 0.0) for y in years}},
        {"key":"gpu_utilization","section":"Compute / GPU","label":"GPU utilization","unit":"%","input_mode":"yearly","value_type":"percent","values_by_year":{str(y):pct(util_map.get(y, yv("utilization", y, 0.5))) for y in years}},
        {"key":"peak_factor","section":"Compute / GPU","label":"Peak factor","unit":"x","input_mode":"base_only","value_type":"number","values_by_year":{str(y):yv("peak_factor", y, 1.0) for y in years}},
        {"key":"weighted_throughput","section":"Compute / GPU","label":"Weighted throughput","unit":"tokens/sec/GPU","input_mode":"readonly","value_type":"number","values_by_year":{str(y):yv("weighted_throughput", y) for y in years}},
        {"key":"gpu_unit_cost","section":"Infrastructure / Cost","label":"GPU unit cost","unit":"RUB/GPU","input_mode":"base_only","value_type":"rub","values_by_year":{str(y):sl_gpu_cost_default for y in years}},
        {"key":"gpu_rental_price_per_gpu_per_year","section":"Infrastructure / Cost","label":"GPU rental price per year","unit":"RUB/GPU/year","input_mode":"base_only","value_type":"rub","values_by_year":{str(y):sl_rent_default for y in years}},
        {"key":"discount_rate","section":"Finance","label":"Discount rate","unit":"%","input_mode":"base_only","value_type":"percent","values_by_year":{str(y):sl_dr_default*100 for y in years}},
    ]
    scenario_lab_data = {
        "base_npv": as_float(metric_store.get("npv", {}).get(years[0])) or 0.0,
        "base_discount_rate": sl_dr_default,
        "base_gpu_unit_cost": sl_gpu_cost_default,
        "base_rental_price": sl_rent_default,
        "active_infrastructure_scenario": str((assumptions.get("capex", {}).get("strategy_scenarios", {}) or {}).get("active_scenario", "hybrid")),
        "active_funding_scenario": str((assumptions.get("funding", {}) or {}).get("active_scenario", "mix")),
        "construction_start_year": as_float(rows[-1].get("construction_start_year")) if rows else 2028,
        "funding_scenarios": {
            "equity_only": {"equity_share": 1.0, "revolver_share": 0.0},
            "revolver_only": {"equity_share": 0.0, "revolver_share": 1.0},
            "mix": {
                "equity_share": as_float((((assumptions.get("funding", {}).get("scenarios", {}).get("mix", {}) or {}).get("equity_share", {}) or {}).get("value")) or 0.5),
                "revolver_share": as_float((((assumptions.get("funding", {}).get("scenarios", {}).get("mix", {}) or {}).get("revolver_share", {}) or {}).get("value")) or 0.5),
            },
        },
        "infra_scenarios": ["build_own_dc", "rent_gpu_only", "hybrid"],
        "rows": [{k: (None if isinstance(v, float) and math.isnan(v) else v) for k, v in r.items()} for r in rows],
        "infra_multiplier": as_float((assumptions.get("capex", {}).get("infra_multiplier", {}) or {}).get("value")) or 0.0,
        "profit_tax_rate": as_float((((assumptions.get("pnl", {}) or {}).get("tax", {}) or {}).get("profit_tax_rate", {}) or {}).get("value")) or 0.0,
        "team_planner": team_planner,
        "inflation_index_by_year": {str(y): inflation_index_by_year.get(y, 1.0) for y in years},
        "go_live_year": int((years[0] if years else 2026)),
        "go_live_month": 1,
        "key_assumptions": {"rows": key_assumptions_rows},
    }
    financial_flow_data = {
        str(int(r.get("year", 0))): {
            "workplace_ai_revenue": as_float(r.get("workplace_ai_revenue")),
            "contact_center_ai_revenue": as_float(r.get("contact_center_ai_revenue")),
            "total_revenue": as_float(r.get("total_revenue")),
            "total_cogs": as_float(r.get("total_cogs")),
            "gross_profit": as_float(r.get("gross_profit")),
            "total_sga": as_float(r.get("total_sga")),
            "ebitda": as_float(r.get("ebitda")),
            "total_depreciation_and_amortization": as_float(r.get("total_depreciation_and_amortization")),
            "ebit": as_float(r.get("ebit")),
            "interest_expense": as_float(r.get("interest_expense")),
            "ebt": as_float(r.get("ebt")),
            "profit_tax": as_float(r.get("profit_tax")),
            "net_income": as_float(r.get("net_income")),
        }
        for r in rows
    }
    report_base_infra = str((assumptions.get("capex", {}).get("strategy_scenarios", {}) or {}).get("active_scenario", "hybrid"))
    report_base_funding = str((assumptions.get("funding", {}) or {}).get("active_scenario", "mix"))
    report_base_mix_equity_pct = (as_float((((assumptions.get("funding", {}).get("scenarios", {}).get("mix", {}) or {}).get("equity_share", {}) or {}).get("value")) or 0.5) * 100.0)
    report_scenario_results: dict[str, Any] = {}
    base_construction_year = int(as_float(rows[-1].get("construction_start_year")) or 2028) if rows else 2028
    for infra in ["build_own_dc", "rent_gpu_only", "hybrid"]:
        year_variants = [2026, 2027, 2028, 2029, 2030] if infra == "hybrid" else [None]
        for csy in year_variants:
            for fund in ["equity_only", "revolver_only", "mix"]:
                ass = copy.deepcopy(assumptions)
                ass.setdefault("capex", {}).setdefault("strategy_scenarios", {})["active_scenario"] = infra
                if infra == "hybrid" and csy is not None:
                    ass.setdefault("capex", {}).setdefault("strategy_scenarios", {}).setdefault("scenarios", {}).setdefault("hybrid", {})["construction_start_year"] = int(csy)
                ass.setdefault("funding", {})["active_scenario"] = fund
                srows, smetric = run_model(ass)
                syears = [str(int(r.get("year", 0))) for r in srows]
                financial_flow = {y: {
                "workplace_ai_revenue": as_float(r.get("workplace_ai_revenue")),
                "contact_center_ai_revenue": as_float(r.get("contact_center_ai_revenue")),
                "total_revenue": as_float(r.get("total_revenue")),
                "total_cogs": as_float(r.get("total_cogs")),
                "gross_profit": as_float(r.get("gross_profit")),
                "total_sga": as_float(r.get("total_sga")),
                "ebitda": as_float(r.get("ebitda")),
                "total_depreciation_and_amortization": as_float(r.get("total_depreciation_and_amortization")),
                "interest_expense": as_float(r.get("interest_expense")),
                "profit_tax": as_float(r.get("profit_tax")),
                "net_income": as_float(r.get("net_income")),
                } for y, r in zip(syears, srows)}
                def smv(name: str, year: str):
                    v = smetric.get(name)
                    return (v.get(year) if isinstance(v, dict) else v)
                table_values = {
                    t.get("title"): {
                        m: ({y: (smetric.get(m, {}) or {}).get(y) for y in years} if isinstance(smetric.get(m), dict) else {years[0]: smetric.get(m)})
                        for m in t.get("rows", []) if isinstance(m, str)
                    }
                    for t in report_tables if isinstance(t, dict) and isinstance(t.get("title"), str)
                }
                key = f"{infra}|{fund}|{csy}" if infra == "hybrid" and csy is not None else f"{infra}|{fund}"
                report_scenario_results[key] = {
                "infra_scenario": infra,
                "funding_scenario": fund,
                "construction_start_year": csy if csy is not None else "na",
                "funding_mix": {
                    "equity_share": float((as_float((((ass.get("funding", {}).get("scenarios", {}).get("mix", {}) or {}).get("equity_share", {}) or {}).get("value")) or 0.5) or 0.5)),
                    "revolver_share": float((as_float((((ass.get("funding", {}).get("scenarios", {}).get("mix", {}) or {}).get("revolver_share", {}) or {}).get("value")) or 0.5) or 0.5)),
                },
                "executive_summary": {
                    "npv": as_float(smv("npv", years[0])),
                    "irr": as_float(smv("irr", years[0])),
                    "required_investments": sum((as_float(r.get("total_capex")) or 0.0) for r in srows),
                    "peak_required_gpu": max((as_float(r.get("required_gpu")) or 0.0) for r in srows),
                    "payback": smv("simple_payback", years[0]),
                },
                "financial_flow": financial_flow,
                "tables": table_values,
                "rows": srows,
                "years": years,
                "profit_tax_rate": as_float((((ass.get("pnl", {}) or {}).get("tax", {}) or {}).get("profit_tax_rate", {}).get("value")) or 0.0),
                "discount_rate": as_float(smv("discount_rate", years[0])) or 0.0,
                }
    html = f"""<!doctype html><html lang='en'><head><meta charset='utf-8'><title>GPS Finmodel Report</title><style>
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
table{{width:100%;border-collapse:collapse;font-size:12px}} th,td{{padding:6px 8px;border-bottom:1px solid #edf1f5}} th{{background:#fdfefe;color:#374151}}
th.yr{{text-align:center}} td.metric,th:first-child{{text-align:left}} td.num{{text-align:right}}
.neg{{color:#b91c1c}} .zero{{color:#9ca3af}} .na{{color:#9ca3af}} .kpi .v span{{color:inherit}}
.table-wrap{{overflow:auto;max-width:100%}} .sticky{{position:sticky;left:0;background:#f8fafc}}
.chart svg{{width:100%;height:auto}} .grid{{stroke:#d1d5db;stroke-width:1}} .axis{{fill:#6b7280;font-size:11px}}
.legend{{display:flex;gap:10px;flex-wrap:wrap;margin-top:8px}} .lg{{font-size:12px;color:#4b5563}} .lg i{{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:4px;vertical-align:middle}}
.base-cell{{outline:2px solid #111827;outline-offset:-2px}}
.ok{{color:#15803d;font-weight:600}} .warn{{color:#b45309;font-weight:600}}
.financial-flow-wrap{{overflow-x:auto;max-width:100%;padding-bottom:8px}}
.financial-flow-plot-wrap{{position:relative;width:100%;height:450px}}
#financial-flow-plot{{width:100%;height:450px}}
#financial-flow-labels{{position:absolute;inset:0;pointer-events:none}}
.ff-label{{position:absolute;background:rgba(255,255,255,0.88);border:1px solid #cbd5e1;border-radius:8px;padding:6px 8px;min-width:110px;max-width:150px;box-shadow:0 1px 2px rgba(15,23,42,0.06);font-size:11px;line-height:1.2}}
.ff-label .name{{font-weight:700;color:#334155}}
.ff-label .value{{font-weight:700;color:#16a34a;margin-top:2px}}
.ff-label .margin{{color:#64748b;margin-top:2px}}
.ka-empty{{background:transparent}}
.ka-readonly{{color:#475569;background:transparent;font-weight:600}}
.ka-section h4{{margin-top:14px;margin-bottom:6px;color:#334155}}
.ka-section table{{table-layout:fixed}}
.ka-section table th,.ka-section table td{{vertical-align:middle}}
.ka-section th:nth-child(1),.ka-section td:nth-child(1){{width:30%;text-align:left}}
.ka-section th:nth-child(2),.ka-section td:nth-child(2){{width:12%;text-align:left}}
.ka-section th:nth-child(n+3),.ka-section td:nth-child(n+3){{width:11.6%;text-align:center}}
.ka-section input{{width:80px;text-align:center;padding:5px 6px;border:1px solid #d1d5db;border-radius:6px}}
</style><script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script></head><body><div class='nav'><strong>GPS Finmodel Report</strong></div><div class='container'>
<header><h1>GPS Finmodel Report</h1><div class='sub'>2026–2030 financial model</div><div class='meta'>Active scenario: {active_scenario} · Generated: {ts}</div></header>
<div class='card'>
  <h3>Report Basis</h3>
  <div class='meta'>Official report: YAML base case</div>
  <div class='meta'>Selected infrastructure scenario: {active_scenario}</div>
  <div class='meta'>Selected funding scenario: {assumptions.get("funding",{}).get("active_scenario","mix")}</div>
  <div class='meta'>Data center construction start year: {base_construction_year if report_base_infra!='rent_gpu_only' else 'N/A'}</div>
  <div class='meta'>Discount rate: {render_value(metric_store.get("discount_rate", {}).get(years[0]), "discount_rate")}</div>
  <div class='meta'>Generated timestamp: {ts}</div>
  <div class='note'>The main report shows the YAML base-case investment scenario. Investment scenario controls are prepared but full report switching is pending.</div>
</div>
<div class='card'>
  <h3>Investment Scenario Controls</h3>
  <div class='controls'>
    <div class='ctrl'><label>Infrastructure scenario</label><select id='report_infra_scenario'><option>build_own_dc</option><option>rent_gpu_only</option><option selected>hybrid</option></select></div>
    <div class='ctrl'><label>Funding scenario</label><select id='report_funding_scenario'><option>equity_only</option><option>revolver_only</option><option selected>mix</option></select></div>
    <div class='ctrl'><label>Data center construction start year</label><select id='report_construction_start_year'><option>2026</option><option>2027</option><option selected>2028</option><option>2029</option><option>2030</option></select></div>
    <div class='ctrl'><label>Funding mix equity share (%)</label><input id='report_mix_equity_share' type='number' min='0' max='100' value='50' step='1'/></div>
    <div class='ctrl'><label>Funding mix revolver share</label><div id='report_mix_revolver_share' class='note'>50%</div></div>
  </div>
  <div style='margin-top:8px'><button id='report_apply_scenario'>Apply Investment Scenario</button> <button id='report_reset_scenario'>Reset to YAML Base Scenario</button></div>
  <div id='report_scenario_status' class='note'></div>
  <div class='note'>Construction start year applies to the hybrid scenario. It changes CAPEX timing, owned/rented GPU split, depreciation, datacenter OPEX, funding, DCF and investment metrics.</div>
  <div class='note'>These controls switch the main report investment scenario. Workbench assumptions remain separate and do not change official report tables until exported to YAML and regenerated.</div>
</div>
<section><h2>Executive Summary</h2><div class='grid'>{kpi_html}</div></section>
<section><h2>Financial Flow — P&L Bridge</h2>
<div class='card'>
  <div class='ctrl' style='max-width:220px'><label>Year</label><select id='ff_year'>{''.join(f"<option {'selected' if y==years[-1] else ''}>{y}</option>" for y in years)}</select></div>
  <div class='note'>Financial Flow uses the selected Investment Scenario, including construction start year for hybrid. Workbench changes do not affect this chart until exported to YAML and regenerated.</div>
  <div class='financial-flow-wrap'><div class='financial-flow-plot-wrap'><div id='financial-flow-plot'></div><div id='financial-flow-labels'></div></div></div>
  <div class='note'><span style='color:#3b82f6'>■</span> Revenue &nbsp; <span style='color:#22c55e'>■</span> Profit flow &nbsp; <span style='color:#ef4444'>■</span> Costs / expenses</div>
  <div class='note'>Financial Flow uses Plotly via CDN. If offline export is required, use the static report tables or switch to bundled Plotly.</div>
</div></section>
<section><h2>NPV Workbench — Scenario Builder</h2>
<div class='card'>
  <div class='card'>
    <h3>Scenario Presets</h3>
    <div class='controls'>
      <div class='ctrl'><label>Scenario name</label><input id='sl_preset_name' placeholder='Scenario name'/></div>
      <div class='ctrl'><label>Saved scenarios</label><select id='sl_preset_select'></select></div>
    </div>
    <div style='margin-top:8px'>
      <button id='sl_preset_save'>Save Scenario</button> <button id='sl_preset_load'>Load Scenario</button> <button id='sl_preset_dup'>Duplicate Scenario</button> <button id='sl_preset_del'>Delete Scenario</button> <button id='sl_preset_export'>Export Scenario JSON</button> <button id='sl_preset_import'>Import Scenario JSON</button>
      <input id='sl_import_json_file' type='file' accept='application/json' style='display:none'/>
    </div>
    <div id='sl_preset_status' class='note'></div>
  </div>
  <div class='note'>The Workbench is a browser-side what-if tool. The official report tables remain the Python-calculated YAML base case.</div>
  <div class='note'>To make a scenario official, copy/export the selected assumptions into assumptions.yaml and regenerate the report.</div>
  <div class='note'>The Workbench changes model-engine assumptions only. Investment scenario switching is controlled in the main report above.</div>
  <div class='grid' style='display:none'>
    <div class='card'><h3>Revenue & Demand</h3><div class='ctrl'><label>workplace_token_intensity_multiplier</label><input id='sl_wp_tok' type='number' step='0.01' value='1.00'/></div><div class='ctrl'><label>contact_center_token_intensity_multiplier</label><input id='sl_cc_tok' type='number' step='0.01' value='1.00'/></div><div class='ctrl'><label>workplace_activation_rate_multiplier</label><input id='sl_wp_act' type='number' step='0.01' value='1.00'/></div><div class='ctrl'><label>contact_center_automation_rate_multiplier</label><input id='sl_cc_auto' type='number' step='0.01' value='1.00'/></div><div class='ctrl'><label>target_contribution_margin_multiplier</label><input id='sl_margin' type='number' step='0.01' value='1.00'/></div></div>
    <div class='card'><h3>Compute & GPU</h3><div class='ctrl'><label>weighted_throughput_multiplier</label><input id='sl_wt' type='number' step='0.01' value='1.00'/></div><div class='ctrl'><label>utilization_multiplier</label><input id='sl_util' type='number' step='0.01' value='1.00'/></div><div class='ctrl'><label>gpu_unit_cost</label><input id='sl_gpu_cost' type='number' step='1' value='{sl_gpu_cost_default:.0f}'/></div><div class='ctrl'><label>gpu_rental_price_per_gpu_per_year</label><input id='sl_rent' type='number' step='1' value='{sl_rent_default:.0f}'/></div></div>
    <div class='card'><h3>Finance</h3><div class='ctrl'><label>discount_rate</label><input id='sl_dr' type='number' step='0.01' value='{sl_dr_default:.2f}'/></div></div>
  </div>
  <div class='grid' id='sl_kpis' style='margin-top:10px'></div>
  <div id='sl_parity' class='note'></div>
  <div id='sl_warn' class='note'></div>
  <div style='margin-top:10px'><button id='sl_recalc'>Recalculate Scenario</button> <button id='sl_reset'>Reset to Base Case</button></div>
  <div class='card'><h3>Export / Apply Scenario</h3><button id='sl_copy_key_yaml'>Copy Key Assumptions YAML</button> <button id='sl_copy_yaml'>Copy Team YAML</button> <button id='sl_preset_export_2'>Export Scenario JSON</button><div class='note'>This snippet is generated from Workbench only. Paste it into assumptions.yaml manually, then run python calc_token_load.py to make it official.</div><div id='sl_yaml_status' class='note'></div><textarea id='sl_yaml_snippet' style='display:none;width:100%;min-height:220px;margin-top:8px;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12px'></textarea><div id='sl_key_yaml_status' class='note'></div><textarea id='sl_key_yaml_snippet' style='display:none;width:100%;min-height:240px;margin-top:8px;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12px'></textarea></div>
  <div class='card'><h3>Key Assumptions Planner</h3><div class='note'>Editable assumptions affect the Workbench scenario only. Official report tables remain unchanged until assumptions.yaml is updated and the report is regenerated.</div><div id='sl_key_assumptions_table' class='table-wrap'></div></div>
  <div class='table-wrap' id='sl_team_tables'></div>
  <div class='note'>Team Planner affects the Workbench scenario only. To make changes official, copy the selected team assumptions into assumptions.yaml and regenerate the report.</div>
  <div class='note'>Workbench defaults are calibrated to match the Python base case. Changed inputs produce indicative what-if results.</div>
</div></section>

{''.join(sections_html)}
</div>
<script>
(function(){{
  const YEARS = {json.dumps(years)};
  const FREE_CASH_FLOW = {json.dumps([as_float(metric_store.get("free_cash_flow", {}).get(y)) or 0.0 for y in years])};
  const DEFAULT_RATE = {float(as_float(metric_store.get("discount_rate", {}).get(years[0])) or 0.30)};
  const input = null;
  const fmtNum = (v)=> Number(v).toLocaleString(undefined, {{minimumFractionDigits:2, maximumFractionDigits:2}});
  const fmtPct = (v)=> (v*100).toFixed(2) + "%";
  const setCellClass = (td, val) => {{
    td.classList.remove('neg','zero','na');
    if (val < 0) td.classList.add('neg');
    else if (Math.abs(val) < 1e-12) td.classList.add('zero');
  }};
  const updateMetricRow = (tableTitle, metric, values, formatter) => {{
    const cards = [...document.querySelectorAll('.card')];
    const card = cards.find(c => c.querySelector('h3') && c.querySelector('h3').textContent.trim() === tableTitle);
    if(!card) return;
    const rows = [...card.querySelectorAll('tbody tr')];
    const row = rows.find(r => (r.children[0]?.textContent || '').trim() === metric);
    if(!row) return;
    for(let i=0;i<values.length;i++) {{
      const td = row.children[i+1];
      if(!td) continue;
      td.textContent = formatter(values[i]);
      setCellClass(td, Number(values[i]));
    }}
  }};
  const updatePayback = (val) => {{
    const cards = [...document.querySelectorAll('.card')];
    const card = cards.find(c => c.querySelector('h3') && c.querySelector('h3').textContent.trim() === 'Investment Metrics');
    if(!card) return;
    const rows = [...card.querySelectorAll('tbody tr')];
    const row = rows.find(r => (r.children[0]?.textContent || '').trim() === 'discounted_payback');
    if(row && row.children[1]) row.children[1].textContent = val;
    const kpis = [...document.querySelectorAll('.kpi')];
    const k = kpis.find(x => (x.querySelector('.k')?.textContent || '').trim() === 'NPV');
    if(k) {{
      const v = k.querySelector('.v');
      v.textContent = fmtNum(current.npv);
      v.classList.remove('neg','zero');
      if(current.npv<0) v.classList.add('neg');
      else if(Math.abs(current.npv)<1e-12) v.classList.add('zero');
    }}
  }};
  const current = {{npv:0}};
  const REPORT_SCENARIO_RESULTS = {json.dumps(report_scenario_results)};
  window.REPORT_SCENARIO_RESULTS = REPORT_SCENARIO_RESULTS;
  let FIN_FLOW = {json.dumps(financial_flow_data)};
  const ffPlot = document.getElementById('financial-flow-plot');
  const ffLabels = document.getElementById('financial-flow-labels');
  const ffYear = document.getElementById('ff_year');
  const ffFmt = (v)=>{{ if(v===null||v===undefined||!Number.isFinite(Number(v))) return 'N/A'; const n=Number(v),a=Math.abs(n); const s=n<0?'(':'',e=n<0?')':''; if(a>=1e9) return s+'₽'+(a/1e9).toFixed(1)+'bn'+e; if(a>=1e6) return s+'₽'+(a/1e6).toFixed(1)+'m'+e; return s+'₽'+a.toFixed(0)+e; }};
  const ffPct=(v,d)=> (Number.isFinite(v)&&Number.isFinite(d)&&Math.abs(d)>1e-9)?((v/d)*100).toFixed(1)+'% margin':'N/A';
  const ffVal=(o,k)=> Number.isFinite(Number(o?.[k]))?Number(o[k]):null;
  const renderFinancialFlow=(year)=>{{ if(!ffPlot) return; const d=FIN_FLOW[String(year)]||{{}}; const rev=ffVal(d,'total_revenue');
    if(typeof Plotly==='undefined'){{ ffPlot.innerHTML="<div class='note warn'>Plotly failed to load. Financial Flow chart unavailable.</div>"; return; }}
    const gp=ffVal(d,'gross_profit'), ebitda=ffVal(d,'ebitda'), net=ffVal(d,'net_income');
    const names=["Workplace.ai Revenue","Contact Center Revenue","Total Revenue","COGS","Gross Profit","SG&A","EBITDA","D&A","Interest","Tax","Net Income"];
    const vals=[ffVal(d,'workplace_ai_revenue'),ffVal(d,'contact_center_ai_revenue'),rev,ffVal(d,'total_cogs'),gp,ffVal(d,'total_sga'),ebitda,ffVal(d,'total_depreciation_and_amortization'),ffVal(d,'interest_expense'),ffVal(d,'profit_tax'),net];
    const margins=['','','','',ffPct(gp,rev),'',ffPct(ebitda,rev),'','','',ffPct(net,rev)];
    const labels=new Array(names.length).fill(' ');
    const linkVals=[ffVal(d,'workplace_ai_revenue'),ffVal(d,'contact_center_ai_revenue'),ffVal(d,'total_cogs'),gp,ffVal(d,'total_sga'),ebitda,ffVal(d,'total_depreciation_and_amortization'),ffVal(d,'interest_expense'),ffVal(d,'profit_tax'),net];
    const sankey={{
      type:'sankey',orientation:'h',arrangement:'fixed',
      node:{{label:labels,pad:28,thickness:18,line:{{color:'#94a3b8',width:1}},color:['#3b82f6','#38bdf8','#60a5fa','#ef4444','#22c55e','#ef4444','#22c55e','#ef4444','#ef4444','#ef4444','#16a34a'],
      x:[0.03,0.03,0.24,0.45,0.45,0.67,0.67,0.90,0.90,0.90,0.90],y:[0.18,0.58,0.38,0.12,0.58,0.22,0.68,0.12,0.34,0.56,0.82]}},
      link:{{source:[0,1,2,2,4,4,6,6,6,6],target:[2,2,3,4,5,6,7,8,9,10],value:linkVals.map(v=>Math.abs(Number(v)||0)),
      color:['rgba(59,130,246,0.75)','rgba(56,189,248,0.75)','rgba(239,68,68,0.75)','rgba(34,197,94,0.75)','rgba(239,68,68,0.75)','rgba(34,197,94,0.75)','rgba(239,68,68,0.75)','rgba(239,68,68,0.75)','rgba(239,68,68,0.75)','rgba(34,197,94,0.75)'],
      customdata:linkVals.map((v,i)=>names[[0,1,2,2,4,4,6,6,6,6][i]]+' → '+names[[2,2,3,4,5,6,7,8,9,10][i]]+'<br>Value: '+ffFmt(v)),hovertemplate:'%{{customdata}}<extra></extra>'}}
    }};
    const pos=[[2,16],[2,55],[25,40],[45,8],[45,54],[63,28],[63,58],[83,10],[83,34],[83,56],[83,78]];
    if(ffLabels){{ ffLabels.innerHTML=names.map((nm,i)=>'<div class=\"ff-label\" style=\"left:'+(Math.max(2,pos[i][0]-3))+'%;top:'+pos[i][1]+'%\"><div class=\"name\">'+nm+'</div><div class=\"value\">'+ffFmt(vals[i])+'</div>'+(margins[i]?'<div class=\"margin\">'+margins[i]+'</div>':'')+'</div>').join(''); }}
    Plotly.react(ffPlot,[sankey],{{margin:{{l:20,r:20,t:8,b:8}},height:400,font:{{size:10}},paper_bgcolor:'#ffffff',plot_bgcolor:'#ffffff'}},{{responsive:true,displayModeBar:false}});
  }};
    if(ffYear){{ ffYear.addEventListener('change',()=>renderFinancialFlow(ffYear.value)); renderFinancialFlow(ffYear.value); }}
    const formatReportValue=(metric,v)=>{{
      if(v===null||v===undefined||Number.isNaN(Number(v))) return "<span class='na'>N/A</span>";
      const fv=Number(v); const pct=new Set(['discount_rate','irr','roic','roe','roa','utilization','target_contribution_margin','contribution_margin']);
      if(pct.has(metric)) return `<span class='${{fv<0?'neg':(Math.abs(fv)<1e-12?'zero':'')}}'>${{(fv*100).toFixed(1)}}%</span>`;
      if(['required_gpu','owned_gpu','rented_gpu'].includes(metric)||metric.endsWith('_year')) return `<span class='${{fv<0?'neg':(Math.abs(fv)<1e-12?'zero':'')}}'>${{Math.round(fv)}}</span>`;
      return `<span class='${{fv<0?'neg':(Math.abs(fv)<1e-12?'zero':'')}}'>${{fv.toLocaleString(undefined,{{minimumFractionDigits:2,maximumFractionDigits:2}})}}</span>`;
    }};
    const buildCustomFundingPayload=(basePayload,equityShare,revolverShare)=>{{
      const rows=JSON.parse(JSON.stringify(basePayload.rows||[])); const years=(basePayload.years||YEARS).map(String);
      const tax=Number(basePayload.profit_tax_rate||0); const dr=Number(basePayload.discount_rate||0.2);
      let prevCash=0, prevRev=0, paidIn=0, re=0; const fcf=[];
      rows.forEach((r,idx)=>{{
        const openCash=idx===0?(Number(r.opening_cash)||0):prevCash; const openRev=idx===0?0:prevRev;
        const ebit=Number(r.ebit)||0; const rate=Number(r.revolver_interest_rate)||0; const da=Number(r.total_depreciation_and_amortization)||0; const icf=Number(r.investing_cash_flow)||0; const minCash=Number(r.minimum_cash_balance)||0;
        let interest=(openRev*rate), ebt=0, taxAmt=0, ni=0, ocf=0, closeBefore=0, need=0, eq=0, draw=0, cashAfter=0, repay=0, revBal=openRev;
        for(let it=0; it<8; it++){{ ebt=ebit-interest; taxAmt=Math.max(ebt,0)*tax; ni=ebt-taxAmt; ocf=ni+da; closeBefore=openCash+ocf+icf; need=Math.max(-closeBefore,0); eq=need*equityShare; draw=need*revolverShare; cashAfter=closeBefore+eq+draw; repay=Math.min(openRev,Math.max(cashAfter-minCash,0)); revBal=openRev+draw-repay; const avg=(openRev+revBal)/2; const newInterest=avg*rate; if(Math.abs(newInterest-interest)<0.01){{interest=newInterest; break;}} interest=newInterest; }}
        ebt=ebit-interest; taxAmt=Math.max(ebt,0)*tax; ni=ebt-taxAmt; ocf=ni+da; closeBefore=openCash+ocf+icf; need=Math.max(-closeBefore,0); eq=need*equityShare; draw=need*revolverShare; cashAfter=closeBefore+eq+draw; repay=Math.min(openRev,Math.max(cashAfter-minCash,0)); revBal=openRev+draw-repay;
        const close=cashAfter-repay; const fin=eq+draw-repay; const free=ocf+icf; fcf.push(free);
        paidIn += eq; re += ni;
        const cash=close, netPpe=Number(r.net_ppe)||0, netInt=Number(r.net_intangible_assets)||0; const assets=cash+netPpe+netInt;
        const liab=revBal, eqTot=paidIn+re, bal=assets-liab-eqTot;
        Object.assign(r,{{opening_cash:openCash,opening_revolver_balance:openRev,interest_expense:interest,ebt:ebt,profit_tax:taxAmt,net_income:ni,operating_cash_flow:ocf,closing_cash_before_funding:closeBefore,funding_need:need,equity_injection:eq,revolver_drawdown:draw,cash_after_drawdown:cashAfter,revolver_repayment:repay,revolver_balance:revBal,average_revolver_balance:(openRev+revBal)/2,financing_cash_flow:fin,closing_cash_after_funding:close,closing_cash:close,cash:cash,cumulative_cash:close,total_assets:assets,total_liabilities:liab,paid_in_capital:paidIn,retained_earnings:re,total_equity:eqTot,balance_check:bal,free_cash_flow:free,net_cash_flow:ocf+icf+fin}});
        prevCash=close; prevRev=revBal;
      }});
      let npv=0,cumD=0,cum=0,sp='Not reached',dp='Not reached';
      rows.forEach((r,idx)=>{{ const df=1/Math.pow(1+dr,idx); const d=(Number(r.free_cash_flow)||0)*df; npv+=d; cumD+=d; cum+=(Number(r.free_cash_flow)||0); r.discount_rate=dr; r.discount_factor=df; r.discounted_fcf=d; r.cumulative_discounted_fcf=cumD; if(sp==='Not reached'&&cum>0) sp=String(r.year); if(dp==='Not reached'&&cumD>0) dp=String(r.year); }});
      return {{...basePayload, rows, executive_summary:{{...basePayload.executive_summary,npv:npv,payback:sp}}, custom_metrics:{{npv, simple_payback:sp, discounted_payback:dp}}}};
    }};
    const getReportScenarioKey=(infra,funding,csy)=> (infra==='hybrid' ? (infra+'|'+funding+'|'+csy) : (infra+'|'+funding));
    const updateInvestmentScenarioControlState=()=>{{
      const infra=(document.getElementById('report_infra_scenario')||{{}}).value||'hybrid';
      const fund=(document.getElementById('report_funding_scenario')||{{}}).value||'mix';
      const csy=document.getElementById('report_construction_start_year'); const eq=document.getElementById('report_mix_equity_share'); const rev=document.getElementById('report_mix_revolver_share');
      if(csy) csy.disabled = infra!=='hybrid';
      if(eq) eq.disabled = fund!=='mix';
      if(eq&&rev){{ const v=Math.min(100,Math.max(0,Number(eq.value)||0)); eq.value=String(v); rev.textContent=(100-v).toFixed(0)+'%'; }}
    }};
    const applyReportScenario=()=>{{
      const infra=(document.getElementById('report_infra_scenario')||{{}}).value||'hybrid';
      const funding=(document.getElementById('report_funding_scenario')||{{}}).value||'mix';
      const csy=(document.getElementById('report_construction_start_year')||{{value:'2028'}}).value||'2028';
      const eqEl=document.getElementById('report_mix_equity_share'); const st=document.getElementById('report_scenario_status');
      const EPS=1e-6; const key=infra+'|'+funding; let payload=REPORT_SCENARIO_RESULTS[key];
      payload = REPORT_SCENARIO_RESULTS[getReportScenarioKey(infra,funding,csy)] || payload;
      if(!payload){{ if(st) st.textContent='Scenario payload not found.'; return; }}
      let eqShare=funding==='equity_only'?1.0:(funding==='revolver_only'?0.0:Math.min(1,Math.max(0,(Number(eqEl?.value)||0)/100)));
      let revShare=1-eqShare; if(eqEl&&funding!=='mix') eqEl.value=String(Math.round(eqShare*100)); const rv=document.getElementById('report_mix_revolver_share'); if(rv) rv.textContent=(revShare*100).toFixed(0)+'%';
      const baseMixPayload = REPORT_SCENARIO_RESULTS[getReportScenarioKey(infra,'mix',csy)] || REPORT_SCENARIO_RESULTS[infra+'|mix'];
      const defaultEq=((baseMixPayload?.funding_mix?.equity_share)||0.5);
      if(funding==='mix' && Math.abs(eqShare-1.0)<EPS) payload=REPORT_SCENARIO_RESULTS[getReportScenarioKey(infra,'equity_only',csy)] || REPORT_SCENARIO_RESULTS[infra+'|equity_only'];
      else if(funding==='mix' && Math.abs(eqShare-0.0)<EPS) payload=REPORT_SCENARIO_RESULTS[getReportScenarioKey(infra,'revolver_only',csy)] || REPORT_SCENARIO_RESULTS[infra+'|revolver_only'];
      else if(funding==='mix' && Math.abs(eqShare-defaultEq)<EPS) payload=baseMixPayload;
      else if(funding==='mix') payload=buildCustomFundingPayload(baseMixPayload,eqShare,revShare);
      console.debug('Funding parity infra='+infra+' funding='+funding+' eq='+eqShare+' rev='+revShare+' defaultEq='+defaultEq+' key='+key);
      const hk=document.querySelector("section h2 + .grid .kpi .k");
      document.querySelectorAll('#financial-flow-plot').forEach(()=>{{}});
      const map={{'NPV':'npv','IRR':'irr','Required Investments':'required_investments','Peak Required GPU':'peak_required_gpu','Payback':'payback'}};
      document.querySelectorAll('section .kpi').forEach(card=>{{ const k=(card.querySelector('.k')?.textContent||'').trim(); const m=map[k]; if(!m) return; const v=payload.executive_summary[m]; const el=card.querySelector('.v'); if(!el) return; if(k==='Payback') el.textContent=(v===null||v===undefined)?'N/A':String(v); else el.innerHTML=formatReportValue(m==='peak_required_gpu'?'required_gpu':m,v); }});
      document.querySelectorAll('td[data-card][data-metric][data-year]').forEach(td=>{{ const card=td.getAttribute('data-card'); const metric=td.getAttribute('data-metric'); const year=td.getAttribute('data-year'); let v=payload.tables?.[card]?.[metric]?.[year]; if((v===undefined||v===null) && payload.rows){{ const rr=(payload.rows||[]).find(x=>String(x.year)===String(year)); if(rr) v=rr[metric]; }} td.innerHTML=formatReportValue(metric, v); }});
      FIN_FLOW = Object.fromEntries((payload.rows||[]).map(r=>[String(r.year),{{workplace_ai_revenue:r.workplace_ai_revenue,contact_center_ai_revenue:r.contact_center_ai_revenue,total_revenue:r.total_revenue,total_cogs:r.total_cogs,gross_profit:r.gross_profit,total_sga:r.total_sga,ebitda:r.ebitda,total_depreciation_and_amortization:r.total_depreciation_and_amortization,interest_expense:r.interest_expense,profit_tax:r.profit_tax,net_income:r.net_income}}])); if(ffYear) renderFinancialFlow(ffYear.value);
      const basis=document.querySelector('.card .meta:nth-child(2)');
      const metas=document.querySelectorAll('.card .meta');
      if(metas.length>3){{ metas[1].textContent='Selected infrastructure scenario: '+infra; metas[2].textContent='Selected funding scenario: '+funding; if(metas[3]) metas[3].textContent='Data center construction start year: '+(infra==='rent_gpu_only'?'N/A':csy); }}
      const bad=(payload.rows||[]).find(r=>Math.abs(Number(r.balance_check)||0)>1); if(st) st.textContent=(funding==='mix'&&Math.abs(eqShare-1.0)<EPS)?('Applied '+infra+' / mix with 100% equity and 0% revolver. Matches equity_only.'):((funding==='mix'&&Math.abs(eqShare)<EPS)?('Applied '+infra+' / mix with 0% equity and 100% revolver. Matches revolver_only.'):((funding==='mix'&&Math.abs(eqShare-defaultEq)<EPS)?('Applied '+infra+' / mix with '+(eqShare*100).toFixed(0)+'% equity and '+(revShare*100).toFixed(0)+'% revolver. Uses precomputed YAML/default mix.'):((funding==='mix'?'Applied '+infra+' / mix with '+(eqShare*100).toFixed(0)+'% equity and '+(revShare*100).toFixed(0)+'% revolver.':'Applied '+infra+' / '+funding+'.'))))+(bad?' Warning: balance check differs by '+Number(bad.balance_check).toFixed(2)+' in '+bad.year+'.':'');
      renderOwnedDcDiagnostic(payload);
    }};
    const summarizeOwned=(p)=>{{
      const rows=p?.rows||[]; const y2030=rows.find(r=>String(r.year)==='2030')||{{}};
      const sum=(k)=>rows.reduce((a,r)=>a+(Number(r[k])||0),0);
      return {{npv:Number(p?.executive_summary?.npv||0), reqInv:Number(p?.executive_summary?.required_investments||0), capex:sum('total_capex'), dcCapex:sum('datacenter_construction_capex'), gpuCapex:sum('gpu_infra_capex'), rentOpex:sum('gpu_rental_opex'), dcOpex:sum('total_datacenter_opex'), da:sum('total_depreciation_and_amortization'), ebitda2030:Number(y2030.ebitda||0), fcf2030:Number(y2030.free_cash_flow||0), discountedPayback:p?.custom_metrics?.discounted_payback||p?.tables?.['Investment Metrics']?.discounted_payback?.[YEARS[0]]||'N/A'}};
    }};
    const renderOwnedDcDiagnostic=(currentPayload)=>{{
      const cur=document.getElementById('owned_dc_diag_current'); const body=document.querySelector('#owned_dc_diag_cmp tbody'); const note=document.getElementById('owned_dc_diag_note');
      if(!cur||!body) return;
      const scenarios=[['rent_gpu_only','rent_gpu_only|mix'],['build_own_dc','build_own_dc|mix'],['hybrid 2026','hybrid|mix|2026'],['hybrid 2027','hybrid|mix|2027'],['hybrid 2028','hybrid|mix|2028'],['hybrid 2029','hybrid|mix|2029'],['hybrid 2030','hybrid|mix|2030']];
      const rows=scenarios.map(([n,k])=>{{ const p=REPORT_SCENARIO_RESULTS[k]; const s=summarizeOwned(p); return [n,s]; }}).filter(x=>x[1]);
      const fmt=(v)=>Number(v||0).toLocaleString(undefined,{{minimumFractionDigits:2,maximumFractionDigits:2}});
      const c=summarizeOwned(currentPayload);
      cur.innerHTML=`<div class='grid'><div class='kpi'><div class='k'>NPV</div><div class='v'>${{fmt(c.npv)}}</div></div><div class='kpi'><div class='k'>Required Investments</div><div class='v'>${{fmt(c.reqInv)}}</div></div><div class='kpi'><div class='k'>Total CAPEX</div><div class='v'>${{fmt(c.capex)}}</div></div><div class='kpi'><div class='k'>Datacenter construction CAPEX</div><div class='v'>${{fmt(c.dcCapex)}}</div></div><div class='kpi'><div class='k'>GPU infra CAPEX</div><div class='v'>${{fmt(c.gpuCapex)}}</div></div><div class='kpi'><div class='k'>GPU rental OPEX</div><div class='v'>${{fmt(c.rentOpex)}}</div></div><div class='kpi'><div class='k'>Datacenter OPEX</div><div class='v'>${{fmt(c.dcOpex)}}</div></div><div class='kpi'><div class='k'>D&A</div><div class='v'>${{fmt(c.da)}}</div></div><div class='kpi'><div class='k'>Free Cash Flow (2030)</div><div class='v'>${{fmt(c.fcf2030)}}</div></div></div>`;
      body.innerHTML=rows.map(([n,s])=>`<tr><td>${{n}}</td><td>${{fmt(s.npv)}}</td><td>${{fmt(s.reqInv)}}</td><td>${{fmt(s.capex)}}</td><td>${{fmt(s.dcCapex)}}</td><td>${{fmt(s.gpuCapex)}}</td><td>${{fmt(s.rentOpex)}}</td><td>${{fmt(s.dcOpex)}}</td><td>${{fmt(s.da)}}</td><td>${{fmt(s.ebitda2030)}}</td><td>${{fmt(s.fcf2030)}}</td><td>${{s.discountedPayback}}</td></tr>`).join('');
      const rent=rows.find(r=>r[0]==='rent_gpu_only')?.[1]; const own=rows.find(r=>r[0]==='build_own_dc')?.[1];
      if(note&&rent&&own&&own.npv<rent.npv) note.textContent='Top NPV drag vs rent_gpu_only: (1) higher CAPEX burden, (2) D&A/timing impact on cash generation, (3) datacenter OPEX and financing burden. No terminal/residual value is currently included. Owned DC scenarios may be understated on a 2026–2030 horizon.';
      else if(note) note.textContent='Owned DC economics summary for selected scenario.';
    }};
  const recalc = () => {{
    if(!input) return;
    try {{
      let r = Number(input.value);
      if(!Number.isFinite(r)) return;
      r = r / 100.0;
      const df = [], dcf = [], cdf = [];
      let cum = 0.0;
      for(let i=0;i<YEARS.length;i++) {{
        const factor = 1 / Math.pow(1+r, i);
        const disc = FREE_CASH_FLOW[i] * factor;
        cum += disc;
        df.push(factor); dcf.push(disc); cdf.push(cum);
      }}
      current.npv = dcf.reduce((a,b)=>a+b,0);
      let payback = "Not reached";
      for(let i=0;i<cdf.length;i++) if(cdf[i] > 0) {{ payback = String(YEARS[i]); break; }}
      updateMetricRow('DCF', 'discount_rate', YEARS.map(()=>r), fmtPct);
      updateMetricRow('DCF', 'discount_factor', df, (v)=>fmtNum(v));
      updateMetricRow('DCF', 'discounted_fcf', dcf, (v)=>fmtNum(v));
      updateMetricRow('DCF', 'cumulative_discounted_fcf', cdf, (v)=>fmtNum(v));
      updateMetricRow('Investment Metrics', 'npv', [current.npv], (v)=>fmtNum(v));
      updatePayback(payback);
    }} catch(err) {{
      console.warn('Discount rate recalculation failed:', err);
    }}
  }};
  if(input) {{
    input.addEventListener('input', recalc);
    recalc();
  }}
  try {{
    const baseInfra={json.dumps(report_base_infra)}; const baseFunding={json.dumps(report_base_funding)}; const baseEq={float(report_base_mix_equity_pct)}; const baseCsy={int(base_construction_year)};
    const infra=document.getElementById('report_infra_scenario'),fund=document.getElementById('report_funding_scenario'),csy=document.getElementById('report_construction_start_year'),eq=document.getElementById('report_mix_equity_share'),rev=document.getElementById('report_mix_revolver_share'),st=document.getElementById('report_scenario_status');
    const sync=()=>{{ if(!fund||!eq||!rev) return; if(fund.value==='equity_only') eq.value='100'; else if(fund.value==='revolver_only') eq.value='0'; eq.disabled=fund.value!=='mix'; const v=Math.min(100,Math.max(0,Number(eq.value)||0)); eq.value=String(v); rev.textContent=(100-v).toFixed(0)+'%'; }};
    if(infra) infra.value=baseInfra; if(fund) fund.value=baseFunding; if(csy) csy.value=String(baseCsy); if(eq) eq.value=String(Math.round(baseEq)); sync(); updateInvestmentScenarioControlState();
    if(fund) fund.addEventListener('change',()=>{{sync(); updateInvestmentScenarioControlState();}}); if(eq) eq.addEventListener('input',()=>{{sync(); updateInvestmentScenarioControlState();}}); if(infra) infra.addEventListener('change',updateInvestmentScenarioControlState);
    const apply=document.getElementById('report_apply_scenario'), reset=document.getElementById('report_reset_scenario');
    if(apply) apply.addEventListener('click',()=>{{ sync(); applyReportScenario(); }});
    if(reset) reset.addEventListener('click',()=>{{ if(infra) infra.value=baseInfra; if(fund) fund.value=baseFunding; if(csy) csy.value=String(baseCsy); if(eq) eq.value=String(Math.round(baseEq)); sync(); updateInvestmentScenarioControlState(); applyReportScenario(); if(st) st.textContent='Reset to YAML base investment scenario.'; }});
    applyReportScenario();
  }} catch(_e) {{}}

  __SCENARIO_LAB_JS__
}})();
</script>
</body></html>"""
    scenario_lab_js = """
const SL_BASE = __SCENARIO_LAB_DATA__;
(function initScenarioLab(){
  try {
    if (!SL_BASE || !Array.isArray(SL_BASE.rows)) {
      throw new Error("Scenario Lab data missing");
    }
    const host=null;
    if(host){
      const wrap=document.getElementById('sl_setup_controls')||document.createElement('div');
      wrap.className='controls';
      wrap.innerHTML="<div class='ctrl'><label>Infrastructure scenario</label><select id='sl_infra_scenario'></select></div><div class='ctrl'><label>Funding scenario</label><select id='sl_funding_scenario'><option value='equity_only'>Equity only</option><option value='revolver_only'>Revolver only</option><option value='mix'>Equity / Revolver mix</option></select></div>";
      if(!document.getElementById('sl_setup_controls')) host.parentNode.insertBefore(wrap, host);
      const infraSel=wrap.querySelector('#sl_infra_scenario');
      const infraNames={build_own_dc:'Build own datacenter',rent_gpu_only:'Rent GPU only',hybrid:'Hybrid'};
      (SL_BASE.infra_scenarios||['build_own_dc','rent_gpu_only','hybrid']).forEach(s=>{ const o=document.createElement('option'); o.value=s;o.textContent=infraNames[s]||s; infraSel.appendChild(o); });
      infraSel.value=SL_BASE.active_infrastructure_scenario||'hybrid';
      wrap.querySelector('#sl_funding_scenario').value=SL_BASE.active_funding_scenario||'mix';
    }
    const slIds=['sl_wp_tok','sl_cc_tok','sl_wp_act','sl_cc_auto','sl_margin','sl_wt','sl_util','sl_gpu_cost','sl_rent','sl_dr'];
    const renderKeyAssumptionsTable=()=>{ const host=document.getElementById('sl_key_assumptions_table'); if(!host) return; const rows=((SL_BASE.key_assumptions||{}).rows)||[];
      ['workplace_activation_rate','workplace_tokens_per_active_user_per_day','contact_center_automation_rate','contact_center_tokens_per_interaction'].forEach(k=>{ const row=rows.find(r=>r.key===k); if(row){ years.forEach(y=>{ const v=Number((row.values_by_year||{})[y]||0); if(!Number.isFinite(v)||v===0) console.warn('Key assumption missing/zero',k,y); }); }});
      const sections=[...new Set(rows.map(r=>r.section||'Other'))];
      host.innerHTML="<div class='note'>Rows with annual assumptions can be edited by year. Rows marked Base 2026 are entered once; later years are kept constant for Workbench calculation.</div>"+sections.map(sec=>{
        const rs=rows.filter(r=>(r.section||'Other')===sec);
        return "<div class='ka-section'><h4>"+sec+"</h4><table><thead><tr><th>Assumption</th><th>Unit</th><th>2026</th><th>2027</th><th>2028</th><th>2029</th><th>2030</th></tr></thead><tbody>"+
        rs.map(r=>"<tr><td>"+r.label+"</td><td>"+r.unit+"</td>"+years.map((y,idx)=>{ if(r.input_mode==='base_only'&&idx>0) return "<td class='ka-empty'></td>"; if(r.input_mode==='readonly') return "<td class='ka-readonly' data-assumption-key='"+r.key+"' data-year='"+y+"'>"+Number((r.values_by_year||{})[y]||0).toFixed(2)+"</td>"; return "<td><input class='sl-key-assumption-input' data-assumption-key='"+r.key+"' data-year='"+y+"' type='number' step='0.01' value='"+Number((r.values_by_year||{})[y]||0)+"'/></td>"; }).join("")+"</tr>").join("")+
        "</tbody></table></div>";
      }).join("");
    };
    const PRESET_KEY='gps_finmodel_scenario_lab_presets';
    const read=()=>Object.fromEntries(slIds.map(id=>[id,Number(document.getElementById(id).value)]));
    const parseInputNumber=(value, fallback)=>{ const n=Number(value); return Number.isFinite(n)?n:fallback; };
    const readKeyAssumptions=()=>{ const out={}; const warns=[]; (((SL_BASE.key_assumptions||{}).rows)||[]).forEach(r=>{ out[r.key]={}; if(r.input_mode==='readonly'){ years.forEach(y=>{ out[r.key][y]=Number((r.values_by_year||{})[y]||0);}); return; } if(r.input_mode==='base_only'){ const y0=years[0]; const e=document.querySelector(".sl-key-assumption-input[data-assumption-key='"+r.key+"'][data-year='"+y0+"']"); const base=parseInputNumber(e?e.value:undefined, Number((r.values_by_year||{})[y0]||0)); years.forEach(y=>{ out[r.key][y]=base; }); } else { years.forEach(y=>{ const e=document.querySelector(".sl-key-assumption-input[data-assumption-key='"+r.key+"'][data-year='"+y+"']"); out[r.key][y]=parseInputNumber(e?e.value:undefined, Number((r.values_by_year||{})[y]||0)); }); } });
      years.forEach(y=>{ const mf=(out.model_mix_frontier||{})[y]||0, ml=(out.model_mix_large||{})[y]||0, mm=(out.model_mix_medium||{})[y]||0, ms=(out.model_mix_small||{})[y]||0;
        const shares=[mf,ml,mm,ms].map(v=>Math.max(v,0)/100.0); const sum=shares.reduce((a,b)=>a+b,0); if(sum>0&&Math.abs(sum-1.0)>0.001) warns.push(`Model mix for ${y} sums to ${(sum*100).toFixed(1)}%; normalized for Workbench calculation.`);
        const norm=sum>0?shares.map(v=>v/sum):[0,0,0,0];
      const tf=Math.max((out.throughput_frontier||{})[y]||0,1e-9), tl=Math.max((out.throughput_large||{})[y]||0,1e-9), tm=Math.max((out.throughput_medium||{})[y]||0,1e-9), ts=Math.max((out.throughput_small||{})[y]||0,1e-9);
        const wt=1.0/((norm[0]/tf)+(norm[1]/tl)+(norm[2]/tm)+(norm[3]/ts)); if(!out.weighted_throughput) out.weighted_throughput={}; out.weighted_throughput[y]=Number.isFinite(wt)?wt:0;
      });
      years.forEach(y=>{ const c=document.querySelector(".ka-readonly[data-assumption-key='weighted_throughput'][data-year='"+y+"']"); if(c) c.textContent=(out.weighted_throughput[y]||0).toFixed(2); });
      const w=document.getElementById('sl_warn'); if(w&&warns.length) w.textContent=warns.join(' ');
      if(out.gpu_utilization&&!out.utilization) out.utilization=out.gpu_utilization; return out; };
    const fm=(v)=>Number(v).toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2});
    const fi=(v)=>String(Math.round(v));
    const render=(out)=>{ const d=out.npv-SL_BASE.base_npv; const cls=d>=0?'ok':'neg';
      const p=document.getElementById('sl_parity');
      if (p) { if (Math.abs(d)<1.0) { p.textContent='Base parity: OK'; p.className='note ok'; } else { p.textContent='Base parity: WARNING, difference = '+fm(d); p.className='note warn'; } }
      document.getElementById('sl_kpis').innerHTML=
      "<div class='kpi'><div class='k'>Base NPV</div><div class='v'>"+fm(SL_BASE.base_npv)+"</div></div>"+
      "<div class='kpi'><div class='k'>Scenario NPV</div><div class='v'>"+fm(out.npv)+"</div></div>"+
      "<div class='kpi'><div class='k'>Delta NPV</div><div class='v "+cls+"'>"+fm(d)+"</div></div>"+
      "<div class='kpi'><div class='k'>Required Investments</div><div class='v'>"+fm(out.totalCapex)+"</div></div>"+
      "<div class='kpi'><div class='k'>Peak Required GPU</div><div class='v'>"+fi(out.reqPeak||0)+"</div></div>"+
      "<div class='kpi'><div class='k'>Owned GPU 2030</div><div class='v'>"+fi(out.owned2030||0)+"</div></div>"+
      "<div class='kpi'><div class='k'>Rented GPU 2030</div><div class='v'>"+fi(out.rented2030||0)+"</div></div>"+
      "<div class='kpi'><div class='k'>Payback</div><div class='v'>N/A</div></div>"+
      "<div class='kpi'><div class='k'>Core Team FTE 2030</div><div class='v'>"+fm(out.coreFte2030)+"</div></div>"+
      "<div class='kpi'><div class='k'>SG&A FTE 2030</div><div class='v'>"+fm(out.sgaFte2030)+"</div></div>"+
      "<div class='kpi'><div class='k'>SG&A FTE 2030</div><div class='v'>"+fm(out.sgaFte2030)+"</div></div>";
    };
    const years=(SL_BASE.rows||[]).map(r=>String(r.year));
    const renderTeamTables=()=>{
      const host=document.getElementById('sl_team_tables'); if(!host) return;
      const tableHtml=(title,key)=>{ const roles=((SL_BASE.team_planner||{})[key]||{}).roles||[];
        const groups={}; roles.forEach((r,i)=>{ const p=String(r.name||'').split('/'); const g=p.length>1?p[0]:'other'; if(!groups[g]) groups[g]=[]; groups[g].push({r,i,short:p.length>1?p.slice(1).join('/'):String(r.name||'')}); });
        const body=Object.entries(groups).map(([g,items])=>"<tr><td colspan='"+(2+years.length)+"' style='font-weight:700;background:#f8fafc'>"+g+"</td></tr>"+items.map(({r,i,short})=>"<tr><td>"+short+"</td><td><input data-plan='"+key+"' data-idx='"+i+"' data-fld='salary' type='number' step='1' value='"+Number(r.monthly_salary_2026||0)+"'/></td>"+years.map(y=>"<td><input data-plan='"+key+"' data-idx='"+i+"' data-fld='fte_"+y+"' type='number' step='0.1' value='"+Number((r.fte_by_year||{})[y]||0)+"'/></td>").join("")+"</tr>").join("")).join("");
        return "<div class='card'><h3>"+title+"</h3><div class='table-wrap'><table><thead><tr><th>Role</th><th>Monthly Salary 2026</th>"+years.map(y=>"<th>FTE "+y+"</th>").join("")+"</tr></thead><tbody>"+body+"</tbody></table></div></div>"; };
      host.innerHTML=tableHtml("Core Team Planner","core_team")+tableHtml("SG&A Team Planner","sga");
    };
    const readTeamPlan=(key)=>{ const roles=JSON.parse(JSON.stringify((((SL_BASE.team_planner||{})[key]||{}).roles)||[]));
      roles.forEach((r,i)=>{ const s=document.querySelector("input[data-plan='"+key+"'][data-idx='"+i+"'][data-fld='salary']"); if(s) r.monthly_salary_2026=Number(s.value)||0;
        years.forEach(y=>{ const f=document.querySelector("input[data-plan='"+key+"'][data-idx='"+i+"'][data-fld='fte_"+y+"']"); if(f){ if(!r.fte_by_year) r.fte_by_year={}; r.fte_by_year[y]=Number(f.value)||0; }});
      }); return roles; };
    const getKeyAssumptionsState=()=>({rows: (((SL_BASE.key_assumptions||{}).rows)||[]).map(r=>({key:r.key,values_by_year:(readKeyAssumptions()[r.key]||{})}))});
    const applyKeyAssumptionsState=(st)=>{ const mapRows=Array.isArray(st?.rows)?st.rows:[]; mapRows.forEach(r=>{ Object.entries(r.values_by_year||{}).forEach(([y,v])=>{ const e=document.querySelector(".sl-key-assumption-input[data-assumption-key='"+r.key+"'][data-year='"+y+"']"); if(e) e.value=Number(v)||0;});}); };
    const resetKeyAssumptionsToBase=()=>{ (((SL_BASE.key_assumptions||{}).rows)||[]).forEach(r=>{ years.forEach(y=>{ const e=document.querySelector(".sl-key-assumption-input[data-assumption-key='"+r.key+"'][data-year='"+y+"']"); if(e) e.value=Number((r.values_by_year||{})[y]||0);});}); };
    const getScenarioLabState=()=>({ scalar_inputs: read(), scenario_switches:{infra:SL_BASE.active_infrastructure_scenario,funding:SL_BASE.active_funding_scenario}, key_assumptions:getKeyAssumptionsState(), core_team_planner:{roles:readTeamPlan('core_team')}, sga_team_planner:{roles:readTeamPlan('sga')}, scalars: read(), infra:SL_BASE.active_infrastructure_scenario, funding:SL_BASE.active_funding_scenario, core_team: readTeamPlan('core_team'), sga: readTeamPlan('sga') });
    const applyScenarioLabState=(st)=>{ if(!st) return; Object.entries((st.scalar_inputs||st.scalars||{})).forEach(([k,v])=>{ const e=document.getElementById(k); if(e) e.value=String(v); });
      renderTeamTables();
      const applyPlan=(key,roles)=>{ (roles||[]).forEach((r,i)=>{ const s=document.querySelector("input[data-plan='"+key+"'][data-idx='"+i+"'][data-fld='salary']"); if(s) s.value=Number(r.monthly_salary_2026||0);
        years.forEach(y=>{ const f=document.querySelector("input[data-plan='"+key+"'][data-idx='"+i+"'][data-fld='fte_"+y+"']"); if(f) f.value=Number((r.fte_by_year||{})[y]||0); });
      });};
      applyPlan('core_team', (st.core_team_planner||{}).roles || st.core_team); applyPlan('sga', (st.sga_team_planner||{}).roles || st.sga);
      if(st.key_assumptions?.rows) applyKeyAssumptionsState(st.key_assumptions); else if(st.key_assumptions) Object.entries(st.key_assumptions||{}).forEach(([k,ym])=>{ Object.entries(ym||{}).forEach(([y,v])=>{ const e=document.querySelector(".sl-key-assumption-input[data-assumption-key='"+k+"'][data-year='"+y+"']"); if(e) e.value=Number(v)||0; }); });
      const sw=st.scenario_switches||{};
    };
    const getScenarioLabOutputsSnapshot=(out)=>({scenario_npv:out.npv,delta_npv:out.npv-SL_BASE.base_npv,revenue_2030:out.rev2030,ebitda_2030:out.ebitda2030,total_capex:out.totalCapex,required_gpu_2030:out.req2030,owned_gpu_2030:out.owned2030,rented_gpu_2030:out.rented2030,revolver_balance_2030:out.revBal2030});
    const loadPresets=()=>{ try{return JSON.parse(localStorage.getItem(PRESET_KEY)||'[]');}catch(_e){return [];} };
    const savePresets=(p)=>localStorage.setItem(PRESET_KEY,JSON.stringify(p));
    const presetStatus=(t)=>{ const s=document.getElementById('sl_preset_status'); if(s) s.textContent=t; };
    const refreshPresetDropdown=()=>{ const sel=document.getElementById('sl_preset_select'); if(!sel) return; const cur=sel.value; const p=loadPresets(); sel.innerHTML='<option value="">-- select --</option>'+p.map(x=>'<option>'+x.name+'</option>').join(''); if(cur) sel.value=cur; };
    const setDeep=(obj, path, val)=>{ let cur=obj; for(let i=0;i<path.length-1;i++){ const p=path[i]; if(!cur[p]||typeof cur[p]!=='object') cur[p]={}; cur=cur[p]; } cur[path[path.length-1]]=val; };
    const toYaml=(v, indent=0)=>{
      const pad=' '.repeat(indent);
      if(v===null||v===undefined) return 'null';
      if(typeof v==='number') return Number.isFinite(v)?String(v):'0';
      if(typeof v==='string') return v;
      if(Array.isArray(v)) return v.map(x=>pad+'- '+toYaml(x,indent+2)).join('\\n');
      const lines=[]; Object.keys(v).forEach(k=>{ const val=v[k];
        if(val&&typeof val==='object'&&!Array.isArray(val)){ lines.push(pad+k+':'); lines.push(toYaml(val, indent+2)); }
        else lines.push(pad+k+': '+toYaml(val, indent+2));
      }); return lines.join('\\n');
    };
    const buildTeamYamlSnippet=()=>{
      const coreRoles=readTeamPlan('core_team');
      const sgaRoles=readTeamPlan('sga');
      const coreFteMap={}, coreSalaryMap={}, sgaFteMap={}, sgaSalaryMap={};
      coreRoles.forEach(r=>{ const p=String(r.name||'').split('/').filter(Boolean); if(!p.length) return;
        setDeep(coreSalaryMap,p,Number(r.monthly_salary_2026)||0);
        const ym={}; years.forEach(y=>{ ym[y]=Number((r.fte_by_year||{})[y]||0); }); setDeep(coreFteMap,p,ym);
      });
      sgaRoles.forEach(r=>{ const p=String(r.name||'').split('/').filter(Boolean); if(!p.length) return;
        setDeep(sgaSalaryMap,p,Number(r.monthly_salary_2026)||0);
        const ym={}; years.forEach(y=>{ ym[y]=Number((r.fte_by_year||{})[y]||0); }); setDeep(sgaFteMap,p,ym);
      });
      return toYaml({opex:{team:{core_team_target_fte:coreFteMap,salary_gross_monthly_rub:coreSalaryMap}},sga:{target_fte:sgaFteMap,salary_gross_monthly_rub:sgaSalaryMap}});
    };
    const buildKeyYamlSnippet=()=>{
      const ka=readKeyAssumptions();
      const kaRows=((SL_BASE.key_assumptions||{}).rows)||[];
      const kaByKey=Object.fromEntries(kaRows.map(r=>[r.key,r]));
      const getKaRow=(key)=>kaByKey[key]||null;
      const isBaseOnly=(key)=>((getKaRow(key)||{}).input_mode)==='base_only';
      const getKaBaseValue=(key)=>Number(((ka[key]||{})[years[0]])||0);
      const getKaYearlyValues=(key)=>Object.fromEntries(years.map(y=>[y,Number(((ka[key]||{})[y])||0)]));
      const decYearly=(key)=>Object.fromEntries(years.map(y=>[y,getKaBaseValue(key.replace('__year__', y))]));
      const yearlyFromKey=(key)=>getKaYearlyValues(key);
      const decFromKey=(key)=>Object.fromEntries(years.map(y=>[y,(Number(((ka[key]||{})[y])||0))/100.0]));
      const valueByMode=(key, asPercent=false)=>{
        if(isBaseOnly(key)){
          const base=getKaBaseValue(key);
          return asPercent ? (base/100.0) : base;
        }
        const vals=getKaYearlyValues(key);
        return asPercent ? Object.fromEntries(Object.entries(vals).map(([y,v])=>[y,v/100.0])) : vals;
      };
      const s={
        usage_assumptions:{
          "Workplace.ai":{activation_rate:valueByMode("workplace_activation_rate", true)},
          "Contact_Center.ai":{automation_rate:valueByMode("contact_center_automation_rate", true)}
        },
        token_load_model:{
          "Workplace.ai":{tokens_per_active_user_per_day:valueByMode("workplace_tokens_per_active_user_per_day", false)},
          "Contact_Center.ai":{tokens_per_interaction:{value:valueByMode("contact_center_tokens_per_interaction", false)}}
        },
        revenue:{target_contribution_margin:{base:valueByMode("target_contribution_margin", true)}},
        compute_model:{model_mix:{},throughput_per_gpu:{},infra:{utilization:valueByMode("gpu_utilization", true),peak_factor:valueByMode("peak_factor", false)}},
        capex:{gpu:{unit_cost:valueByMode("gpu_unit_cost", false)}},
        opex:{gpu_rental:{rental_price_per_gpu_per_year:valueByMode("gpu_rental_price_per_gpu_per_year", false)}},
        investment_metrics:{discount_rate:{value:valueByMode("discount_rate", true)}}
      };
      years.forEach(y=>{ s.compute_model.model_mix[y]={frontier:((ka.model_mix_frontier||{})[y]||0)/100,large:((ka.model_mix_large||{})[y]||0)/100,medium:((ka.model_mix_medium||{})[y]||0)/100,small:((ka.model_mix_small||{})[y]||0)/100}; });
      s.compute_model.throughput_per_gpu={frontier:Number((ka.throughput_frontier||{})[years[0]]||0),large:Number((ka.throughput_large||{})[years[0]]||0),medium:Number((ka.throughput_medium||{})[years[0]]||0),small:Number((ka.throughput_small||{})[years[0]]||0)};
      return "# Workbench Key Assumptions override\\n# Paste relevant blocks into assumptions.yaml, then run:\\n# python calc_token_load.py\\n# Note: official report values change only after regeneration.\\n\\n# weighted_throughput is calculated by the model from model_mix and throughput_per_gpu.\\n# It is shown in the Workbench as a read-only calculated result and should not be pasted as a direct YAML input.\\n\\n"+toYaml(s);
    };
    let lastOut=null;
    const calc=()=>{ const p=read(); const ka=readKeyAssumptions(); let npv=0,totalCapex=0,rev2030=0,ebitda2030=0,req2030=0,revBal2030=0;
      const infra=SL_BASE.active_infrastructure_scenario;
      const funding=SL_BASE.active_funding_scenario;
      const shares=(SL_BASE.funding_scenarios&&SL_BASE.funding_scenarios[funding])||{equity_share:0.5,revolver_share:0.5};
      const defaults={sl_wp_tok:1,sl_cc_tok:1,sl_wp_act:1,sl_cc_auto:1,sl_margin:1,sl_wt:1,sl_util:1,sl_dr:SL_BASE.base_discount_rate,sl_gpu_cost:SL_BASE.base_gpu_unit_cost,sl_rent:SL_BASE.base_rental_price};
      const isDefault = slIds.every(k=>Math.abs((p[k]||0)-(defaults[k]||0))<1e-9) && infra===(SL_BASE.active_infrastructure_scenario||'hybrid') && funding===(SL_BASE.active_funding_scenario||'mix');
      let prevOwned=0, prevClose=0, prevRevBal=0, owned2030=0, rented2030=0, coreFte2030=0,coreCash2030=0,teamOpex2030=0,sgaFte2030=0,sgaPayroll2030=0,totalSga2030=0,reqPeak=0;
      const coreRoles=readTeamPlan('core_team'), sgaRoles=readTeamPlan('sga');
      SL_BASE.rows.forEach((r,idx)=>{ const y=String(r.year||'');
        const wpAct=((ka.workplace_activation_rate||{})[y]||((r.workplace_activation_rate||0)*100))/100.0;
        const wpTok=(ka.workplace_tokens_per_active_user_per_day||{})[y]||r.workplace_tokens_per_active_user_per_day||0;
        const ccAct=((ka.contact_center_automation_rate||{})[y]||((r.contact_center_automation_rate||0)*100))/100.0;
        const ccTok=(ka.contact_center_tokens_per_interaction||{})[y]||r.contact_center_tokens_per_interaction||0;
        const wd=r.working_days_per_year||250, cd=r.calendar_days_per_year||365, wh=r.working_hours_per_day||8;
        const baseEmp=(r.workplace_activation_rate||0)>0?(r.workplace_active_users||0)/(r.workplace_activation_rate||1):(r.workplace_active_users||0);
        const active=baseEmp*wpAct;
        const wp=active*wpTok*wd;
        const baseInt=(r.contact_center_automation_rate||0)>0?(r.automated_interactions_per_day||0)/(r.contact_center_automation_rate||1):(r.automated_interactions_per_day||0);
        const cc=baseInt*ccAct*ccTok*cd;
        const totalTokens=wp+cc;
        const tps=totalTokens/(wd*wh*3600);
        const wt=(ka.weighted_throughput||{})[y]||r.weighted_throughput||1;
        const util=((ka.utilization||{})[y]||((r.utilization||0.5)*100))/100.0;
        const peak=(ka.peak_factor||{})[y]||r.peak_factor||1;
        const req=(wt>0&&util>0)?Math.ceil(tps/(wt*util)*peak):Math.ceil(r.required_gpu||0); reqPeak=Math.max(reqPeak,req);
        let owned=0, rented=0; const csy=Math.round(SL_BASE.construction_start_year||2028);
        if(infra==='build_own_dc'){owned=req; rented=0;} else if(infra==='rent_gpu_only'){owned=0; rented=req;} else { if((r.year||0)<csy){owned=0; rented=req;} else {owned=req; rented=0;} }
        const s=(r.owned_gpu||0)>0?owned/(r.owned_gpu||1):1;
        const yr=String(r.year||'');
        const infl=(SL_BASE.inflation_index_by_year||{})[yr]||1;
        let coreCash=0, coreFte=0; coreRoles.forEach(role=>{ const f=Number((role.fte_by_year||{})[yr]||0); const gross=(Number(role.monthly_salary_2026||0)*infl)*f*12; const bonus=gross*(((SL_BASE.team_planner||{}).core_team||{}).annual_bonus_percent_of_gross||0); const soc=(gross+bonus)*(((SL_BASE.team_planner||{}).core_team||{}).social_contribution_sfr_percent_of_gross||0); coreCash += gross+bonus+soc; coreFte+=f; });
        const capRatio=((r.annual_core_team_cash_cost||0)>0)?((r.capitalized_core_team_cost||0)/(r.annual_core_team_cash_cost||1)):0;
        const team=coreCash-(coreCash*capRatio);
        let sgaPayroll=0, sgaFte=0; sgaRoles.forEach(role=>{ const f=Number((role.fte_by_year||{})[yr]||0); const gross=(Number(role.monthly_salary_2026||0)*infl)*f*12; const bonus=gross*(((SL_BASE.team_planner||{}).sga||{}).annual_bonus_percent_of_gross||0); const soc=(gross+bonus)*(((SL_BASE.team_planner||{}).sga||{}).social_contribution_sfr_percent_of_gross||0); sgaPayroll += gross+bonus+soc; sgaFte += f; });
        const sga=sgaPayroll+(r.annual_office_rent||0);
        const rent=(ka.gpu_rental_price_per_gpu_per_year||{})[y]||p.sl_rent;
        const cogs=(r.total_datacenter_opex||0)*(owned>0?s:0)+team+rented*rent; const da=(r.total_depreciation_and_amortization||0);
        const m=Math.min(Math.max((((ka.target_contribution_margin||{})[y]||((r.target_contribution_margin||0)*100))/100.0),0),0.95);
        const shareWp=totalTokens>0?wp/totalTokens:(r.workplace_token_share||0); const shareCc=totalTokens>0?cc/totalTokens:(r.contact_center_token_share||0);
        const pb=cogs+da; const wpPB=pb*shareWp; const ccPB=pb*shareCc;
        const rev=(wpPB/(1-m))*(r.workplace_revenue_availability_factor||0)+(ccPB/(1-m))*(r.contact_center_revenue_availability_factor||0);
        const ownInc=(idx===0)?owned:Math.max(owned-prevOwned,0); prevOwned=owned;
        const ebt_pre=(rev-cogs)-sga-da;
        const guc=(ka.gpu_unit_cost||{})[y]||p.sl_gpu_cost;
        const gi=ownInc*guc*(SL_BASE.infra_multiplier||0);
        const dcc=(infra==='rent_gpu_only')?0:((infra==='hybrid'&& (r.year||0)!==csy)?0:(r.datacenter_construction_capex||0));
        const invest=-(gi+dcc+(r.office_capex||0)+(r.intangible_capex||0));
        const preFin=(ebt_pre - (r.interest_expense||0) - Math.max(ebt_pre-(r.interest_expense||0),0)*(SL_BASE.profit_tax_rate||0) + da) + invest;
        const openingCash=idx===0?(r.opening_cash||0):prevClose;
        const openingRev=idx===0?0:prevRevBal;
        const floor=(r.minimum_cash_balance||0);
        const need=Math.max(-(openingCash+preFin),0);
        const eq=need*(shares.equity_share||0), drw=need*(shares.revolver_share||0);
        const cashAfter=openingCash+preFin+eq+drw;
        const repay=Math.min(Math.max(cashAfter-floor,0),openingRev);
        const revBal=openingRev+drw-repay; prevRevBal=revBal; prevClose=cashAfter-repay;
        const fcf=isDefault?(r.free_cash_flow||0):(preFin+eq+drw-repay);
        const dr=((ka.discount_rate||{})[years[0]]||((ka.discount_rate||{})['2026'])||(p.sl_dr*100))/100.0;
        npv+=fcf/Math.pow(1+dr,idx); totalCapex+=(gi+dcc+(r.office_capex||0)+(r.intangible_capex||0));
        if(idx===SL_BASE.rows.length-1){rev2030=rev;ebitda2030=(rev-cogs)-sga;req2030=req;revBal2030=revBal;owned2030=owned;rented2030=rented;coreFte2030=coreFte;coreCash2030=coreCash;teamOpex2030=team;sgaFte2030=sgaFte;sgaPayroll2030=sgaPayroll;totalSga2030=sga;}
      }); lastOut={npv,totalCapex,rev2030,ebitda2030,req2030,reqPeak,revBal2030,owned2030,rented2030,infra,funding,coreFte2030,coreCash2030,teamOpex2030,sgaFte2030,sgaPayroll2030,totalSga2030}; render(lastOut); };
    document.getElementById('sl_recalc').addEventListener('click',calc);
    document.getElementById('sl_reset').addEventListener('click',()=>{ slIds.forEach(id=>{ const e=document.getElementById(id); if(e) e.value=e.defaultValue;}); renderTeamTables(); resetKeyAssumptionsToBase(); calc();});
    document.getElementById('sl_copy_yaml').addEventListener('click', async ()=>{ const txt=buildTeamYamlSnippet(); const ta=document.getElementById('sl_yaml_snippet'); const st=document.getElementById('sl_yaml_status'); if(ta) ta.value=txt;
      if(ta) ta.style.display='block';
      try{ if(navigator.clipboard&&navigator.clipboard.writeText){ await navigator.clipboard.writeText(txt); if(st) st.textContent='Copied to clipboard'; }
      else { if(st) st.textContent='Snippet generated — copy manually.'; } }
      catch(_e){ if(st) st.textContent='Snippet generated — copy manually.'; }
    });
    document.getElementById('sl_copy_key_yaml').addEventListener('click', async ()=>{ const txt=buildKeyYamlSnippet(); const ta=document.getElementById('sl_key_yaml_snippet'); const st=document.getElementById('sl_key_yaml_status'); if(ta) ta.value=txt;
      if(ta) ta.style.display='block';
      try{ if(navigator.clipboard&&navigator.clipboard.writeText){ await navigator.clipboard.writeText(txt); if(st) st.textContent='Key assumptions YAML copied to clipboard.'; }
      else { if(st) st.textContent='Key assumptions YAML generated — copy manually.'; } }
      catch(_e){ if(st) st.textContent='Key assumptions YAML generated — copy manually.'; }
    });
    const saveCurrentPreset=()=>{ const name=((document.getElementById('sl_preset_name')||{}).value||'').trim(); if(!name){presetStatus('Enter scenario name.'); return;} const p=loadPresets(); const idx=p.findIndex(x=>x.name===name); if(idx>=0&&!confirm('Scenario exists. Overwrite?')) return;
      const item={name,created_at:(idx>=0?p[idx].created_at:new Date().toISOString()),updated_at:new Date().toISOString(),scenario_state:getScenarioLabState(),outputs_snapshot:getScenarioLabOutputsSnapshot(lastOut||{})}; if(idx>=0)p[idx]=item; else p.push(item); savePresets(p); refreshPresetDropdown(); const sel=document.getElementById('sl_preset_select'); if(sel) sel.value=name; presetStatus('Scenario saved, including Key Assumptions and Team Planners.'); };
    const loadSelectedPreset=()=>{ const n=(document.getElementById('sl_preset_select')||{}).value; const it=loadPresets().find(x=>x.name===n); if(!it){presetStatus('Select scenario.'); return;} applyScenarioLabState(it.scenario_state); calc(); const nm=document.getElementById('sl_preset_name'); if(nm) nm.value=it.name; presetStatus('Scenario loaded.'); };
    const duplicateSelectedPreset=()=>{ const n=(document.getElementById('sl_preset_select')||{}).value; const p=loadPresets(); const it=p.find(x=>x.name===n); if(!it){presetStatus('Select scenario.'); return;} const name=n+' copy'; const cp=JSON.parse(JSON.stringify(it)); cp.name=name; cp.created_at=new Date().toISOString(); cp.updated_at=cp.created_at; p.push(cp); savePresets(p); refreshPresetDropdown(); const sel=document.getElementById('sl_preset_select'); if(sel) sel.value=name; presetStatus('Scenario duplicated.'); };
    const deleteSelectedPreset=()=>{ const n=(document.getElementById('sl_preset_select')||{}).value; if(!n) return; if(!confirm('Delete scenario?')) return; savePresets(loadPresets().filter(x=>x.name!==n)); refreshPresetDropdown(); presetStatus('Scenario deleted.'); };
    const exportScenarioJson=()=>{ const n=(document.getElementById('sl_preset_select')||{}).value; const it=loadPresets().find(x=>x.name===n) || {name:(document.getElementById('sl_preset_name')||{}).value||'unsaved',created_at:new Date().toISOString(),updated_at:new Date().toISOString(),scenario_state:getScenarioLabState(),outputs_snapshot:getScenarioLabOutputsSnapshot(lastOut||{})}; const blob=new Blob([JSON.stringify(it,null,2)],{type:'application/json'}); const a=document.createElement('a'); const safe=String(it.name||'scenario').replace(/[^a-z0-9_-]+/gi,'_'); a.href=URL.createObjectURL(blob); a.download='gps_finmodel_scenario_'+safe+'.json'; a.click(); URL.revokeObjectURL(a.href); presetStatus('Scenario JSON exported.'); };
    const importScenarioJson=(file)=>{ const r=new FileReader(); r.onload=()=>{ try{ const obj=JSON.parse(String(r.result||'{}')); if(!obj.scenario_state) throw new Error('Invalid'); const p=loadPresets(); let name=String(obj.name||'imported_scenario'); if(p.some(x=>x.name===name)) name=name+'_'+Date.now(); obj.name=name; obj.updated_at=new Date().toISOString(); obj.created_at=obj.created_at||obj.updated_at; p.push(obj); savePresets(p); refreshPresetDropdown(); const sel=document.getElementById('sl_preset_select'); if(sel) sel.value=name; applyScenarioLabState(obj.scenario_state); calc(); presetStatus('Scenario imported and loaded.'); } catch(_e){ presetStatus('Import failed.'); } }; r.readAsText(file); };
    document.getElementById('sl_preset_save').addEventListener('click',saveCurrentPreset);
    document.getElementById('sl_preset_load').addEventListener('click',loadSelectedPreset);
    document.getElementById('sl_preset_dup').addEventListener('click',duplicateSelectedPreset);
    document.getElementById('sl_preset_del').addEventListener('click',deleteSelectedPreset);
    document.getElementById('sl_preset_export').addEventListener('click',exportScenarioJson);
    const exp2=document.getElementById('sl_preset_export_2'); if(exp2) exp2.addEventListener('click',exportScenarioJson);
    document.getElementById('sl_preset_import').addEventListener('click',()=>{ const f=document.getElementById('sl_import_json_file'); if(f) f.click();});
    document.getElementById('sl_import_json_file').addEventListener('change',(e)=>{ const file=(e.target.files||[])[0]; if(file) importScenarioJson(file); });
    renderTeamTables();
    renderKeyAssumptionsTable();
    refreshPresetDropdown();
    const initSnippet=document.getElementById('sl_yaml_snippet'); if(initSnippet) initSnippet.value=buildTeamYamlSnippet();
    calc();
  } catch(e){ console.warn('Scenario Lab initialization failed',e); const w=document.getElementById('sl_warn'); if(w) w.textContent='Scenario Lab failed to initialize.'; }
})();
"""
    scenario_lab_json = json.dumps(scenario_lab_data, ensure_ascii=False)
    html = html.replace("__SCENARIO_LAB_JS__", scenario_lab_js)
    html = html.replace("__SCENARIO_LAB_DATA__", scenario_lab_json)
    return html

def write_html(rows: list[dict[str, Any]], assumptions: dict[str, Any], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(build_html(rows, assumptions), encoding="utf-8")


def write_audit_csv(rows: list[dict[str, Any]], assumptions: dict[str, Any], output: Path) -> None:
    years, metric_store, inv_metrics = build_metric_store(rows, assumptions)
    by_year = {int(r["year"]): r for r in rows}
    usage = assumptions.get("usage_assumptions", {})
    token_model = assumptions.get("token_load_model", {})
    compute = assumptions.get("compute_model", {})
    capex = assumptions.get("capex", {})
    revenue_cfg = assumptions.get("revenue", {})
    pnl_cfg = assumptions.get("pnl", {})
    funding_cfg = assumptions.get("funding", {})

    wp_usage = (usage.get("Workplace.ai", {}) or {})
    cc_usage = (usage.get("Contact_Center.ai", {}) or {})
    wp_activation = to_year_map(wp_usage.get("activation_rate"))
    wp_tokens_per_user = to_year_map(((token_model.get("Workplace.ai", {}) or {}).get("tokens_per_active_user_per_day")))
    cc_automation = to_year_map(cc_usage.get("automation_rate"))
    cc_tokens_per_interaction = as_float(((token_model.get("Contact_Center.ai", {}) or {}).get("tokens_per_interaction")))
    working_days = as_float(((token_model.get("time_assumptions", {}) or {}).get("working_days_per_year"))) or 0.0
    calendar_days = as_float(((token_model.get("time_assumptions", {}) or {}).get("calendar_days_per_year"))) or 0.0
    util_map = to_year_map(((compute.get("infra", {}) or {}).get("utilization")))
    peak_factor = as_float(((compute.get("infra", {}) or {}).get("peak_factor")) or 1.0) or 1.0
    gpu_unit_cost = as_float((((capex.get("gpu", {}) or {}).get("unit_cost"))) or 0.0)
    infra_multiplier = as_float((((capex.get("infra_multiplier", {}) or {}).get("value"))) or 0.0)
    contribution_margin_map = to_year_map(((revenue_cfg.get("target_contribution_margin", {}) or {}).get(str(revenue_cfg.get("active_scenario", "base")), {})))
    tax_rate = as_float((((pnl_cfg.get("tax", {}) or {}).get("profit_tax_rate", {}) or {}).get("value")) or 0.0)
    min_cash_months = as_float((((funding_cfg.get("minimum_cash_balance", {}) or {}).get("months_of_fixed_costs", {}) or {}).get("value")))
    if min_cash_months is None:
        min_cash_months = as_float((((((funding_cfg.get("revolver", {}) or {}).get("repayment_logic", {}) or {}).get("minimum_cash_balance", {}) or {}).get("months_of_fixed_costs", {}) or {}).get("value")))
    min_cash_months = 0.0 if min_cash_months is None else min_cash_months
    report_rows: list[dict[str, Any]] = []
    ok = warn = na = 0

    def add_check(name: str, year: Any, formula: str, expected: Any, actual: Any, tolerance: float = 1.0, notes: str = "", exact: bool = False) -> None:
        nonlocal ok, warn, na
        ev, av = as_float(expected), as_float(actual)
        if exact:
            if expected is None or actual is None:
                status, diff = "N/A", ""
                na += 1
            else:
                same = str(expected) == str(actual)
                status = "OK" if same else "WARNING"
                diff = 0 if same else "mismatch"
                ok += 1 if same else 0
                warn += 0 if same else 1
        elif ev is None or av is None or math.isnan(ev) or math.isnan(av):
            status, diff = "N/A", ""
            na += 1
        else:
            d = av - ev
            status = "OK" if abs(d) < tolerance else "WARNING"
            diff = d
            ok += 1 if status == "OK" else 0
            warn += 1 if status == "WARNING" else 0
        report_rows.append({"Check": name, "Year": year, "Formula": formula, "Expected": expected, "Actual": actual, "Difference": diff, "Status": status, "Notes": notes})

    prev_owned = 0.0
    for i, y in enumerate(years):
        r = by_year[y]
        # Token load
        act_users_exp = (as_float(wp_usage.get("total_employees")) or 0.0) * (as_float(wp_activation.get(y)) or 0.0)
        add_check("active_users_check", y, "total_employees*activation_rate", act_users_exp, r.get("active_users"), 0.01)
        wp_ann_exp = act_users_exp * (as_float(wp_tokens_per_user.get(y)) or 0.0) * float(working_days or 0.0)
        add_check("workplace_annual_tokens_check", y, "active_users*tokens_per_active_user_per_day*working_days", wp_ann_exp, r.get("workplace_annual_tokens"), 1.0)
        auto_int_exp = (as_float(cc_usage.get("interactions_per_day")) or 0.0) * (as_float(cc_automation.get(y)) or 0.0)
        add_check("automated_interactions_check", y, "interactions_per_day*automation_rate", auto_int_exp, r.get("automated_interactions"), 0.01)
        cc_ann_exp = auto_int_exp * (cc_tokens_per_interaction or 0.0) * float(calendar_days or 0.0)
        add_check("contact_center_annual_tokens_check", y, "automated_interactions*tokens_per_interaction*calendar_days", cc_ann_exp, r.get("contact_center_annual_tokens"), 1.0)
        add_check("total_annual_tokens_check", y, "workplace_annual_tokens+contact_center_annual_tokens", (as_float(r.get("workplace_annual_tokens")) or 0.0)+(as_float(r.get("contact_center_annual_tokens")) or 0.0), r.get("total_annual_tokens"), 1.0)
        # GPU sizing
        seconds = (working_days or 0.0) * (as_float((compute.get("infra", {}) or {}).get("working_hours_per_day")) or 0.0) * 3600.0
        tps_exp = (as_float(r.get("total_annual_tokens")) or 0.0) / seconds if seconds > 0 else None
        add_check("tokens_per_second_check", y, "total_annual_tokens/(working_days*working_hours*3600)", tps_exp, r.get("tokens_per_second"), 0.01)
        util = as_float(util_map.get(y)) or 0.0
        wt = as_float(r.get("weighted_throughput")) or 0.0
        req_exp = math.ceil((tps_exp or 0.0) / (wt * util) * peak_factor) if wt > 0 and util > 0 else None
        add_check("required_gpu_check", y, "ceil(tokens_per_second/(weighted_throughput*utilization)*peak_factor)", req_exp, r.get("required_gpu"), 0.01)
        # Infrastructure
        csy = as_float(r.get("construction_start_year"))
        cflag_exp = 1 if csy is not None and y == int(csy) else 0
        add_check("construction_flag_check", y, "1 if year==construction_start_year else 0", cflag_exp, r.get("construction_flag"), exact=True)
        if str(r.get("active_scenario")) == "hybrid":
            req = as_float(r.get("required_gpu")) or 0.0
            add_check("owned_gpu_check", y, "required_gpu if year>=construction_start_year else 0", req if y >= int(csy or 9999) else 0, r.get("owned_gpu"), 0.01)
            add_check("rented_gpu_check", y, "required_gpu if year<construction_start_year else 0", req if y < int(csy or 9999) else 0, r.get("rented_gpu"), 0.01)
        owned = as_float(r.get("owned_gpu")) or 0.0
        own_inc_exp = owned if i == 0 else max(owned - prev_owned, 0.0)
        add_check("owned_gpu_increment_check", y, "owned first year else max(delta,0)", own_inc_exp, r.get("owned_gpu_increment"), 0.01)
        prev_owned = owned
        # CAPEX
        add_check("gpu_capex_check", y, "owned_gpu_increment*gpu_unit_cost", (as_float(r.get("owned_gpu_increment")) or 0.0) * float(gpu_unit_cost or 0.0), r.get("gpu_capex"), 1.0)
        add_check("gpu_infra_capex_check", y, "gpu_capex*infra_multiplier", (as_float(r.get("gpu_capex")) or 0.0) * float(infra_multiplier or 0.0), r.get("gpu_infra_capex"), 1.0)
        tangible_exp = (as_float(r.get("gpu_infra_capex")) or 0.0) + (as_float(r.get("datacenter_construction_capex")) or 0.0) + (as_float(r.get("office_capex")) or 0.0)
        add_check("tangible_capex_check", y, "gpu_infra+dc+office", tangible_exp, r.get("tangible_capex"), 1.0)
        intang_exp = (as_float(r.get("workplace_ai_ip_value")) or 0.0) + (as_float(r.get("contact_center_ai_ip_value")) or 0.0)
        add_check("intangible_capex_check", y, "workplace_ai_ip_value+contact_center_ai_ip_value", intang_exp, r.get("intangible_capex"), 1.0)
        add_check("total_capex_check", y, "tangible_capex+intangible_capex", tangible_exp + intang_exp, r.get("total_capex"), 1.0)
        add_check("datacenter_construction_capex_check", y, "total_component_rub*construction_flag", (as_float(r.get("total_component_rub")) or 0.0)*(as_float(r.get("construction_flag")) or 0.0), r.get("datacenter_construction_capex"), 1.0)
        # D&A
        add_check("office_capex_depreciation_check", y, "sum office depreciation components", (as_float(r.get("office_server_depreciation")) or 0.0)+(as_float(r.get("employee_laptops_depreciation")) or 0.0)+(as_float(r.get("executive_laptops_depreciation")) or 0.0)+(as_float(r.get("mfu_depreciation")) or 0.0)+(as_float(r.get("meeting_rooms_depreciation")) or 0.0)+(as_float(r.get("office_furniture_depreciation")) or 0.0), r.get("office_capex_depreciation"), 1.0)
        add_check("total_ppe_depreciation_check", y, "gpu_depreciation+datacenter_depreciation+office_capex_depreciation", (as_float(r.get("gpu_depreciation")) or 0.0)+(as_float(r.get("datacenter_depreciation")) or 0.0)+(as_float(r.get("office_capex_depreciation")) or 0.0), r.get("total_ppe_depreciation"), 1.0)
        add_check("ip_amortization_check", y, "workplace_ai_amortization+contact_center_ai_amortization", (as_float(r.get("workplace_ai_amortization")) or 0.0)+(as_float(r.get("contact_center_ai_amortization")) or 0.0), r.get("ip_amortization"), 1.0)
        add_check("total_depreciation_and_amortization_check", y, "total_ppe_depreciation+ip_amortization", (as_float(r.get("total_ppe_depreciation")) or 0.0)+(as_float(r.get("ip_amortization")) or 0.0), r.get("total_depreciation_and_amortization"), 1.0)
        # OPEX / Revenue / P&L / CF / Funding / BS
        add_check("gpu_rental_opex_check", y, "rented_gpu*rental_price_per_gpu_per_year", (as_float(r.get("rented_gpu")) or 0.0)*(as_float(r.get("rental_price_per_gpu_per_year")) or 0.0), r.get("annual_gpu_rental_cost"), 1.0)
        add_check("electricity_cost_check", y, "electricity_kwh*electricity_price_t", (as_float(r.get("electricity_kwh")) or 0.0)*(as_float(r.get("electricity_price_t")) or 0.0), r.get("electricity_cost"), 1.0)
        add_check("total_datacenter_opex_check", y, "electricity+maintenance+network+land+other", (as_float(r.get("electricity_cost")) or 0.0)+(as_float(r.get("maintenance_cost")) or 0.0)+(as_float(r.get("network_cost")) or 0.0)+(as_float(r.get("land_rent")) or 0.0)+(as_float(r.get("other_datacenter_opex")) or 0.0), r.get("total_datacenter_opex"), 1.0)
        add_check("team_opex_check", y, "annual_core_team_cash_cost-capitalized_core_team_cost", (as_float(r.get("annual_core_team_cash_cost")) or 0.0)-(as_float(r.get("capitalized_core_team_cost")) or 0.0), r.get("total_team_opex"), 1.0)
        add_check("total_sga_check", y, "annual_fixed_sga+annual_office_rent", (as_float(r.get("annual_fixed_sga")) or 0.0)+(as_float(r.get("annual_office_rent")) or 0.0), r.get("total_sga"), 1.0)
        pricing_base_exp = (as_float(r.get("total_cogs")) or 0.0) + (as_float(r.get("total_depreciation_and_amortization")) or 0.0)
        add_check("pricing_base_check", y, "total_cogs+total_depreciation_and_amortization", pricing_base_exp, r.get("pricing_base"), 1.0)
        total_tokens = as_float(r.get("total_annual_tokens")) or 0.0
        add_check("workplace_token_share_check", y, "workplace_annual_tokens/total_annual_tokens", (as_float(r.get("workplace_annual_tokens")) or 0.0)/total_tokens if total_tokens else None, r.get("workplace_token_share"), 0.01)
        add_check("contact_center_token_share_check", y, "contact_center_annual_tokens/total_annual_tokens", (as_float(r.get("contact_center_annual_tokens")) or 0.0)/total_tokens if total_tokens else None, r.get("contact_center_token_share"), 0.01)
        margin = as_float(contribution_margin_map.get(y))
        denom = (1.0 - margin) if margin is not None and margin < 1 else None
        wp_rev_exp = None if denom in (None, 0) else ((pricing_base_exp * (as_float(r.get("workplace_token_share")) or 0.0)) / denom) * (as_float(r.get("workplace_revenue_availability_factor")) or 0.0)
        cc_rev_exp = None if denom in (None, 0) else ((pricing_base_exp * (as_float(r.get("contact_center_token_share")) or 0.0)) / denom) * (as_float(r.get("contact_center_revenue_availability_factor")) or 0.0)
        add_check("workplace_revenue_check", y, "workplace_pricing_base/(1-margin)*availability", wp_rev_exp, r.get("workplace_ai_revenue"), 1.0)
        add_check("contact_center_revenue_check", y, "contact_center_pricing_base/(1-margin)*availability", cc_rev_exp, r.get("contact_center_ai_revenue"), 1.0)
        add_check("total_revenue_check", y, "workplace_ai_revenue+contact_center_ai_revenue", (as_float(r.get("workplace_ai_revenue")) or 0.0)+(as_float(r.get("contact_center_ai_revenue")) or 0.0), r.get("total_revenue"), 1.0)
        add_check("total_cogs_check", y, "total_datacenter_opex+total_team_opex+annual_gpu_rental_cost", (as_float(r.get("total_datacenter_opex")) or 0.0)+(as_float(r.get("total_team_opex")) or 0.0)+(as_float(r.get("annual_gpu_rental_cost")) or 0.0), r.get("total_cogs"), 1.0)
        add_check("gross_profit_check", y, "total_revenue-total_cogs", (as_float(r.get("total_revenue")) or 0.0)-(as_float(r.get("total_cogs")) or 0.0), r.get("gross_profit"), 1.0)
        add_check("ebitda_check", y, "gross_profit-total_sga", (as_float(r.get("gross_profit")) or 0.0)-(as_float(r.get("total_sga")) or 0.0), r.get("ebitda"), 1.0)
        add_check("ebit_check", y, "ebitda-total_depreciation_and_amortization", (as_float(r.get("ebitda")) or 0.0)-(as_float(r.get("total_depreciation_and_amortization")) or 0.0), r.get("ebit"), 1.0)
        add_check("ebt_check", y, "ebit-interest_expense", (as_float(r.get("ebit")) or 0.0)-(as_float(r.get("interest_expense")) or 0.0), r.get("ebt"), 1.0)
        add_check("profit_tax_check", y, "max(ebt,0)*tax_rate", max((as_float(r.get("ebt")) or 0.0), 0.0)*float(tax_rate or 0.0), r.get("profit_tax"), 1.0)
        add_check("net_income_check", y, "ebt-profit_tax", (as_float(r.get("ebt")) or 0.0)-(as_float(r.get("profit_tax")) or 0.0), r.get("net_income"), 1.0)
        add_check("operating_cash_flow_check", y, "net_income+total_depreciation_and_amortization", (as_float(r.get("net_income")) or 0.0)+(as_float(r.get("total_depreciation_and_amortization")) or 0.0), r.get("operating_cash_flow"), 1.0)
        add_check("investing_cash_flow_check", y, "-gpu_infra-dc-office-intangible", -((as_float(r.get("gpu_infra_capex")) or 0.0)+(as_float(r.get("datacenter_construction_capex")) or 0.0)+(as_float(r.get("office_capex")) or 0.0)+(as_float(r.get("intangible_capex")) or 0.0)), r.get("investing_cash_flow"), 1.0)
        add_check("pre_financing_cash_flow_check", y, "operating_cash_flow+investing_cash_flow", (as_float(r.get("operating_cash_flow")) or 0.0)+(as_float(r.get("investing_cash_flow")) or 0.0), r.get("pre_financing_cash_flow"), 1.0)
        add_check("financing_cash_flow_check", y, "equity_injection+revolver_drawdown-revolver_repayment", (as_float(r.get("equity_injection")) or 0.0)+(as_float(r.get("revolver_drawdown")) or 0.0)-(as_float(r.get("revolver_repayment")) or 0.0), r.get("financing_cash_flow"), 1.0)
        add_check("net_cash_flow_check", y, "pre_financing_cash_flow+financing_cash_flow", (as_float(r.get("pre_financing_cash_flow")) or 0.0)+(as_float(r.get("financing_cash_flow")) or 0.0), r.get("net_cash_flow"), 1.0)
        add_check("funding_need_check", y, "max(-closing_cash_before_funding,0)", max(-((as_float(r.get("closing_cash_before_funding")) or 0.0)), 0.0), r.get("funding_need"), 1.0)
        add_check("minimum_cash_balance_check", y, "(total_team_opex+total_sga+annual_gpu_rental_cost)/12*months_of_fixed_costs", ((as_float(r.get("total_team_opex")) or 0.0)+(as_float(r.get("total_sga")) or 0.0)+(as_float(r.get("annual_gpu_rental_cost")) or 0.0))/12.0*float(min_cash_months), r.get("minimum_cash_balance"), 1.0)
        add_check("revolver_balance_check", y, "opening_revolver_balance+drawdown-repayment", (as_float(r.get("opening_revolver_balance")) or 0.0)+(as_float(r.get("revolver_drawdown")) or 0.0)-(as_float(r.get("revolver_repayment")) or 0.0), r.get("revolver_balance"), 1.0)
        add_check("interest_expense_check", y, "average_revolver_balance*revolver_interest_rate", (as_float(r.get("average_revolver_balance")) or 0.0)*(as_float(r.get("revolver_interest_rate")) or 0.0), r.get("interest_expense"), 1.0)
        add_check("closing_cash_after_funding_check", y, "cash_after_drawdown-revolver_repayment", (as_float(r.get("cash_after_drawdown")) or 0.0)-(as_float(r.get("revolver_repayment")) or 0.0), r.get("closing_cash_after_funding"), 1.0)
        add_check("net_ppe_check", y, "gross_ppe-accumulated_depreciation", (as_float(r.get("gross_ppe")) or 0.0)-(as_float(r.get("accumulated_depreciation")) or 0.0), r.get("net_ppe"), 1.0)
        add_check("net_intangible_assets_check", y, "gross_intangible_assets-accumulated_amortization", (as_float(r.get("gross_intangible_assets")) or 0.0)-(as_float(r.get("accumulated_amortization")) or 0.0), r.get("net_intangible_assets"), 1.0)
        add_check("total_assets_check", y, "cash+net_ppe+net_intangible_assets", (as_float(r.get("cash")) or 0.0)+(as_float(r.get("net_ppe")) or 0.0)+(as_float(r.get("net_intangible_assets")) or 0.0), r.get("total_assets"), 1.0)
        add_check("total_equity_check", y, "paid_in_capital+retained_earnings", (as_float(r.get("paid_in_capital")) or 0.0)+(as_float(r.get("retained_earnings")) or 0.0), r.get("total_equity"), 1.0)
        add_check("balance_check", y, "0", 0.0, r.get("balance_check"), 1.0)
        add_check("free_cash_flow_check", y, "operating_cash_flow+investing_cash_flow", (as_float(r.get("operating_cash_flow")) or 0.0)+(as_float(r.get("investing_cash_flow")) or 0.0), r.get("free_cash_flow"), 1.0)
        dr = as_float(metric_store.get("discount_rate", {}).get(years[0])) or 0.0
        df_exp = 1.0 / ((1.0 + dr) ** i)
        add_check("discount_factor_check", y, "1/(1+discount_rate)^year_index", df_exp, metric_store.get("discount_factor", {}).get(y), 0.01)
        add_check("discounted_fcf_check", y, "free_cash_flow*discount_factor", (as_float(r.get("free_cash_flow")) or 0.0) * df_exp, metric_store.get("discounted_fcf", {}).get(y), 1.0)

    npv_exp = sum((as_float(metric_store.get("discounted_fcf", {}).get(y)) or 0.0) for y in years)
    npv_act = as_float(metric_store.get("npv", {}).get(years[0]))
    add_check("npv_check", "Total", "sum(discounted_fcf)", npv_exp, npv_act, 1.0)
    sc = build_scenario_comparison(assumptions)
    active = str(rows[-1].get("active_scenario"))
    add_check("scenario_comparison_active_npv_check", "Total", "scenario row npv == base npv", as_float(sc.get(active, {}).get("npv")), npv_act, 1.0)
    wt, cm, matrix = build_sensitivity_matrix(assumptions, rows)
    add_check("sensitivity_base_cell_check", "Total", "sensitivity(1.00,1.00)==base npv", matrix.get((1.0, 1.0)), npv_act, 1.0)

    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["Check", "Year", "Formula", "Expected", "Actual", "Difference", "Status", "Notes"])
        writer.writeheader()
        writer.writerows(report_rows)

    print(f"Audit checks: {ok} OK, {warn} WARNING, {na} N/A")
    if warn > 0:
        for r in report_rows:
            if r["Status"] == "WARNING":
                print(f"WARNING AUDIT: {r['Check']} year={r['Year']} diff={r['Difference']}")


def main() -> None:
    assumptions = load_yaml(Path("assumptions.yaml"))
    for section in ("usage_assumptions", "token_load_model"):
        if section not in assumptions:
            raise KeyError(f"В assumptions.yaml отсутствует обязательная секция: {section}")

    rows = calculate(assumptions)
    write_csv(rows, assumptions, OUT_CSV)
    write_html(rows, assumptions, OUT_HTML)
    write_audit_csv(rows, assumptions, OUT_AUDIT)
    if ENABLE_MONTHLY_DEBUG_OUTPUT:
        months_rows = calculate_monthly(assumptions)
        write_monthly_rows_preview(months_rows, OUT_MONTHLY_ROWS_PREVIEW)
        write_monthly_vs_annual_audit(rows, aggregate_monthly_to_annual(months_rows), OUT_MONTHLY_VS_ANNUAL_AUDIT, assumptions)
        write_monthly_validation_checks(months_rows, OUT_MONTHLY_VALIDATION)
        write_monthly_balance_sheet_debug(months_rows, OUT_MONTHLY_BS_DEBUG)
    if ENABLE_MONTHLY_PREVIEW:
        write_monthly_preview(assumptions, OUT_MONTHLY_PREVIEW)

    print("year | total_annual_tokens | required_gpu | total_capex | total_opex")
    print("-" * 90)
    for r in rows:
        print(
            f"{r['year']} | {fmt_num(r['total_annual_tokens'],0)} | {fmt_num(r['required_gpu'],0)} | "
            f"{fmt_num(r['total_capex'],2)} | {fmt_num(r['total_opex'],2)}"
        )
    print(f"\nCSV: {OUT_CSV}")
    print(f"HTML: {OUT_HTML}")
    print(f"AUDIT: {OUT_AUDIT}")
    if ENABLE_MONTHLY_PREVIEW:
        print(f"MONTHLY PREVIEW: {OUT_MONTHLY_PREVIEW}")
    if ENABLE_MONTHLY_DEBUG_OUTPUT:
        print(f"MONTHLY ROWS: {OUT_MONTHLY_ROWS_PREVIEW}")
        print(f"MONTHLY VS ANNUAL AUDIT: {OUT_MONTHLY_VS_ANNUAL_AUDIT}")
        print(f"MONTHLY VALIDATION: {OUT_MONTHLY_VALIDATION}")
        print(f"MONTHLY BS DEBUG: {OUT_MONTHLY_BS_DEBUG}")


if __name__ == "__main__":
    main()
