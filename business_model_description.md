# Цель модели

Построить Python-модель ДЗО по ИИ, которая читает assumptions.yaml и рассчитывает:

1. active users по Workplace.ai
2. daily tokens и annual tokens по Workplace.ai
3. automated interactions по Contact_Center.ai
4. daily tokens и annual tokens по Contact_Center.ai
5. total annual tokens по ДЗО
6. долю каждого сервиса в токенах
7. таблицу результатов по годам 2026–2030
8. required_gpu по годам
9. owned_gpu по годам
10. rented_gpu по годам
11. owned_gpu_increment по годам
12. gpu_capex по годам
13. datacenter_construction_capex по годам
14. total_capex по годам
15. depreciation по годам
16. datacenter OPEX по годам
17. team OPEX по годам
18. GPU rental OPEX по годам
19. total OPEX по годам
20. revenue по сценариям потребления
21. contribution margin
22. EBITDA / operating result

---

# Входные данные

Основной файл:

- assumptions.yaml

---

# Infrastructure strategy scenarios

Модель должна поддерживать 3 сценария инфраструктуры:

## 1. build_own_dc

Собственный ЦОД строится сразу в 2026 году.

Логика:

- все required_gpu = owned_gpu
- rented_gpu = 0
- возникает CAPEX на покупку GPU
- возникает CAPEX на строительство ЦОДа
- начисляется depreciation
- datacenter OPEX считается полностью

---

## 2. rent_gpu_only

Собственный ЦОД не строится.

Логика:

- все required_gpu = rented_gpu
- owned_gpu = 0
- CAPEX на GPU отсутствует
- CAPEX на строительство ЦОДа отсутствует
- depreciation отсутствует
- возникает только GPU rental OPEX
- datacenter OPEX = 0

---

## 3. hybrid

До года строительства используется аренда GPU,
после — собственный ЦОД.

Логика:

- до construction_start_year:
  - rented_gpu = required_gpu
  - owned_gpu = 0

- начиная с construction_start_year:
  - owned_gpu = required_gpu
  - rented_gpu = 0

В год строительства:

- возникает CAPEX на строительство ЦОДа
- owned_gpu_increment = owned_gpu текущего года

После запуска:

- начисляется depreciation
- считается datacenter OPEX

---

# GPU calculation

Python-модель рассчитывает:

- required_gpu

required_gpu берётся из GPU sizing model
на основе annual tokens, utilization assumptions,
reserve capacity и performance assumptions.

---

# CAPEX calculation

Python-модель должна рассчитывать по годам 2026–2030:

1. owned_gpu
2. rented_gpu
3. owned_gpu_increment
4. gpu_capex
5. gpu_infra_capex
6. datacenter_construction_capex
7. total_capex
8. depreciation

---

## GPU ownership logic

### build_own_dc

- owned_gpu = required_gpu
- rented_gpu = 0

### rent_gpu_only

- owned_gpu = 0
- rented_gpu = required_gpu

### hybrid

До строительства:

- owned_gpu = 0
- rented_gpu = required_gpu

После строительства:

- owned_gpu = required_gpu
- rented_gpu = 0

---

## owned_gpu_increment

Формулы:

Для первого года владения:

- owned_gpu_increment = owned_gpu

Для следующих лет:

- owned_gpu_increment =
  max(owned_gpu текущего года - owned_gpu предыдущего года, 0)

Для rented GPU CAPEX не возникает.

---

## CAPEX formulas

### GPU CAPEX

- gpu_capex =
  owned_gpu_increment × capex.gpu.unit_cost

### GPU infrastructure CAPEX

- gpu_infra_capex =
  gpu_capex × capex.infra_multiplier.value

---

## Datacenter construction CAPEX

Размер ЦОДа определяется автоматически:

- peak_required_gpu = max(required_gpu)
- it_load_mw =
  peak_required_gpu × gpu_power_kw / 1000
- total_load_mw =
  it_load_mw × pue
- target_capacity_mw =
  ceil(total_load_mw)

Используются benchmark values:

- benchmark_components_3mw_usd_mln
- benchmark_capacity_mw

Формулы:

- component_target_usd =
  component_3mw_usd ×
  target_capacity_mw /
  benchmark_capacity_mw

- component_target_rub =
  component_target_usd × fx_usd_rub_t

- datacenter_construction_capex =
  total_component_rub × construction_flag

CAPEX строительства возникает только
в год, где construction_flag = 1.

# Office CAPEX

Дополнительно к GPU и строительству ЦОДа
модель должна учитывать корпоративный CAPEX GPS,
не связанный с production AI infrastructure.

Включаются:

- office server
- employee laptops
- executive laptops
- MFP / printers
- meeting room equipment
- office furniture

---

## Office server

Корпоративный сервер для:

- AD / access
- file services
- backup
- monitoring
- internal services

Формула:

- office_server_capex =
  quantity × unit_cost

Амортизация:

- 5 лет

---

## Employee laptops

Ноутбуки для:

