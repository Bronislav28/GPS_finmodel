# GPS_finmodel
Financial model, automated with Python

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

## Token-load + GPU/CAPEX model (2026-2030)

```bash
python calc_token_load.py
```

После запуска формируется интерактивный HTML-отчет:

- `output/gps_finmodel.html`

Отчет содержит:

- total tokens
- required_gpu
- required_gpu_increment
- gpu_capex
- total_capex
- depreciation

В браузере можно менять assumptions (growth rate, GPU capacity, CAPEX inputs) и сразу получать пересчет.
