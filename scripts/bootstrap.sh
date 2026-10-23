#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "$0")/.."
/usr/bin/python3 -m venv --system-site-packages .venv
uv pip install --python .venv/bin/python -r requirements.lock
uv pip install --python .venv/bin/python --no-deps -e .
if ! command -v Xvfb >/dev/null && [[ ! -x .local/xvfb/usr/bin/Xvfb ]]; then
  mkdir -p .local/debs
  (cd .local/debs && apt-get download xvfb)
  for package in .local/debs/xvfb_*.deb; do dpkg-deb -x "$package" .local/xvfb; done
fi
