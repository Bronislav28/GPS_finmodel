# GPS_finmodel

Python-модель ДЗО по ИИ на основе `assumptions.yaml`.

## Запуск

```bash
python -m pip install -r requirements.txt
python calc_token_load.py
```

## Что генерируется

- `output/gps_finmodel_results.csv`
- `output/gps_finmodel.html`

## Если нет PyYAML

Скрипт не падает с traceback, а выводит понятную инструкцию по установке:

```bash
python -m pip install -r requirements.txt
```

(Зависимость объявлена в `requirements.txt`.)
