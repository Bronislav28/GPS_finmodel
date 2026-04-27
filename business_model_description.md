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
9. required_gpu_increment по годам
10. gpu_capex по годам
11. total_capex по годам
12. depreciation по годам

# Входные данные

Основной файл:
- assumptions.yaml

# CAPEX calculation

Python-модель должна дополнительно рассчитывать по годам 2026–2030:

1. required_gpu
2. required_gpu_increment
3. gpu_capex
4. total_capex
5. depreciation

Формулы:

- required_gpu берётся из GPU calculation model
- required_gpu_increment = max(required_gpu текущего года - required_gpu предыдущего года, 0)
- для 2026 года required_gpu_increment = required_gpu
- gpu_capex = required_gpu_increment * capex.gpu.unit_cost
- total_capex = gpu_capex * capex.infra_multiplier.value
- depreciation считается straight-line на срок capex.depreciation.useful_life_years

HTML-отчёт должен включать отдельную таблицу CAPEX по годам со столбцами:

- year
- required_gpu
- required_gpu_increment
- gpu_unit_cost
- gpu_capex
- infra_multiplier
- total_capex
- annual_depreciation

# OPEX calculation

Python-модель должна дополнительно рассчитывать OPEX по годам 2026–2030.

## Datacenter OPEX

Расчет производится на основе блока opex.datacenter:

Шаги:

1. average_gpu = (gpu_beginning_of_year + gpu_end_of_year) / 2

2. Расчет мощности:
- it_load_mw = average_gpu * gpu_power_kw / 1000
- total_load_mw = it_load_mw * pue

3. Расчет потребления:
- electricity_kwh = total_load_mw * 1000 * operating_hours_per_day * calendar_days_per_year

4. Расчет цены электроэнергии:
- price_2026 = base_price_per_kwh
- price_t = price_previous_year * (1 + annual_growth_t)

5. electricity_cost = electricity_kwh * electricity_price_t

6. Дополнительные расходы:
- maintenance_cost = total_capex * maintenance_percent_of_capex
- network_cost = total_load_mw * network_cost_per_mw_per_year
- land_rent = total_load_mw * land_rent_per_mw_per_year

7. datacenter_opex = electricity_cost + maintenance_cost + network_cost + land_rent

8. other_opex = datacenter_opex * other_opex_percent

9. total_datacenter_opex = datacenter_opex + other_opex

---

## Team OPEX

Расчет производится на основе блока team:

1. Для каждого месяца:
- monthly_fte = core_team_target_fte * hiring_plan_monthly

2. Для каждой роли:
- monthly_gross_salary берется из salary_gross_monthly_rub

3. Доплаты:
- monthly_bonus = monthly_gross * bonus_percent_of_gross
- monthly_social = (monthly_gross + monthly_bonus) * social_contribution_sfr_percent_of_gross

4. Fully loaded cost:
- monthly_cost_per_fte = monthly_gross + monthly_bonus + monthly_social

5. Monthly team cost:
- monthly_team_cost = monthly_fte * monthly_cost_per_fte

6. Annual team cost:
- annual_team_opex = сумма monthly_team_cost

7. Учет роста зарплат:
- salary_t = salary_previous_year * (1 + salary_growth_t)

---

## Total OPEX

- total_opex = total_datacenter_opex + annual_team_opex

---

## HTML-отчет должен включать:

### Datacenter OPEX
- year
- average_gpu
- total_load_mw
- electricity_kwh
- electricity_price
- electricity_cost
- maintenance_cost
- network_cost
- land_rent
- total_datacenter_opex

### Team OPEX
- year
- avg_fte
- annual_team_opex

### Total OPEX
- year
- datacenter_opex
- team_opex
- total_opex

# Выходные данные

Python должен сформировать:
- таблицу pandas DataFrame
- CSV с результатами
- HTML-отчёт с таблицей (включая CAPEX)

# Важно

- YAML не должен содержать расчёты, только assumptions.
- Все формулы реализуются в Python.
- Если поле formula есть в YAML, использовать его только как описание.
