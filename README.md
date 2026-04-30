# GPS_finmodel

## Назначение модели

**GPS_finmodel** — это финансовая модель ДЗО по ИИ, предназначенная для управленческого и инвестиционного анализа.
Модель читает входные допущения из `assumptions.yaml` и автоматически рассчитывает полный контур финансовой отчетности и инвестиционных метрик.

Модель считает:

- **Token load** (нагрузка токенов по продуктам)
- **GPU sizing** (потребность в GPU и прирост мощностей)
- **CAPEX**
- **OPEX**
- **SG&A**
- **Revenue**
- **P&L**
- **Cash Flow**
- **Funding**
- **Balance Sheet**
- **DCF / Investment Metrics**
- **Sensitivity Analysis**

---

## Основные файлы проекта

- `assumptions.yaml`  
  Единый источник входных параметров модели (**source of truth**).
- `business_model_description.md`  
  Бизнес-логика, требования к расчетам и методология.
- `calc_token_load.py`  
  Основной Python-скрипт расчета модели.
- `output/gps_finmodel.html`  
  Интерактивный HTML-отчет для бизнес-пользователей и инвесткомитета.
- `output/gps_finmodel_results.csv`  
  Детализированные результаты расчетов в табличном виде.

---

## Как запустить модель

Базовая команда запуска:

```bash
python calc_token_load.py
```

Рекомендуемо (если окружение еще не подготовлено):

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python calc_token_load.py
```

---

## Что модель генерирует

После выполнения `python calc_token_load.py` формируются:

- **HTML report**: `output/gps_finmodel.html`
- **CSV results**: `output/gps_finmodel_results.csv`

HTML-отчет предназначен для интерактивного просмотра сценариев и ключевых метрик, CSV — для последующего анализа в Excel/BI.

---

## Основные сценарии

### Infrastructure scenarios

- `build_own_dc`
- `rent_gpu_only`
- `hybrid`

### Revenue scenarios

- `conservative`
- `base`
- `aggressive`

### Funding scenarios

- `equity_only`
- `revolver_only`
- `mix`

---

## Основные interactive controls в HTML

В отчете `output/gps_finmodel.html` доступны ключевые элементы управления:

- `revenue scenario` dropdown
- `infrastructure scenario` dropdown
- `construction_start_year` input
- `discount_rate` input

Это позволяет быстро пересчитывать и сравнивать сценарии без ручного редактирования кода.

---

## Что не делать

Чтобы сохранить целостность модели:

- **Не редактировать output-файлы вручную** (`output/*.html`, `output/*.csv`).
- **Редактировать только `assumptions.yaml`** как единый источник входных данных.
- После любых изменений допущений **обязательно запускать**:

```bash
python calc_token_load.py
```

---

## Структура репозитория

```text
GPS_finmodel/
├── README.md
├── assumptions.yaml
├── business_model_description.md
├── calc_token_load.py
├── requirements.txt
└── output/
    ├── gps_finmodel.html
    └── gps_finmodel_results.csv
```

---

## Краткий financial logic flow

Логика модели строится как последовательная цепочка:

**Tokens**  
→ **GPU**  
→ **CAPEX / OPEX**  
→ **Revenue**  
→ **P&L**  
→ **Cash Flow**  
→ **Funding**  
→ **Balance Sheet**  
→ **DCF / Sensitivity**

Именно такая последовательность обеспечивает причинно-следственную связь между операционными драйверами (токены, GPU) и инвестиционными выводами (стоимость, доходность, чувствительность).
