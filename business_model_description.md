# Цель модели

Построить Python-модель ДЗО по ИИ, которая читает assumptions.yaml и рассчитывает:

1. active users по Workplace.ai
2. daily tokens и annual tokens по Workplace.ai
3. automated interactions по Contact_Center.ai
4. daily tokens и annual tokens по Contact_Center.ai
5. total annual tokens по ДЗО
6. долю каждого сервиса в токенах
7. required_gpu по годам 2026–2030
8. required_gpu_increment по годам 2026–2030
9. gpu_capex, total_capex и depreciation по годам 2026–2030
10. таблицу результатов по годам 2026–2030

# Входные данные

Основной файл:
- assumptions.yaml

Новые блоки assumptions:
- `gpu_calculation`
- `capex`

# Выходные данные

Python должен сформировать:
- таблицу pandas DataFrame
- CSV с результатами
- HTML-отчёт с таблицей (включая CAPEX)

# Важно

- YAML не должен содержать расчёты, только assumptions.
- Все формулы реализуются в Python.
- Если поле formula есть в YAML, использовать его только как описание.
