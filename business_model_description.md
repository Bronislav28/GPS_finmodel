# GPS Finmodel — Business Model Description

## 1. Цель модели

Модель GPS рассчитывает финансовую модель ДЗО по ИИ на горизонте 2026–2030.

Модель читает входные параметры из `assumptions.yaml` и рассчитывает:

1. спрос на токены по продуктам Workplace.ai и Contact_Center.ai;
2. требуемую GPU-мощность;
3. инфраструктурные сценарии: собственный ЦОД, аренда GPU, гибрид;
4. CAPEX по GPU, ЦОДу, офису и разработке IP;
5. depreciation & amortization;
6. OPEX, включая datacenter OPEX, team OPEX и GPU rental OPEX;
7. SG&A;
8. Revenue через utilization мощности и target contribution margin;
9. P&L;
10. Cash Flow Statement;
11. Funding через equity / revolver / mix;
12. Balance Sheet;
13. DCF / Investment Metrics;
14. Return Metrics;
15. Sensitivity Analysis;
16. HTML и CSV output.

Логика модели:

```text
Usage assumptions
→ Token load
→ Compute model
→ GPU sizing
→ Infrastructure strategy
→ CAPEX / OPEX
→ Revenue
→ P&L
→ Cash Flow
→ Funding
→ Balance Sheet
→ DCF / Investment Metrics
→ Sensitivity Analysis
```

---

## 2. Основные файлы

Основной файл входных параметров:

```text
assumptions.yaml
```

Основной расчетный файл:

```text
calc_token_load.py
```

Основные выходные файлы:

```text
output/gps_finmodel.html
output/gps_finmodel_results.csv
```

`assumptions.yaml` является source of truth для модели.  
`business_model_description.md` описывает бизнес-логику модели.  
HTML и CSV являются результатами расчета и не должны редактироваться вручную.

---

## 3. Горизонт модели

Модель рассчитывается по годам:

```text
2026, 2027, 2028, 2029, 2030
```

Все основные таблицы отчета должны выводиться в wide format:

```text
Metric | 2026 | 2027 | 2028 | 2029 | 2030
```

---

## 4. Global assumptions

### 4.1 FX assumptions

FX используется для пересчета USD-бенчмарков в RUB.

Формулы:

```text
fx_2026 = base_value

fx_t =
fx_previous_year × (1 + annual_growth_t)
```

FX применяется в первую очередь для расчета CAPEX строительства ЦОДа, так как benchmark стоимости ЦОДа задан в USD.

---

### 4.2 Inflation assumptions

Рублевая инфляция используется для индексации:

- SG&A;
- офисных расходов;
- прочих рублевых затрат.

Формулы:

```text
inflation_index_2026 = 1.0

inflation_index_t =
inflation_index_previous_year × (1 + annual_growth_t)
```

---

## 5. Products

Модель включает два продукта:

1. Workplace.ai
2. Contact_Center.ai

### 5.1 Workplace.ai

Workplace.ai — ИИ-платформа для работы сотрудников с корпоративными знаниями, документами и внутренними процессами.

Продукт включает:

- LLM fine-tuning;
- RAG / knowledge access;
- document generation;
- corporate chat assistant;
- agentic actions;
- генерацию текста и изображений;
- поддержку внутренних workflow.

`components` в YAML являются описательной декомпозицией продукта и не используются напрямую в финансовых расчетах.

---

### 5.2 Contact_Center.ai

Contact_Center.ai — ИИ-платформа для автоматизации клиентского взаимодействия.

Продукт включает:

- AI operator;
- operator assistant;
- voice layer;
- conversation analytics;
- agentic execution layer.

`components` в YAML являются описательной декомпозицией продукта и не используются напрямую в финансовых расчетах.

---

## 6. Usage assumptions

`usage_assumptions` описывает спрос на стороне банка.

### 6.1 Workplace.ai

Для Workplace.ai используются:

```text
total_employees
activation_rate
```

Формула:

```text
active_users =
total_employees × activation_rate
```

`activation_rate` показывает долю сотрудников, которые являются активными пользователями Workplace.ai.

---

### 6.2 Contact_Center.ai

Для Contact_Center.ai используются:

```text
interactions_per_day
automation_rate
```

Формула:

```text
automated_interactions_per_day =
interactions_per_day × automation_rate
```

`automation_rate` показывает долю обращений контакт-центра, которые обрабатываются AI.

---

## 7. Token load model

`token_load_model` переводит usage assumptions в токеновую нагрузку.

### 7.1 Time assumptions

Для Workplace.ai используется:

```text
working_days_per_year
```

Для Contact_Center.ai используется:

```text
calendar_days_per_year
```

---

### 7.2 Workplace.ai token load

