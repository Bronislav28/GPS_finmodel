# GPS_finmodel
Financial model, automated with Python

Python-модель ДЗО по ИИ, которая читает `assumptions.yaml` и считает цепочку:

**Token Load → GPU → CAPEX → OPEX** (годы 2026–2030).

## Что считает модель

- **Token Load**
  - Workplace.ai: `active_users`, `daily_tokens`, `annual_tokens`
  - Contact_Center.ai: `automated_interactions`, `daily_tokens`, `annual_tokens`
  - `total_daily_tokens`, `total_annual_tokens`, доли сервисов
- **GPU**
  - `weighted_throughput` (harmonic mean), `tokens_per_second`, `required_gpu`, `required_gpu_increment`
- **CAPEX**
  - `gpu_capex`, `total_capex`, `annual_depreciation`
- **OPEX**
  - Datacenter OPEX (электричество, maintenance, network, land rent, other)
  - Team OPEX (FTE, зарплата, bonus, social)
  - `total_opex`

## Важное про структуру assumptions.yaml

- Модель читает OPEX-параметры из `datacenter` и `team` (top-level).
- Также поддержан fallback для старого варианта `opex.datacenter` / `opex.team`.
- Если каких-то OPEX/CAPEX значений нет, скрипт не падает: соответствующие денежные поля будут `NaN`.

## Запуск

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python calc_token_load.py
```

## Результаты

После запуска формируются файлы:

- `output/gps_finmodel_results.csv`
- `output/gps_finmodel.html`

HTML содержит отдельные таблицы:

- Token Load
- GPU Calculation
- CAPEX
- Datacenter OPEX
- Team OPEX
- Total OPEX
- Summary

## Если в среде нет PyYAML

Скрипт завершится с понятной подсказкой по установке:

```bash
python -m pip install -r requirements.txt
```
