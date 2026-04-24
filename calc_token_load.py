#!/usr/bin/env python3
"""Расчет token-load модели по годам 2026–2030 на основе assumptions.yaml."""

from __future__ import annotations

from pathlib import Path
import sys


def _import_yaml():
    try:
        import yaml  # type: ignore
    except ModuleNotFoundError as exc:
        python = Path(sys.executable).name
        raise SystemExit(
            "Не найден пакет 'pyyaml'. Установите его в текущее окружение:\n"
            f"  {python} -m pip install pyyaml"
        ) from exc
    return yaml


YEARS = [2026, 2027, 2028, 2029, 2030]


def load_assumptions(path: Path) -> dict:
    yaml = _import_yaml()
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def compute_workplace_tokens(data: dict, year: int) -> int:
    usage = data["Usage_assumptions"]["Workplace.ai"]
    model = data["Token_load_model"]["Workplace.ai"]
    working_days = data["Token_load_model"]["time_assumptions"]["working_days_per_year"]

    total_employees = usage["total_employees"]
    activation_rate = usage["activation_rate"][year]
    tokens_per_user_day = model["tokens_per_active_user_per_day"][year]

    active_users = total_employees * activation_rate
    return int(active_users * tokens_per_user_day * working_days)


def compute_contact_center_tokens(data: dict, year: int) -> int:
    usage = data["Usage_assumptions"]["Contact_Center.ai"]
    calendar_days = data["Token_load_model"]["time_assumptions"]["calendar_days_per_year"]

    interactions_per_day = usage["interactions_per_day"]
    automation_rate = usage["automation_rate"][year]
    tokens_per_interaction = usage["tokens_per_interaction"]

    return int(interactions_per_day * automation_rate * tokens_per_interaction * calendar_days)


def main() -> None:
    assumptions = load_assumptions(Path("assumptions.yaml"))

    print("Год | Workplace.ai | Contact_Center.ai | Итого")
    print("-" * 72)

    for year in YEARS:
        wp_tokens = compute_workplace_tokens(assumptions, year)
        cc_tokens = compute_contact_center_tokens(assumptions, year)
        total_tokens = wp_tokens + cc_tokens

        print(f"{year} | {wp_tokens:,} | {cc_tokens:,} | {total_tokens:,}")


if __name__ == "__main__":
    main()