Workplace.ai считается через токены на одного активного пользователя в день:

```text
tokens_per_active_user_per_day
```

Рост `tokens_per_active_user_per_day` по годам отражает:

- рост частоты использования;
- усложнение сценариев;
- работу с документами;
- RAG;
- agentic workflows;
- увеличение количества LLM calls на одну пользовательскую задачу.

Формулы:

```text
active_users =
total_employees × activation_rate

workplace_daily_tokens =
active_users × tokens_per_active_user_per_day

workplace_annual_tokens =
workplace_daily_tokens × working_days_per_year
```

---

### 7.3 Contact_Center.ai token load

Contact_Center.ai считается через blended assumption:

```text
tokens_per_interaction
```

Модель не разделяет text / voice token load, так как нет надежного публичного benchmark по российскому банковскому рынку для среднего количества токенов в текстовом и голосовом обращении.

Формулы:

```text
automated_interactions_per_day =
interactions_per_day × automation_rate

contact_center_daily_tokens =
automated_interactions_per_day × tokens_per_interaction

contact_center_annual_tokens =
contact_center_daily_tokens × calendar_days_per_year
```

---

### 7.4 Total annual tokens

Общая годовая токеновая нагрузка GPS:

```text
total_annual_tokens =
workplace_annual_tokens +
contact_center_annual_tokens
```

Эта величина является входом для GPU sizing.

---

## 8. Compute model

`compute_model` описывает перевод токеновой нагрузки в вычислительную нагрузку.

### 8.1 Model mix

`model_mix` показывает распределение токенов между классами моделей:

- frontier;
- large;
- medium;
- small.

Логика:

- в 2026–2028 годах выше доля frontier / large моделей, так как продукт еще развивается, routing менее оптимизирован, больше сложных универсальных запросов;
- в 2029–2030 годах часть нагрузки переходит на medium / small модели за счет model routing, кэширования, типизации сценариев и специализированных моделей.

---

### 8.2 Throughput per GPU

`throughput_per_gpu` показывает производительность одной GPU для каждого класса модели:

```text
tokens per second per GPU
```

Чем тяжелее модель, тем ниже throughput.

---

### 8.3 Weighted throughput

`weighted_throughput` — средняя производительность GPU с учетом model mix.

Формула:

```text
weighted_throughput =
1 / sum(model_share / throughput_per_gpu)
```

Используется harmonic mean, потому что нагрузка распределяется между моделями с разной производительностью.

---

### 8.4 GPU utilization

`utilization` показывает полезную загрузку GPU.

Она ниже 100%, потому что часть времени уходит на:

- orchestration;
- routing;
- переключение моделей;
- очереди;
- ошибки;
- резерв capacity;
- технические простои.

---

## 9. GPU sizing

`gpu_sizing` рассчитывает требуемое количество GPU.

### 9.1 Tokens per second

Годовая токеновая нагрузка переводится в tokens per second:

```text
tokens_per_second =
total_annual_tokens /
(working_days_per_year × working_hours_per_day × 3600)
```

---

### 9.2 Required GPU

Формула:

```text
required_gpu =
tokens_per_second /
(weighted_throughput × utilization) × peak_factor
```

Где:

- `tokens_per_second` — требуемая скорость обработки токенов;
- `weighted_throughput` — производительность одной GPU с учетом model mix;
- `utilization` — полезная загрузка GPU;
- `peak_factor` — запас на пики нагрузки.

Итоговое значение `required_gpu` используется в инфраструктурных сценариях.

---

## 10. Infrastructure strategy scenarios

Модель поддерживает три инфраструктурных сценария:

1. `build_own_dc`
2. `rent_gpu_only`
3. `hybrid`

### 10.1 build_own_dc

Собственный ЦОД строится со старта проекта.

Логика:

```text
owned_gpu = required_gpu
rented_gpu = 0
construction_start_year = 2026
```

Возникают:

- GPU CAPEX;
- GPU infrastructure CAPEX;
- datacenter construction CAPEX;
- datacenter OPEX;
- depreciation.

---

### 10.2 rent_gpu_only

Собственный ЦОД не строится.

Логика:

```text
owned_gpu = 0
rented_gpu = required_gpu
construction_start_year = null
```

Возникает:

- GPU rental OPEX.

Не возникает:

- GPU CAPEX;
- datacenter construction CAPEX;
- datacenter OPEX;
- depreciation по GPU / ЦОДу.

---

### 10.3 hybrid

До года строительства используется аренда GPU. Начиная с `construction_start_year` используется собственная инфраструктура.

Логика:

```text
if year < construction_start_year:
  rented_gpu = required_gpu
  owned_gpu = 0

if year >= construction_start_year:
  rented_gpu = 0
  owned_gpu = required_gpu
```

