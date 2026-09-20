#!/usr/bin/env bash
# Сохранить data/puma.db в репозиторий. Общий шаг для обоих воркфлоу.
#
# База — это память бота: без неё каждый прогон считал бы все скидки новыми.
# На GitHub файл живёт между запусками только потому, что мы коммитим его сюда.
#
# Почему не просто `git push`: пока бот работал, человек мог запушить свою
# правку, и тогда пуш отклоняется, а состояние теряется. Поэтому берём базу
# в сторону, встаём на свежий main, возвращаем базу и пробуем снова.
#
# Ветку называем явно (HEAD:main): так скрипт не зависит от того, под каким
# именем её выложил actions/checkout.
set -u

if [ ! -f data/puma.db ]; then
  echo "базы нет — сохранять нечего"
  exit 0
fi

git config user.name "puma-bot"
git config user.email "puma-bot@users.noreply.github.com"

keep="${RUNNER_TEMP:-/tmp}/puma-state.db"
cp data/puma.db "$keep"

for try in 1 2 3; do
  git fetch -q origin main
  git reset -q --hard FETCH_HEAD
  cp "$keep" data/puma.db
  git add -f data/puma.db

  if git diff --staged --quiet; then
    echo "состояние не менялось — коммитить нечего"
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
