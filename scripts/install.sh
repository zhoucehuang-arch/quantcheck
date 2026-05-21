#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
python3 -m venv .venv
. .venv/bin/activate
pip install -U pip
pip install -e .
python -m playwright install chromium
if [ ! -f .env ]; then
  cp .env.example .env
  echo "Created .env. Fill in Quant GT and email credentials before running."
fi