---

### 10.4 Construction flag

`construction_flag` рассчитывается автоматически:

```text
construction_flag =
1 if year == construction_start_year else 0
```

Для `rent_gpu_only` `construction_start_year = null`, поэтому `construction_flag = 0`.

---

### 10.5 Owned GPU increment

CAPEX возникает только на прирост собственных GPU.

```text
owned_gpu_increment =
owned_gpu in first owned year

owned_gpu_increment =
max(owned_gpu_current - owned_gpu_previous, 0)
in next years
```

---

## 11. CAPEX

`capex` рассчитывает инвестиции в активы GPS.

CAPEX включает:

1. GPU infrastructure;
2. Datacenter construction;
3. Office CAPEX;
4. Intangible assets / IP.

---

### 11.1 GPU CAPEX

```text
gpu_capex =
owned_gpu_increment × gpu.unit_cost
```

GPU CAPEX возникает только для owned GPU.

---

### 11.2 GPU Infrastructure CAPEX

`gpu_infra_capex` включает стоимость GPU и сопутствующей инфраструктуры:

- серверы;
- стойки;
- сеть;
- storage;
- инженерная инфраструктура;
- резерв.

Формула:

```text
gpu_infra_capex =
gpu_capex × infra_multiplier
```

`gpu_infra_capex` уже включает `gpu_capex`.  
В Cash Flow и Balance Sheet для GPU-инфраструктуры используется именно `gpu_infra_capex`, чтобы не было двойного учета.

---

### 11.3 Datacenter Construction CAPEX

Размер ЦОДа рассчитывается по пиковой GPU-нагрузке за горизонт модели.

Формулы sizing:

```text
peak_required_gpu =
max(required_gpu)

it_load_mw =
peak_required_gpu × gpu_power_kw / 1000

total_load_mw =
it_load_mw × pue

target_capacity_mw =
ceil(total_load_mw)
```

CAPEX строительства рассчитывается через benchmark 3 MW:

```text
component_target_usd =
component_3mw_usd × target_capacity_mw / benchmark_capacity_mw

component_target_rub =
component_target_usd × fx_usd_rub_t

total_component_rub =
sum(component_target_rub)

datacenter_construction_capex =
total_component_rub × construction_flag
```

CAPEX строительства возникает только в год строительства.

---

### 11.4 Office CAPEX

Office CAPEX — корпоративный CAPEX GPS, не связанный с production AI infrastructure.

Включает:

- office server;
- employee laptops;
- executive laptops;
- MFP / printers;
- meeting room equipment;
- office furniture.

Office CAPEX возникает в purchase year.

Формулы:

```text
purchase_flag =
year == purchase_year

office_server_capex =
quantity × unit_cost × purchase_flag

employee_laptops_capex =
total_fte_in_purchase_year × unit_cost × purchase_flag

executive_laptops_capex =
quantity × unit_cost × purchase_flag

mfu_capex =
quantity × unit_cost × purchase_flag

meeting_rooms_capex =
quantity × unit_cost × purchase_flag

office_furniture_capex =
total_cost × purchase_flag

total_office_capex =
office_server_capex +
employee_laptops_capex +
executive_laptops_capex +
mfu_capex +
meeting_rooms_capex +
office_furniture_capex
```

---

### 11.5 Intangible Assets / IP CAPEX

Модель капитализирует затраты на разработку собственных AI-продуктов:

- Workplace.ai IP;
- Contact_Center.ai IP.

Эти активы отражаются как intangible assets, а не как PP&E.

Капитализируются только роли core team, которые напрямую создают продукт и IP.

Капитализируются:

- head_of_ai;
- genai_lead;
- llm_engineer;
- ml_engineer;
- data_engineer;
- platform_lead;
- backend_engineer;
- ai_platform_engineer;
- devops_engineer;
- agent_lead;
- agent_engineer;
- business_analyst;
- chief_architect;
- solution_architect;
- mlops_lead;
- qa_lead;
- qa_engineer;
- data_lead;
- data_labeling_specialist.

Не капитализируются:

- implementation_manager;
- sre_engineer;
- datacenter team;
- office / admin roles;
- CEO / CFO;
- HR / Finance;
- Sales / Marketing;
- Customer Success;
- Support / Run team.

Капитализация идет только в build phase до go-live.

После go-live соответствующие сотрудники возвращаются в OPEX, если они занимаются поддержкой, развитием, эксплуатацией и улучшениями продукта.

---

### 11.6 IP build period and go-live

Для обоих продуктов:

```text
build_period_months = 6
go_live_year = 2026
go_live_month = 7
```

Это означает:

- январь–июнь 2026: build phase;
- июль 2026: go-live;
- после go-live: начинается revenue recognition и amortization.

