#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export QUANTCHECK_HOME="${QUANTCHECK_HOME:-$PWD}"
. .venv/bin/activate
exec quantcheck --daemon
