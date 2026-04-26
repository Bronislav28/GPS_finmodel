# GPS_finmodel

Python-модель ДЗО по ИИ, которая читает `assumptions.yaml` и считает метрики за 2026–2030.

## Что считает модель

- Workplace.ai: `active_users`, `daily_tokens`, `annual_tokens`
- Contact_Center.ai: `automated_interactions`, `daily_tokens`, `annual_tokens`
- Общие: `total_daily_tokens`, `total_annual_tokens`, доли сервисов в токенах
- Compute: `weighted_throughput` (harmonic mean), `tokens_per_second`, `required_gpu`, `required_gpu_increment`
- CAPEX: `gpu_capex`, `total_capex`, `annual_depreciation`

## Запуск

```bash
python -m pip install -r requirements.txt
python calc_token_load.py
```

## Результаты

После запуска формируются файлы:

- `output/gps_finmodel_results.csv`
- `output/gps_finmodel.html`

В HTML есть отдельные таблицы:

1. Token Load by Product
2. GPU Calculation
3. CAPEX
4. Summary

## Если в среде нет PyYAML

Скрипт корректно завершится с понятным сообщением (без traceback-аварии) и подскажет команду установки:

```bash
python -m pip install -r requirements.txt
```