---

### 11.7 IP cost formula

Для каждого продукта:

```text
capitalized_payroll =
eligible_core_team_payroll × effort_share_of_core_team

capitalized_sfr =
capitalized_payroll × sfr_rate

development_infrastructure_cost =
capitalized_payroll × development_infrastructure_percent

data_acquisition_cost =
capitalized_payroll × data_acquisition_percent

total_ip_asset_value =
capitalized_payroll +
capitalized_sfr +
development_infrastructure_cost +
data_acquisition_cost
```

Effort allocation:

```text
Workplace.ai = 70%
Contact_Center.ai = 30%
```

---

### 11.8 Total CAPEX

```text
tangible_capex =
gpu_infra_capex +
datacenter_construction_capex +
office_capex

intangible_capex =
workplace_ai_ip_value +
contact_center_ai_ip_value

total_capex =
tangible_capex +
intangible_capex
```

---

## 12. Depreciation & Amortization

`depreciation_and_amortization` — единый блок D&A.

Он рассчитывает:

1. depreciation по PP&E;
2. amortization по intangible assets;
3. total depreciation and amortization.

---

### 12.1 PP&E depreciation

PP&E включает:

- GPU infrastructure;
- datacenter construction;
- office CAPEX.

Формулы:

```text
gpu_depreciation =
gpu_infra_capex / gpu_infra_useful_life_years

datacenter_depreciation =
datacenter_construction_capex / datacenter_useful_life_years

office_capex_depreciation =
office_capex / asset_specific_useful_life_years

total_ppe_depreciation =
gpu_depreciation +
datacenter_depreciation +
office_capex_depreciation
```

---

### 12.2 IP amortization

Intangible assets включают:

- Workplace.ai IP;
- Contact_Center.ai IP.

Формулы:

```text
workplace_ai_amortization =
workplace_ai_ip_value / ip_assets_useful_life_years

contact_center_ai_amortization =
contact_center_ai_ip_value / ip_assets_useful_life_years

total_ip_amortization =
workplace_ai_amortization +
contact_center_ai_amortization
```

---

### 12.3 Total D&A

```text
total_depreciation_and_amortization =
total_ppe_depreciation +
total_ip_amortization
```

Эта величина используется в P&L, Cash Flow, DCF и Balance Sheet.

---

## 13. OPEX

`opex` включает:

1. GPU rental OPEX;
2. Datacenter OPEX;
3. Team OPEX.

---

### 13.1 GPU Rental OPEX

GPU rental возникает только по rented GPU.

Формула:

```text
annual_gpu_rental_cost =
rented_gpu × rental_price_per_gpu_per_year
```

Если GPU арендуются, electricity, cooling, hosting и обслуживание предполагаются включенными в rental price. Поэтому электричество отдельно считается только по owned GPU.

---

### 13.2 Datacenter OPEX

Datacenter OPEX считается только для owned infrastructure.

Если owned_gpu = 0:

```text
total_datacenter_opex = 0
```

---

### 13.3 Average owned GPU

```text
average_owned_gpu =
(owned_gpu_beginning_of_year + owned_gpu_end_of_year) / 2
```

---

### 13.4 Power and electricity

```text
it_load_mw =
average_owned_gpu × gpu_power_kw / 1000

total_load_mw =
it_load_mw × pue

electricity_kwh =
total_load_mw × 1000 × operating_hours_per_day × calendar_days_per_year

electricity_cost =
electricity_kwh × electricity_price_t
```

`weighted_throughput` влияет на electricity cost косвенно:

```text
weighted_throughput
→ required_gpu
→ owned_gpu
→ electricity_kwh
→ electricity_cost
```

---

### 13.5 Datacenter maintenance

Maintenance cost считается только от production infrastructure base:

```text
datacenter_maintenance_base =
cumulative_gpu_infra_capex +
cumulative_datacenter_construction_capex

maintenance_cost =
datacenter_maintenance_base × maintenance_percent_of_capex
```

Office CAPEX и intangible CAPEX не входят в базу maintenance ЦОДа.

---

### 13.6 Other datacenter OPEX

```text
network_cost =
total_load_mw × network_cost_per_mw_per_year

land_rent =
total_load_mw × land_rent_per_mw_per_year

datacenter_base_opex =
electricity_cost +
maintenance_cost +
network_cost +
land_rent

other_datacenter_opex =
datacenter_base_opex × other_opex_percent

total_datacenter_opex =
datacenter_base_opex +
other_datacenter_opex
```

---

### 13.7 Team OPEX

Team OPEX считается на основе:

- target FTE core team;
- monthly gross salary;
- hiring plan;
- annual bonus;
- SFR social contribution;
- capitalization of eligible roles during build phase.

