#!/usr/bin/env python3
"""Расчет token-load, GPU-потребности и CAPEX по годам 2026–2030."""

from __future__ import annotations

from pathlib import Path
import json
import math
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

    active_users = usage["total_employees"] * usage["activation_rate"][year]
    tokens_per_user_day = model["tokens_per_active_user_per_day"][year]
    return int(active_users * tokens_per_user_day * working_days)


def compute_contact_center_tokens(data: dict, year: int) -> int:
    usage = data["Usage_assumptions"]["Contact_Center.ai"]
    calendar_days = data["Token_load_model"]["time_assumptions"]["calendar_days_per_year"]

    interactions_per_day = usage["interactions_per_day"]
    automation_rate = usage["automation_rate"][year]
    tokens_per_interaction = usage["tokens_per_interaction"]
    return int(interactions_per_day * automation_rate * tokens_per_interaction * calendar_days)


def _weighted_throughput(model_mix: dict[str, float], throughput_per_gpu: dict[str, float]) -> float:
    denominator = 0.0
    for model_name, share in model_mix.items():
        if model_name not in throughput_per_gpu:
            raise KeyError(f"Нет throughput для модели '{model_name}'")
        denominator += share / throughput_per_gpu[model_name]
    if denominator <= 0:
        raise ValueError("Некорректный model_mix/throughput: делитель <= 0")
    return 1 / denominator


def _compute_required_gpu(total_tokens: float, year: int, data: dict) -> tuple[int, float, float, float]:
    time_cfg = data["Token_load_model"]["time_assumptions"]
    compute_cfg = data["compute_model"]

    working_days_per_year = time_cfg["working_days_per_year"]
    working_hours_per_day = compute_cfg["infra"]["working_hours_per_day"]
    utilization = compute_cfg["infra"]["utilization"][year]
    peak_factor = compute_cfg["infra"]["peak_factor"]

    model_mix = compute_cfg["model_mix"][year]
    throughput_per_gpu = compute_cfg["throughput_per_gpu"]

    seconds_per_year = working_days_per_year * working_hours_per_day * 3600
    tokens_per_second = total_tokens / seconds_per_year
    weighted_throughput = _weighted_throughput(model_mix, throughput_per_gpu)

    required_gpu_raw = tokens_per_second / (weighted_throughput * utilization) * peak_factor
    required_gpu = int(math.ceil(required_gpu_raw))

    return required_gpu, tokens_per_second, weighted_throughput, utilization


def build_results(data: dict) -> list[dict]:
    capex_cfg = data["capex"]

    gpu_unit_cost = capex_cfg["gpu_unit_cost_usd"]
    infra_cost_per_gpu = capex_cfg["infra_cost_per_gpu_usd"]
    platform_capex = capex_cfg["platform_capex_usd"]
    useful_life = int(capex_cfg["useful_life_years"])

    rows: list[dict] = []
    capex_history: list[float] = []
    previous_required_gpu = 0

    for year in YEARS:
        workplace_tokens = compute_workplace_tokens(data, year)
        contact_tokens = compute_contact_center_tokens(data, year)
        total_tokens = workplace_tokens + contact_tokens

        required_gpu, tokens_per_second, weighted_throughput, utilization = _compute_required_gpu(total_tokens, year, data)
        required_gpu_increment = max(0, required_gpu - previous_required_gpu)

        gpu_capex = required_gpu_increment * (gpu_unit_cost + infra_cost_per_gpu)
        year_platform_capex = platform_capex[year]
        total_capex = gpu_capex + year_platform_capex

        capex_history.append(total_capex)
        depreciation = sum(capex_history[-useful_life:]) / useful_life

        rows.append(
            {
                "year": year,
                "workplace_tokens": workplace_tokens,
                "contact_center_tokens": contact_tokens,
                "total_tokens": total_tokens,
                "tokens_per_second": tokens_per_second,
                "weighted_throughput": weighted_throughput,
                "utilization": utilization,
                "required_gpu": required_gpu,
                "required_gpu_increment": required_gpu_increment,
                "gpu_capex": gpu_capex,
                "platform_capex": year_platform_capex,
                "total_capex": total_capex,
                "depreciation": depreciation,
            }
        )

        previous_required_gpu = required_gpu

    return rows