- core delivery team
- SG&A

Логика:

- 1 ноутбук на 1 FTE

Формула:

- employee_laptops_capex =
  total_fte × unit_cost

Амортизация:

- 3 года

---

## Executive laptops

Ноутбуки для:

- CEO
- CFO
- COO
- Head of AI
- Chief Architect

Формула:

- executive_laptops_capex =
  quantity × unit_cost

Амортизация:

- 3 года

---

## MFP / printers

Логика:

- 1 МФУ на 30–40 сотрудников

Формула:

- mfu_capex =
  quantity × unit_cost

Амортизация:

- 5 лет

---

## Meeting room equipment

Оснащение переговорных:

- VC systems
- displays
- conference equipment

Формула:

- meeting_rooms_capex =
  total_cost

Амортизация:

- 5 лет

---

## Office furniture

Стартовый CAPEX:

- мебель
- базовое оснащение офиса

Формула:

- office_furniture_capex =
  total_cost

Амортизация:

- 7 лет

---

## Total Office CAPEX

Формула:

- total_office_capex =
  office_server_capex +
  employee_laptops_capex +
  executive_laptops_capex +
  mfu_capex +
  meeting_rooms_capex +
  office_furniture_capex

---

## Total CAPEX

Общий CAPEX модели:

- total_capex =
  gpu_infra_capex +
  datacenter_construction_capex +
- total_office_capex

GPU rental не входит в CAPEX.

Амортизация начисляется также
на office CAPEX согласно срокам
полезного использования.

---

# Depreciation

Амортизация начисляется только на:

- owned GPU
- строительство собственного ЦОДа

Формула:

- depreciable_base =
  gpu_infra_capex +
  datacenter_construction_capex

Метод:

- straight-line

Срок:

- capex.depreciation.useful_life_years

GPU rental не амортизируется.

---

# OPEX calculation

Python-модель должна рассчитывать OPEX
по годам 2026–2030.

---

# Datacenter OPEX

Расчет производится только
для owned infrastructure.

Если owned_gpu = 0:

- datacenter OPEX = 0

---

## Datacenter OPEX steps

### 1. Average GPU

- average_gpu =
  (owned_gpu_beginning_of_year +
   owned_gpu_end_of_year) / 2

---

### 2. Power calculation

- it_load_mw =
  average_gpu × gpu_power_kw / 1000

- total_load_mw =
  it_load_mw × pue

---

### 3. Electricity consumption

- electricity_kwh =
  total_load_mw × 1000 ×
  operating_hours_per_day ×
  calendar_days_per_year

---

### 4. Electricity price

- price_2026 =
  base_price_per_kwh

- price_t =
  price_previous_year ×
  (1 + annual_growth_t)

---

### 5. Electricity cost

- electricity_cost =
  electricity_kwh × electricity_price_t

---

### 6. Additional costs

- maintenance_cost =
  total_capex ×
  maintenance_percent_of_capex

- network_cost =
  total_load_mw ×
  network_cost_per_mw_per_year

- land_rent =
  total_load_mw ×
  land_rent_per_mw_per_year

---

### 7. Datacenter OPEX

- datacenter_opex =
  electricity_cost +
  maintenance_cost +
  network_cost +
  land_rent

- other_opex =
  datacenter_opex ×
  other_opex_percent

- total_datacenter_opex =
  datacenter_opex +
  other_opex

---

# Team OPEX

Расчет производится
на основе блока:

- opex.team

---

## Team calculation

### 1. Monthly hiring

Для каждого месяца:

- monthly_fte =
  core_team_target_fte ×
  hiring_plan_monthly

---

### 2. Gross salary

Для каждой роли:

- monthly_gross_salary
  из salary_gross_monthly_rub

---

### 3. Bonus and payroll taxes

- monthly_bonus =
  monthly_gross ×
  bonus_percent_of_gross

- monthly_social =
  (monthly_gross + monthly_bonus) ×
  social_contribution_sfr_percent_of_gross

---

### 4. Fully loaded cost

- monthly_cost_per_fte =
  monthly_gross +
  monthly_bonus +
  monthly_social

---

### 5. Monthly team cost

- monthly_team_cost =
  monthly_fte ×
  monthly_cost_per_fte

---

### 6. Annual team OPEX

- annual_team_opex =
  сумма monthly_team_cost

---

### 7. Salary growth

- salary_t =
  salary_previous_year ×
  (1 + salary_growth_t)

---

# GPU Rental OPEX

Используется блок:

- opex.gpu_rental

Формула:

- annual_gpu_rental_cost =
  rented_gpu ×
  rental_price_per_gpu_per_year

Важно:

- если rented_gpu = 0,
  rental OPEX = 0

- если scenario = rent_gpu_only,
  весь required_gpu попадает
  в rental OPEX

---

# Total OPEX

Формула:

- total_opex =
  total_datacenter_opex +
  annual_team_opex +
  annual_gpu_rental_cost

---

# SG&A calculation