---

### 13.8 Team payroll

```text
monthly_gross_salary =
salary_gross_monthly_rub × monthly_fte

monthly_bonus_accrual =
monthly_gross_salary × bonus_percent_of_gross

monthly_social_contribution_sfr =
(monthly_gross_salary + monthly_bonus_accrual) × social_contribution_sfr_percent_of_gross

monthly_fully_loaded_team_cost =
monthly_gross_salary +
monthly_bonus_accrual +
monthly_social_contribution_sfr

annual_core_team_cash_cost =
sum(monthly_fully_loaded_cost_by_role_by_month)
```

---

### 13.9 Capitalized core team cost

During build phase:

```text
capitalized_core_team_cost =
sum(
  monthly_fully_loaded_cost_by_role_by_month
  where role in eligible_core_team_roles
  and month < go_live_month
)
```

After go-live:

```text
capitalized_core_team_cost = 0
for ongoing support / run / minor improvements
```

---

### 13.10 Total team OPEX

```text
total_team_opex =
annual_core_team_cash_cost -
capitalized_core_team_cost
```

---

## 14. SG&A

SG&A — постоянные административные расходы GPS, не относящиеся к delivery / production OPEX.

SG&A включает:

- corporate management;
- HR;
- finance and accounting;
- admin;
- shared corporate services;
- office rent.

---

### 14.1 SG&A payroll

SG&A payroll рассчитывается по target FTE и monthly gross salary.

Формулы:

```text
total_sga_fte =
sum(target_fte)

annual_gross_salary_by_role =
monthly_gross_salary_by_role × target_fte_by_role × 12 × inflation_index_t

annual_bonus_by_role =
annual_gross_salary_by_role × annual_bonus_percent_of_gross × worked_months_ratio

annual_social_contribution_sfr_by_role =
(annual_gross_salary_by_role + annual_bonus_by_role) × social_contribution_sfr_percent_of_gross

annual_fully_loaded_cost_by_role =
annual_gross_salary_by_role +
annual_bonus_by_role +
annual_social_contribution_sfr_by_role

annual_fixed_sga =
sum(annual_fully_loaded_cost_by_role)
```

---

### 14.2 Office rent

Office rent рассчитывается через FTE, площадь и ставку аренды.

Формулы:

```text
total_fte =
core_team_fte +
total_sga_fte

required_office_area_sqm =
total_fte × sqm_per_fte

rent_rub_per_sqm_per_month_t =
rent_rub_per_sqm_per_month_base_2026 × inflation_index_t

monthly_office_rent =
required_office_area_sqm × rent_rub_per_sqm_per_month_t

annual_office_rent =
monthly_office_rent × 12
```

---

### 14.3 Total SG&A

```text
total_sga =
annual_fixed_sga +
annual_office_rent
```

---

## 15. Revenue

Revenue рассчитывается не через заранее заданную цену токена, а через:

1. utilization доступной мощности;
2. pricing base;
3. target contribution margin;
4. go-live factor.

---

### 15.1 Revenue scenarios

Модель поддерживает три сценария потребления мощности:

1. conservative;
2. base;
3. aggressive.

Каждый сценарий задает:

```text
utilization_of_token_capacity
target_contribution_margin
```

---

### 15.2 Product token allocation

Pricing base распределяется между продуктами пропорционально token share.

```text
product_token_share =
product_tokens / total_tokens
```

---

### 15.3 Revenue go-live logic

Выручка по каждому продукту начинается только после go-live.

Для каждого продукта используются:

```text
go_live_year
go_live_month
```

Логика:

```text
if year < go_live_year:
  revenue_active_months = 0

if year == go_live_year:
  revenue_active_months = 12 - go_live_month + 1

if year > go_live_year:
  revenue_active_months = 12
```

```text
revenue_availability_factor =
revenue_active_months / 12
```

При `go_live_month = 7`:

```text
active_months = 6
revenue_availability_factor = 0.5
```

---

### 15.4 Pricing base

Pricing base включает:

```text
total_cogs +
total_depreciation_and_amortization
```

SG&A не включается в pricing base и учитывается ниже в P&L.

```text
pricing_base =
total_cogs +
total_depreciation_and_amortization
```

---

### 15.5 Revenue formula

```text
sold_tokens =
available_token_capacity × utilization_of_token_capacity

sold_tokens_by_product =
available_tokens_by_product × utilization_of_token_capacity

pricing_base_by_product =
pricing_base × product_token_share

annual_revenue_before_go_live_adjustment =
pricing_base_by_product / (1 - target_contribution_margin)

revenue_by_product =
annual_revenue_before_go_live_adjustment × revenue_availability_factor

total_revenue =
sum(revenue_by_product)

implied_price_per_1m_tokens =
revenue_by_product / sold_tokens_by_product × 1,000,000
```

