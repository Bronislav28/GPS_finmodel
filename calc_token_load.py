#!/usr/bin/env python3
"""Расчет token-load модели по годам 2026–2030 и генерация HTML-отчета."""

from __future__ import annotations

from pathlib import Path
import json
import sys


YEARS = [2026, 2027, 2028, 2029, 2030]
OUTPUT_PATH = Path("output/gps_finmodel.html")


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


def build_results(data: dict) -> list[dict]:
    rows: list[dict] = []
    for year in YEARS:
        workplace_tokens = compute_workplace_tokens(data, year)
        contact_tokens = compute_contact_center_tokens(data, year)
        rows.append(
            {
                "year": year,
                "workplace_tokens": workplace_tokens,
                "contact_center_tokens": contact_tokens,
                "total_tokens": workplace_tokens + contact_tokens,
            }
        )
    return rows


def render_html(rows: list[dict]) -> str:
    rows_json = json.dumps(rows, ensure_ascii=False)
    return f"""<!doctype html>
<html lang="ru">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>GPS Finmodel — Token Load</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 24px; color: #1f2937; }}
    h1 {{ margin-bottom: 8px; }}
    .sub {{ margin: 0 0 20px; color: #6b7280; }}
    .controls {{
      display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 12px; margin-bottom: 20px;
    }}
    .control {{ border: 1px solid #e5e7eb; border-radius: 8px; padding: 12px; background: #f9fafb; }}
    label {{ display: block; font-weight: 600; margin-bottom: 6px; }}
    input {{ width: 100%; padding: 6px 8px; box-sizing: border-box; }}
    table {{ border-collapse: collapse; width: 100%; }}
    th, td {{ border: 1px solid #e5e7eb; padding: 8px; text-align: right; }}
    th:first-child, td:first-child {{ text-align: center; }}
    thead {{ background: #f3f4f6; }}
    tfoot {{ background: #f9fafb; font-weight: 700; }}
  </style>
</head>
<body>
  <h1>Token-load model (2026–2030)</h1>
  <p class="sub">Изменяйте параметры ниже — таблица пересчитывается в браузере без перезагрузки.</p>

  <div class="controls">
    <div class="control">
      <label for="growthRate">Growth rate, % в год</label>
      <input id="growthRate" type="number" step="0.1" value="0" />
    </div>
    <div class="control">
      <label for="wpCost">Cost assumption: Workplace ($ / 1M tokens)</label>
      <input id="wpCost" type="number" step="0.01" value="2.50" />
    </div>
    <div class="control">
      <label for="ccCost">Cost assumption: Contact Center ($ / 1M tokens)</label>
      <input id="ccCost" type="number" step="0.01" value="3.10" />
    </div>
  </div>

  <table>
    <thead>
      <tr>
        <th>Год</th>
        <th>Workplace.ai tokens</th>
        <th>Contact_Center.ai tokens</th>
        <th>Total tokens</th>
        <th>Total cost ($)</th>
      </tr>
    </thead>
    <tbody id="resultsBody"></tbody>
    <tfoot>
      <tr>
        <td>Итого</td>
        <td id="sumWp"></td>
        <td id="sumCc"></td>
        <td id="sumTotal"></td>
        <td id="sumCost"></td>
      </tr>
    </tfoot>
  </table>

  <script>
    const baseRows = {rows_json};

    const growthInput = document.getElementById('growthRate');
    const wpCostInput = document.getElementById('wpCost');
    const ccCostInput = document.getElementById('ccCost');
    const bodyEl = document.getElementById('resultsBody');

    const sumWp = document.getElementById('sumWp');
    const sumCc = document.getElementById('sumCc');
    const sumTotal = document.getElementById('sumTotal');
    const sumCost = document.getElementById('sumCost');

    const fmtInt = (n) => Math.round(n).toLocaleString('en-US');
    const fmtMoney = (n) => n.toLocaleString('en-US', {{ minimumFractionDigits: 2, maximumFractionDigits: 2 }});

    function recalc() {{
      const growthRate = (parseFloat(growthInput.value) || 0) / 100;
      const wpCostPer1M = parseFloat(wpCostInput.value) || 0;
      const ccCostPer1M = parseFloat(ccCostInput.value) || 0;

      let totalWp = 0;
      let totalCc = 0;
      let totalTokens = 0;
      let totalCost = 0;

      bodyEl.innerHTML = '';
      baseRows.forEach((row, idx) => {{
        const factor = Math.pow(1 + growthRate, idx);
        const wp = row.workplace_tokens * factor;
        const cc = row.contact_center_tokens * factor;
        const total = wp + cc;
        const cost = (wp / 1_000_000) * wpCostPer1M + (cc / 1_000_000) * ccCostPer1M;

        totalWp += wp;
        totalCc += cc;
        totalTokens += total;
        totalCost += cost;

        const tr = document.createElement('tr');
        tr.innerHTML = `
          <td>${{row.year}}</td>
          <td>${{fmtInt(wp)}}</td>
          <td>${{fmtInt(cc)}}</td>
          <td>${{fmtInt(total)}}</td>
          <td>${{fmtMoney(cost)}}</td>
        `;
        bodyEl.appendChild(tr);
      }});

      sumWp.textContent = fmtInt(totalWp);
      sumCc.textContent = fmtInt(totalCc);
      sumTotal.textContent = fmtInt(totalTokens);
      sumCost.textContent = fmtMoney(totalCost);
    }}

    [growthInput, wpCostInput, ccCostInput].forEach((el) => el.addEventListener('input', recalc));
    recalc();
  </script>
</body>
</html>
"""


def save_html(html: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")


def main() -> None:
    assumptions = load_assumptions(Path("assumptions.yaml"))
    rows = build_results(assumptions)

    print("Год | Workplace.ai | Contact_Center.ai | Итого")
    print("-" * 72)
    for row in rows:
        print(
            f"{row['year']} | {row['workplace_tokens']:,} | "
            f"{row['contact_center_tokens']:,} | {row['total_tokens']:,}"
        )

    html = render_html(rows)
    save_html(html, OUTPUT_PATH)
    print(f"\nHTML-отчет сохранен: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