def render_html(rows: list[dict], assumptions: dict) -> str:
    rows_json = json.dumps(rows, ensure_ascii=False)

    working_days = assumptions["Token_load_model"]["time_assumptions"]["working_days_per_year"]
    working_hours = assumptions["compute_model"]["infra"]["working_hours_per_day"]
    peak_factor = assumptions["compute_model"]["infra"]["peak_factor"]
    capex_cfg = assumptions["capex"]
    platform_capex_json = json.dumps(capex_cfg["platform_capex_usd"], ensure_ascii=False)

    return f"""<!doctype html>
<html lang="ru">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>GPS Finmodel — Token Load + CAPEX</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 24px; color: #1f2937; }}
    h1 {{ margin-bottom: 8px; }}
    .sub {{ margin: 0 0 20px; color: #6b7280; }}
    .controls {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(230px, 1fr)); gap: 12px; margin-bottom: 20px; }}
    .control {{ border: 1px solid #e5e7eb; border-radius: 8px; padding: 12px; background: #f9fafb; }}
    label {{ display: block; font-weight: 600; margin-bottom: 6px; }}
    input {{ width: 100%; padding: 6px 8px; box-sizing: border-box; }}
    table {{ border-collapse: collapse; width: 100%; font-size: 13px; }}
    th, td {{ border: 1px solid #e5e7eb; padding: 8px; text-align: right; }}
    th:first-child, td:first-child {{ text-align: center; }}
    thead {{ background: #f3f4f6; }}
    tfoot {{ background: #f9fafb; font-weight: 700; }}
  </style>
</head>
<body>
  <h1>Token-load + GPU CAPEX model (2026–2030)</h1>
  <p class="sub">Изменяйте параметры — required_gpu и CAPEX пересчитываются в браузере.</p>

  <div class="controls">
    <div class="control">
      <label for="growthRate">Growth rate, % в год</label>
      <input id="growthRate" type="number" step="0.1" value="0" />
    </div>
    <div class="control">
      <label for="workingHours">Working hours per day</label>
      <input id="workingHours" type="number" step="0.5" value="{working_hours}" />
    </div>
    <div class="control">
      <label for="peakFactor">Peak factor</label>
      <input id="peakFactor" type="number" step="0.05" value="{peak_factor}" />
    </div>
    <div class="control">
      <label for="gpuUnitCost">GPU unit cost, $</label>
      <input id="gpuUnitCost" type="number" step="100" value="{capex_cfg['gpu_unit_cost_usd']}" />
    </div>
    <div class="control">
      <label for="infraCost">Infra cost per GPU, $</label>
      <input id="infraCost" type="number" step="100" value="{capex_cfg['infra_cost_per_gpu_usd']}" />
    </div>
    <div class="control">
      <label for="usefulLife">Useful life, years</label>
      <input id="usefulLife" type="number" step="1" min="1" value="{capex_cfg['useful_life_years']}" />
    </div>
  </div>

  <table>
    <thead>
      <tr>
        <th>Год</th>
        <th>Total tokens</th>
        <th>Required GPU</th>
        <th>GPU increment</th>
        <th>GPU CAPEX ($)</th>
        <th>Platform CAPEX ($)</th>
        <th>Total CAPEX ($)</th>
        <th>Depreciation ($)</th>
      </tr>
    </thead>
    <tbody id="resultsBody"></tbody>
    <tfoot>
      <tr>
        <td>Итого</td>
        <td id="sumTokens"></td>
        <td id="sumGpu"></td>
        <td id="sumGpuInc"></td>
        <td id="sumGpuCapex"></td>
        <td id="sumPlatformCapex"></td>
        <td id="sumTotalCapex"></td>
        <td id="sumDep"></td>
      </tr>
    </tfoot>
  </table>

  <script>
    const baseRows = {rows_json};
    const platformCapexByYear = {platform_capex_json};
    const workingDaysPerYear = {working_days};

    const growthRateEl = document.getElementById('growthRate');
    const workingHoursEl = document.getElementById('workingHours');
    const peakFactorEl = document.getElementById('peakFactor');
    const gpuUnitCostEl = document.getElementById('gpuUnitCost');
    const infraCostEl = document.getElementById('infraCost');
    const usefulLifeEl = document.getElementById('usefulLife');
    const bodyEl = document.getElementById('resultsBody');

    const sumTokens = document.getElementById('sumTokens');
    const sumGpu = document.getElementById('sumGpu');
    const sumGpuInc = document.getElementById('sumGpuInc');
    const sumGpuCapex = document.getElementById('sumGpuCapex');
    const sumPlatformCapex = document.getElementById('sumPlatformCapex');
    const sumTotalCapex = document.getElementById('sumTotalCapex');
    const sumDep = document.getElementById('sumDep');

    const fmtInt = (n) => Math.round(n).toLocaleString('en-US');
    const fmtMoney = (n) => n.toLocaleString('en-US', {{ minimumFractionDigits: 2, maximumFractionDigits: 2 }});

    function recalc() {{
      const growthRate = (parseFloat(growthRateEl.value) || 0) / 100;
      const workingHours = parseFloat(workingHoursEl.value) || 1;
      const peakFactor = parseFloat(peakFactorEl.value) || 1;
      const gpuUnitCost = parseFloat(gpuUnitCostEl.value) || 0;
      const infraCost = parseFloat(infraCostEl.value) || 0;
      const usefulLife = Math.max(1, parseInt(usefulLifeEl.value || '1', 10));

      let prevGpu = 0;
      let capexHistory = [];

      let totalTokensAll = 0;
      let totalGpuAll = 0;
      let totalGpuIncAll = 0;
      let totalGpuCapexAll = 0;
      let totalPlatformCapexAll = 0;
      let totalCapexAll = 0;
      let totalDepAll = 0;

      bodyEl.innerHTML = '';

      baseRows.forEach((row, idx) => {{
        const factor = Math.pow(1 + growthRate, idx);
        const totalTokens = row.total_tokens * factor;

        const secondsPerYear = workingDaysPerYear * workingHours * 3600;
        const tokensPerSecond = totalTokens / secondsPerYear;
        const requiredGpuRaw = (tokensPerSecond / (row.weighted_throughput * row.utilization)) * peakFactor;
        const requiredGpu = Math.ceil(requiredGpuRaw);

        const gpuInc = Math.max(0, requiredGpu - prevGpu);
        const gpuCapex = gpuInc * (gpuUnitCost + infraCost);
        const platformCapex = platformCapexByYear[row.year] || 0;
        const totalCapex = gpuCapex + platformCapex;

        capexHistory.push(totalCapex);
        const depreciation = capexHistory.slice(-usefulLife).reduce((a, b) => a + b, 0) / usefulLife;

        totalTokensAll += totalTokens;
        totalGpuAll += requiredGpu;
        totalGpuIncAll += gpuInc;
        totalGpuCapexAll += gpuCapex;
        totalPlatformCapexAll += platformCapex;
        totalCapexAll += totalCapex;
        totalDepAll += depreciation;

        const tr = document.createElement('tr');
        tr.innerHTML = `
          <td>${{row.year}}</td>
          <td>${{fmtInt(totalTokens)}}</td>
          <td>${{fmtInt(requiredGpu)}}</td>
          <td>${{fmtInt(gpuInc)}}</td>
          <td>${{fmtMoney(gpuCapex)}}</td>
          <td>${{fmtMoney(platformCapex)}}</td>
          <td>${{fmtMoney(totalCapex)}}</td>
          <td>${{fmtMoney(depreciation)}}</td>
        `;
        bodyEl.appendChild(tr);

        prevGpu = requiredGpu;
      }});

      sumTokens.textContent = fmtInt(totalTokensAll);
      sumGpu.textContent = fmtInt(totalGpuAll);
      sumGpuInc.textContent = fmtInt(totalGpuIncAll);
      sumGpuCapex.textContent = fmtMoney(totalGpuCapexAll);
      sumPlatformCapex.textContent = fmtMoney(totalPlatformCapexAll);
      sumTotalCapex.textContent = fmtMoney(totalCapexAll);
      sumDep.textContent = fmtMoney(totalDepAll);
    }}

    [
      growthRateEl,
      workingHoursEl,
      peakFactorEl,
      gpuUnitCostEl,
      infraCostEl,
      usefulLifeEl,
    ].forEach((el) => el.addEventListener('input', recalc));

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

    print("Год | Total tokens | req GPU | GPU inc | GPU CAPEX | Total CAPEX | Depreciation")
    print("-" * 98)
    for row in rows:
        print(
            f"{row['year']} | {row['total_tokens']:,} | {row['required_gpu']:,} | "
            f"{row['required_gpu_increment']:,} | {row['gpu_capex']:,} | "
            f"{row['total_capex']:,} | {row['depreciation']:.2f}"
        )

    html = render_html(rows, assumptions)
    save_html(html, OUTPUT_PATH)
    print(f"\nHTML-отчет сохранен: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