---

## 16. P&L

P&L строится на основе:

- Revenue;
- COGS;
- SG&A;
- Depreciation & Amortization;
- interest expense;
- profit tax.

---

### 16.1 Revenue

```text
total_revenue =
workplace_ai_revenue +
contact_center_ai_revenue
```

---

### 16.2 COGS

COGS включает delivery costs:

```text
total_cogs =
total_datacenter_opex +
total_team_opex +
annual_gpu_rental_cost
```

---

### 16.3 Gross Profit

```text
gross_profit =
total_revenue -
total_cogs
```

---

### 16.4 EBITDA

```text
ebitda =
gross_profit -
total_sga
```

---

### 16.5 EBIT

```text
ebit =
ebitda -
total_depreciation_and_amortization
```

---

### 16.6 EBT

Interest expense рассчитывается в funding block и попадает ниже EBIT.

```text
ebt =
ebit -
interest_expense
```

---

### 16.7 Profit Tax

```text
profit_tax =
max(ebt, 0) × profit_tax_rate
```

---

### 16.8 Net Income

```text
net_income =
ebt -
profit_tax
```

---

## 17. Cash Flow Statement

Cash Flow Statement строится на основе P&L, CAPEX и Funding.

---

### 17.1 Operating Cash Flow

```text
operating_cash_flow =
net_income +
total_depreciation_and_amortization
```

На текущем этапе working capital не моделируется.

---

### 17.2 Investing Cash Flow

```text
investing_cash_flow =
- gpu_infra_capex
- datacenter_construction_capex
- office_capex
- intangible_capex
```

Важно:

- `gpu_capex` показывает стоимость GPU как оборудования;
- `gpu_infra_capex` показывает полный cash outflow на GPU infrastructure и используется в Cash Flow;
- `gpu_capex` не должен вычитаться дополнительно вместе с `gpu_infra_capex`, чтобы не было двойного учета.

---

### 17.3 Pre-financing Cash Flow

```text
pre_financing_cash_flow =
operating_cash_flow +
investing_cash_flow
```

---

### 17.4 Financing Cash Flow

```text
financing_cash_flow =
equity_injection +
revolver_drawdown -
revolver_repayment
```

---

### 17.5 Net Cash Flow

```text
net_cash_flow =
pre_financing_cash_flow +
financing_cash_flow
```

---

### 17.6 Cash Balance

```text
opening_cash =
previous_year_closing_cash

closing_cash =
opening_cash +
net_cash_flow

cumulative_cash =
cumulative_previous_year +
net_cash_flow
```

---

## 18. Funding Model

Funding model используется для покрытия отрицательного cash balance через:

1. equity;
2. revolver;
3. mix equity / revolver.

---

### 18.1 Funding scenarios

Модель поддерживает три сценария:

```text
equity_only
revolver_only
mix
```

---

### 18.2 equity_only

```text
equity_share = 1.0
revolver_share = 0.0
```

---

### 18.3 revolver_only

```text
equity_share = 0.0
revolver_share = 1.0
```

---

### 18.4 mix

```text
equity_share + revolver_share = 1.0
```

Доли задаются пользователем вручную.

---

### 18.5 Minimum cash balance

Minimum cash balance нужен для операционной устойчивости.

Он рассчитывается как cash buffer на базе фиксированных расходов:

```text
minimum_cash_balance =
monthly_fixed_costs × months_of_fixed_costs
```

Minimum cash balance учитывается при погашении revolver: долг гасится только деньгами сверх cash buffer.

---

### 18.6 Funding need

```text
closing_cash_before_funding =
opening_cash +
pre_financing_cash_flow

funding_need =
max(-closing_cash_before_funding, 0)
```

---

### 18.7 Equity injection

```text
equity_injection =
funding_need × equity_share
```

---

### 18.8 Revolver drawdown

```text
revolver_drawdown =
funding_need × revolver_share
```

---

### 18.9 Cash after drawdown

```text
cash_after_drawdown =
closing_cash_before_funding +
equity_injection +
revolver_drawdown
```

---

### 18.10 Revolver repayment

Revolver автоматически погашается из excess cash сверх minimum cash balance.

```text
excess_cash_available_for_repayment =
max(cash_after_drawdown - minimum_cash_balance, 0)

revolver_repayment =
min(excess_cash_available_for_repayment, opening_revolver_balance)
```

---

### 18.11 Revolver balance

```text
revolver_balance =
opening_revolver_balance +
revolver_drawdown -
revolver_repayment
```

---

### 18.12 Interest expense

```text
average_revolver_balance =
(opening_revolver_balance + revolver_balance) / 2

interest_expense =
average_revolver_balance × revolver_interest_rate
```

