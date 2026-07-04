#!/bin/zsh
# Dzienny obieg yt-brief odpalany lokalnie (launchd). Loguje do logs/run.log.
set -o pipefail
REPO=/Users/bartosz/Apki/yt-brief
cd "$REPO" || exit 1
mkdir -p logs
STAMP=$(date "+%Y-%m-%d %H:%M")
{
  echo "===== $STAMP start ====="
  git pull --quiet --rebase 2>&1 || echo "! git pull nieudany (kontynuuję na lokalnym kodzie)"
  ./.venv/bin/python -m src.run_daily 2>&1 | grep -vE "NotOpenSSL|warnings.warn|FutureWarning|google\.|non-supported|end of life|urllib3"
  RC=$?
  git add data/brief.db docs/ 2>/dev/null
  if git diff --cached --quiet; then
    echo "brak zmian do wypchnięcia"
  else
    git commit -q -m "brief $(date -u +%F) (lokalny)" && git push -q origin main && echo "wypchnięto na GitHub (deploy Pages ruszy sam)"
  fi
  echo "===== $STAMP koniec (rc=$RC) ====="
  echo ""
} >> logs/run.log 2>&1