Модель должна рассчитывать SG&A по годам 2026–2030.

SG&A — это постоянные административные расходы GPS, не относящиеся к:
- delivery OPEX
- datacenter OPEX
- GPU rental
- core AI/platform team

## Inflation

SG&A индексируется по рублёвой инфляции:

- inflation_index_2026 = 1.0
- inflation_index_t = inflation_index_previous_year × (1 + rub_inflation_t)

## Fixed SG&A

Расчёт производится на основе блока:

- sga.monthly_cost_base_2026

Формула:

- monthly_cost_t = monthly_cost_base_2026 × inflation_index_t
- annual_fixed_sga = сумма monthly_cost_t × 12

## Office rent

Аренда офиса рассчитывается исходя из численности сотрудников GPS:

- total_fte = core_team_fte + sga_team_fte
- required_office_area_sqm = total_fte × sqm_per_fte
- rent_rub_per_sqm_per_month_t =
  rent_rub_per_sqm_per_month_base_2026 × inflation_index_t
- monthly_office_rent =
  required_office_area_sqm × rent_rub_per_sqm_per_month_t
- annual_office_rent =
  monthly_office_rent × 12

## Total SG&A

Формула:

- total_sga = annual_fixed_sga + annual_office_rent

## HTML / CSV output

Добавить таблицу:

### SG&A

- annual_fixed_sga
- required_office_area_sqm
- annual_office_rent
- total_sga

Все таблицы должны оставаться в wide format:

Metric | 2026 | 2027 | 2028 | 2029 | 2030

---

# Revenue

Revenue считается через
реальное потребление мощности
и contribution margin.

Сценарий revenue определяется
не через мощность ЦОДа,
а через utilization уже созданной мощности.

То есть:

CAPEX → задаёт мощность

Revenue scenario →
задаёт реальное использование мощности

---

## Revenue logic

Revenue зависит от:

- utilization scenario
- annual token consumption
- monetization assumptions
- contribution margin

Необходима возможность
сценарного анализа:

- conservative
- base
- aggressive

---

# P&L calculation

Модель должна рассчитывать полноценный Profit & Loss (P&L)
по годам 2026–2030.

P&L строится на основе:

- Revenue
- COGS (delivery costs)
- SG&A
- Depreciation
- Profit Tax

---

# Revenue

Revenue рассчитывается через utilization scenarios
и contribution margin logic.

Revenue должен быть раскрыт по продуктам:

- Workplace.ai
- Contact_Center.ai

Формулы:

- workplace_ai_revenue
- contact_center_ai_revenue

- total_revenue =
  workplace_ai_revenue +
  contact_center_ai_revenue

---

# COGS (Cost of Goods Sold)

COGS = delivery costs,
необходимые для оказания AI-сервисов.

COGS включает:

## Datacenter OPEX

- electricity_cost
- maintenance_cost
- network_cost
- land_rent
- other_datacenter_opex
- total_datacenter_opex

---

## Team OPEX

Team payroll должен быть раскрыт отдельно:

- payroll_gross
- annual_bonus
- social_contribution_sfr
- total_team_opex

---

## GPU Rental OPEX

- annual_gpu_rental_cost

---

## Total COGS

Формула:

- total_cogs =
  total_datacenter_opex +
  total_team_opex +
  annual_gpu_rental_cost

---

# Gross Profit

Формула:

- gross_profit =
  total_revenue -
  total_cogs

---

# SG&A

SG&A = overhead costs,
не относящиеся к delivery.

## Важно

SG&A payroll считается как fully loaded cost:

- annual gross salary
- annual bonus
- social contribution SFR (30%)

Бонус:

- начисляется один раз в декабре
- пропорционально фактически отработанному времени в году

SFR:

- начисляется на:
  gross salary + annual bonus

---

## SG&A включает:

- corporate_management
- hr
- finance_and_accounting
- admin
- shared_corporate_services
- office_rent

---

## Total SG&A

Формула:

- total_sga =
  annual_fixed_sga +
  annual_office_rent

---

# EBITDA

Формула:

- ebitda =
  gross_profit -
  total_sga

---

# Depreciation

Амортизация начисляется только
на собственные активы:

- GPU
- datacenter construction
- office CAPEX

Формулы:

- gpu_depreciation
- datacenter_depreciation
- office_capex_depreciation

- total_depreciation =
  сумма всех видов depreciation

GPU rental не амортизируется.

---

# EBIT

Формула:

- ebit =
  ebitda -
  total_depreciation

---

# Profit Tax

Налог начисляется только
при положительном EBIT.

Формула:

- profit_tax =
  max(ebit, 0) ×
  profit_tax_rate

---

# Net Income

Формула:

- net_income =
  ebit -
  profit_tax

---

# HTML и CSV output

Python должен формировать:

- pandas DataFrame
- CSV
- HTML-report

---

# Формат таблиц

Все таблицы должны быть
в wide format:

```text
Metric | 2026 | 2027 | 2028 | 2029 | 2030