Interest expense попадает в P&L ниже EBIT.

---

### 18.13 Closing cash after funding

```text
closing_cash_after_funding =
cash_after_drawdown -
revolver_repayment
```

---

## 19. Balance Sheet

Balance Sheet строится на основе:

- Cash Flow;
- CAPEX;
- D&A;
- Funding;
- P&L.

---

### 19.1 Assets

#### Cash

```text
cash =
closing_cash_after_funding
```

Cash в Balance Sheet берется после funding.

---

#### PP&E

PP&E включает:

- GPU infrastructure;
- datacenter construction;
- office CAPEX.

```text
gross_ppe =
cumulative_gpu_infra_capex +
cumulative_datacenter_construction_capex +
cumulative_office_capex

accumulated_depreciation =
cumulative_total_ppe_depreciation

net_ppe =
gross_ppe -
accumulated_depreciation
```

---

#### Intangible Assets

Intangible Assets включают:

- Workplace.ai IP;
- Contact_Center.ai IP.

```text
gross_intangible_assets =
cumulative_workplace_ai_ip_value +
cumulative_contact_center_ai_ip_value

accumulated_amortization =
cumulative_total_ip_amortization

net_intangible_assets =
gross_intangible_assets -
accumulated_amortization
```

---

#### Total Assets

```text
total_assets =
cash +
net_ppe +
net_intangible_assets
```

---

### 19.2 Liabilities

```text
total_liabilities =
revolver_balance
```

---

### 19.3 Equity

```text
paid_in_capital =
cumulative_equity_injection

retained_earnings =
previous_retained_earnings +
net_income -
dividends

total_equity =
paid_in_capital +
retained_earnings
```

На текущем этапе dividends = 0, если не задано отдельно.

---

### 19.4 Balance Check

```text
balance_check =
total_assets -
total_liabilities -
total_equity
```

Если модель собрана корректно:

```text
balance_check ≈ 0
```

---

## 20. DCF / Investment Metrics

DCF используется для оценки инвестиционной привлекательности GPS.

---

### 20.1 Discount Rate

`discount_rate` используется как WACC proxy / hurdle rate.

Пользователь может менять discount rate в HTML-отчете.

---

### 20.2 Free Cash Flow

Для DCF используется pre-financing free cash flow:

```text
free_cash_flow =
operating_cash_flow +
investing_cash_flow
```

Financing cash flow не должен входить в FCFF.

---

### 20.3 Discount Factor

```text
discount_factor =
1 / (1 + discount_rate) ^ year_index
```

---

### 20.4 Discounted FCF

```text
discounted_fcf =
free_cash_flow × discount_factor
```

---

### 20.5 NPV

```text
npv =
sum(discounted_fcf)
```

---

### 20.6 IRR

```text
irr =
IRR(free_cash_flow_series)
```

Если IRR невозможно посчитать, модель должна возвращать `N/A` или warning, но не падать.

---

### 20.7 Payback

Simple payback:

```text
first year when cumulative_cash > 0
```

Discounted payback:

```text
first year when cumulative_discounted_fcf > 0
```

Если payback не достигнут:

```text
Not reached
```

---

### 20.8 Scenario Comparison

Scenario comparison сравнивает:

- build_own_dc;
- rent_gpu_only;
- hybrid.

Метрики:

- NPV;
- IRR;
- simple payback;
- discounted payback.

---

## 21. Return Metrics

Return metrics показывают эффективность капитала и долговую нагрузку.

---

### 21.1 ROIC

```text
nopat =
ebit × (1 - profit_tax_rate)

invested_capital =
net_ppe +
net_intangible_assets

average_invested_capital =
(invested_capital_beginning + invested_capital_ending) / 2

roic =
nopat / average_invested_capital
```

---

### 21.2 ROE

```text
roe =
net_income / average_equity
```

---

### 21.3 ROA

```text
roa =
net_income / average_total_assets
```

---

### 21.4 Leverage metrics

```text
debt_to_equity =
revolver_balance / total_equity

net_debt =
revolver_balance - cash

net_debt_to_ebitda =
net_debt / ebitda

interest_coverage =
ebit / interest_expense
```

Если знаменатель равен 0 или отрицательный, модель должна возвращать `N/A`, а не падать.

---

## 22. Sensitivity Analysis

Sensitivity analysis показывает влияние ключевых факторов на NPV.

Текущая основная sensitivity table:

```text
NPV sensitivity:
weighted_throughput × target_contribution_margin
```

---

### 22.1 Sensitivity metric

В ячейках таблицы:

```text
NPV
```

---

### 22.2 Row factor: weighted throughput

`weighted_throughput` отражает среднюю производительность GPU с учетом model mix.

