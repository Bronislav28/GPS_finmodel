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


## Проверка перед PR (чтобы не улетели старые 60 строк)

Перед `git push` и открытием PR выполните:

```bash
pwd
git rev-parse --is-inside-work-tree
wc -l calc_token_load.py
git log --oneline -- calc_token_load.py -n 5
git show HEAD:calc_token_load.py | wc -l
```

Ожидаемо:

- `git rev-parse --is-inside-work-tree` → `true`
- `wc -l calc_token_load.py` и `git show HEAD:calc_token_load.py | wc -l` дают одинаковое число строк
- в `git log -- calc_token_load.py` виден последний коммит с обновлённым файлом

После merge проверьте уже в целевой ветке:

```bash
git checkout main
git pull
git show HEAD:calc_token_load.py | wc -l
```

Если тут снова `60`, значит в merge попал не тот commit/branch и нужно либо re-merge правильной ветки, либо cherry-pick нужного SHA.
