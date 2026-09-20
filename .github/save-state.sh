#!/usr/bin/env bash
# Сохранить data/puma.db в репозиторий. Общий шаг для обоих воркфлоу.
#
# База — это память бота: запомненная цена значит «карточку уже отправили».
# Потерять строку = прислать карточку повторно. Поэтому шаг устроен осторожно.
#
# Две ловушки, на которых он уже спотыкался:
#
# 1. Прогон, который базу вообще не открывал (--answer без /start), раньше всё
#    равно выкладывал свою копию — и откатывал состояние часового обхода назад.
#    Поэтому сначала проверяем, трогал ли этот прогон файл.
#
# 2. Два прогона на GitHub могут идти параллельно, и второй держит базу,
#    выложенную ДО первого. Просто положить свой файл сверху нельзя — потеряются
#    чужие строки. Поэтому не копируем, а сливаем через merge-state.py.
set -eu

if [ ! -f data/puma.db ]; then
  echo "базы нет — сохранять нечего"
  exit 0
fi

if git diff --quiet HEAD -- data/puma.db; then
  echo "этот прогон базу не трогал — сохранять нечего"
  exit 0
fi

git config user.name "puma-bot"
git config user.email "puma-bot@users.noreply.github.com"

keep="${RUNNER_TEMP:-/tmp}/puma-state.db"
cp data/puma.db "$keep"

for try in 1 2 3; do
  git fetch -q origin main
  git reset -q --hard FETCH_HEAD          # свежий main вместе с чужими коммитами
  if ! python .github/merge-state.py data/puma.db "$keep"; then
    echo "слияние базы сорвалось — лучше упасть, чем потерять состояние"
    exit 1
  fi
  git add -f data/puma.db

  if git diff --staged --quiet; then
    echo "после слияния состояние не изменилось — коммитить нечего"
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
