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

# Выходные данные

Python должен сформировать:
- таблицу pandas DataFrame
- CSV с результатами
- HTML-отчёт с таблицей

# Важно

- YAML не должен содержать расчёты, только assumptions.
- Все формулы реализуются в Python.
- Если поле formula есть в YAML, использовать его только как описание.