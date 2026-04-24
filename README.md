# GPS_finmodel
Financial model, automated with Python

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

## Token-load calculation (2026-2030)

```bash
python calc_token_load.py
```

После запуска формируется интерактивный HTML-отчет:

- `output/gps_finmodel.html`

В отчете доступны параметры для пересчета в браузере:

- Growth rate (% в год)
- Cost assumption для `Workplace.ai` ($ / 1M tokens)
- Cost assumption для `Contact_Center.ai` ($ / 1M tokens)
