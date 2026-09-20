#!/usr/bin/env bash
# Сохранить в репозиторий то, что прогон изменил в папке data/. Общий шаг воркфлоу.
#
# Два файла, и они разной природы:
#
#   data/puma.db      память бота. Запомненная цена значит «карточку уже
#                     отправили», потерять строку = прислать карточку повторно.
#                     Поэтому базы СЛИВАЮТСЯ, а не перезаписываются.
#   data/latest.json  выгрузка витрины для Cloudflare Worker. Это снимок, который
#                     каждый обход собирает заново, так что свой всегда свежее.
#
# Две ловушки, на которых шаг уже спотыкался:
#
# 1. Прогон, который data/ вообще не трогал, раньше всё равно выкладывал свою
#    копию — и откатывал состояние другого прогона назад. Поэтому сначала
#    проверяем, изменилось ли хоть что-то.
#
# 2. Два прогона на GitHub могут идти параллельно, и второй держит файлы,
#    выложенные ДО первого. Просто положить своё сверху нельзя — потеряются чужие
#    строки. Поэтому базу сливаем через merge-state.py.
#
# Ветку называем явно (HEAD:main): так скрипт не зависит от того, под каким
# именем её выложил actions/checkout.
set -eu

DB=data/puma.db
JSON=data/latest.json

# Проверки идут через if, а не через &&: при set -e цепочка, кончившаяся
# ненулевым кодом, уронила бы весь скрипт на первом же неизменённом файле.
changed=0
if [ -f "$DB" ] && ! git diff --quiet HEAD -- "$DB"; then changed=1; fi
if [ -f "$JSON" ] && ! git diff --quiet HEAD -- "$JSON"; then changed=1; fi
if [ "$changed" -eq 0 ]; then
  echo "этот прогон data/ не менял — сохранять нечего"
  exit 0
fi

git config user.name "puma-bot"
git config user.email "puma-bot@users.noreply.github.com"

tmp="${RUNNER_TEMP:-/tmp}"
rm -f "$tmp/puma-state.db" "$tmp/latest.json"
if [ -f "$DB" ]; then cp "$DB" "$tmp/puma-state.db"; fi
if [ -f "$JSON" ]; then cp "$JSON" "$tmp/latest.json"; fi

for try in 1 2 3; do
  git fetch -q origin main
  git reset -q --hard FETCH_HEAD          # свежий main вместе с чужими коммитами

  if [ -f "$tmp/puma-state.db" ]; then
    if ! python .github/merge-state.py "$DB" "$tmp/puma-state.db"; then
      echo "слияние базы сорвалось — лучше упасть, чем потерять состояние"
      exit 1
    fi
    git add -f "$DB"
  fi
  if [ -f "$tmp/latest.json" ]; then
    cp "$tmp/latest.json" "$JSON"         # снимок, сливать нечего: свой свежее
    git add -f "$JSON"
  fi

  if git diff --staged --quiet; then
    echo "после слияния изменений не осталось — коммитить нечего"
    exit 0
  fi

  git commit -qm "state $(date -u '+%Y-%m-%d %H:%M')"
  if git push -q origin HEAD:main; then
    echo "состояние сохранено (попытка $try)"
    exit 0
  fi
  echo "пуш отклонён (кто-то запушил раньше), пробую снова"
done

echo "не смог сохранить состояние за 3 попытки"
exit 1
