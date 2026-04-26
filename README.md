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


## Почему в GitHub после merge снова 60 строк

Кнопка **Accept incoming changes** в веб-конфликте часто оставляет "чужую" (старую) сторону конфликта.
Для `calc_token_load.py` это может вернуть короткую версию файла.

Надёжный способ: решать конфликт локально в ветке PR и пушить заново.

```bash
# 1) в ветке PR
git checkout <your_pr_branch>
git fetch origin
git merge origin/main

# 2) если конфликт в calc_token_load.py
#    оставьте версию из вашей ветки (ours)
git checkout --ours calc_token_load.py
#    или если нужна версия из main, тогда --theirs

# 3) проверьте, что в индексе именно нужный файл
wc -l calc_token_load.py
git add calc_token_load.py
git commit -m "Resolve conflict: keep updated calc_token_load.py"
git push
```

Проверка перед нажатием Merge в GitHub:

```bash
git show HEAD:calc_token_load.py | wc -l
```

Число строк в `HEAD` должно совпадать с тем, что вы ожидаете (например, 345).
