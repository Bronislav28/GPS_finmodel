#!/usr/bin/env python3
"""GPS finmodel YAML validator (issue #119 scope)."""

from __future__ import annotations

import csv
from dataclasses import dataclass
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


def main() -> int:
    assumptions = load_assumptions(ASSUMPTIONS_PATH)
    items = validate(assumptions)
    write_reports(items)

    errors = [x for x in items if x.level == "ERROR"]
    warnings = [x for x in items if x.level == "WARNING"]
    print(f"Validation completed. Errors: {len(errors)}, warnings: {len(warnings)}")
    print(f"TXT: {OUT_TXT}")
    print(f"CSV: {OUT_CSV}")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