Изменение weighted throughput влияет на:

```text
weighted_throughput
→ required_gpu
→ CAPEX / OPEX
→ D&A
→ Cash Flow
→ NPV
```

Sensitivity применяется как multiplier к base weighted throughput.

---

### 22.3 Column factor: target contribution margin

`target_contribution_margin` отражает коммерческую маржинальность.

Изменение contribution margin влияет на:

```text
target_contribution_margin
→ revenue
→ EBITDA
→ Cash Flow
→ NPV
```

Sensitivity применяется как multiplier к base contribution margin curve.

---

### 22.4 Sensitivity calculation logic

```text
adjusted_weighted_throughput =
base_weighted_throughput × weighted_throughput_multiplier

adjusted_required_gpu =
tokens_per_second /
(adjusted_weighted_throughput × utilization) × peak_factor

adjusted_target_contribution_margin =
base_target_contribution_margin × contribution_margin_multiplier

adjusted_revenue =
pricing_base / (1 - adjusted_target_contribution_margin)

adjusted_npv =
NPV(adjusted_free_cash_flow_series, discount_rate)
```

---

## 23. Report Output

`report_output` централизует структуру HTML и CSV отчета.

Отдельные блоки модели не должны иметь собственные `html_output`, чтобы не было нескольких источников правды по отчету.

---

### 23.1 Interactive controls

HTML-отчет должен поддерживать:

1. revenue scenario dropdown;
2. infrastructure scenario dropdown;
3. construction_start_year input;
4. funding scenario dropdown;
5. funding mix inputs;
6. discount rate input.

---

### 23.2 Report tables

HTML и CSV должны включать таблицы:

1. Token Load;
2. GPU Sizing;
3. Infrastructure Scenario;
4. CAPEX;
5. Datacenter Construction CAPEX;
6. Office CAPEX;
7. Intangible Assets / IP;
8. Depreciation & Amortization;
9. Datacenter OPEX;
10. Team OPEX;
11. GPU Rental OPEX;
12. SG&A;
13. Revenue;
14. COGS;
15. P&L Summary;
16. Cash Flow Statement;
17. Funding;
18. Balance Sheet;
19. DCF;
20. Investment Metrics;
21. Return Metrics;
22. Scenario Comparison;
23. Sensitivity Analysis.

---

## 24. Key Modelling Principles

### 24.1 One source of truth

`assumptions.yaml` является единственным источником входных параметров.

---

### 24.2 No manual edits in output files

HTML и CSV генерируются Python-моделью и не редактируются вручную.

---

### 24.3 GPU rental and owned infrastructure are mutually exclusive by scenario

Если GPU rented:

```text
rental OPEX includes hosting / electricity / maintenance
```

Если GPU owned:

```text
datacenter OPEX is calculated separately
```

---

### 24.4 Electricity is calculated only for owned GPU

Electricity не считается по rented GPU, чтобы избежать двойного учета.

---

### 24.5 GPU infrastructure CAPEX includes GPU CAPEX

`gpu_infra_capex` уже включает `gpu_capex`.

В Cash Flow используется:

```text
gpu_infra_capex
```

а не:

```text
gpu_capex + gpu_infra_capex
```

---

### 24.6 SG&A is excluded from pricing base

Pricing base включает:

```text
COGS + D&A
```

SG&A учитывается ниже gross profit при расчете EBITDA.

---

### 24.7 IP capitalization is limited to build phase

Eligible core team roles капитализируются только до go-live.

После go-live команда возвращается в OPEX, если занимается эксплуатацией, поддержкой и развитием продукта.

---

### 24.8 DCF uses pre-financing cash flow

DCF должен использовать FCFF до equity / revolver financing.

Financing влияет на funding, interest expense, Balance Sheet и equity/debt structure, но не должен напрямую увеличивать project FCFF.

---

## 25. Validation Checklist

После изменений в модели нужно запускать:

```bash
python calc_token_load.py
```

Проверить:

1. HTML-отчет генерируется без ошибок;
2. CSV генерируется без ошибок;
3. Token Load считается по обоим продуктам;
4. GPU Sizing использует total annual tokens;
5. Infrastructure scenario dropdown работает;
6. Revenue scenario dropdown работает;
7. Funding scenario dropdown работает;
8. Discount rate input работает;
9. Cash Flow использует `gpu_infra_capex`, а не только `gpu_capex`;
10. Intangible CAPEX попадает в Cash Flow и Balance Sheet;
11. D&A включает PP&E depreciation и IP amortization;
12. P&L считает tax от EBT, а не от EBIT;
13. Balance Check близок к 0;
14. DCF / NPV / IRR пересчитываются;
15. Sensitivity Analysis отображается корректно.
```