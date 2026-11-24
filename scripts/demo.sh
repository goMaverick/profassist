#!/usr/bin/env sh
# One-command ProfAssist POC demo (Linux/macOS/WSL/Git Bash).
# Never prints secrets. .env is gitignored.
set -eu

cd "$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"

if [ ! -f .env ]; then
  cp .env.example .env
  cat <<'MSG'

Created .env from .env.example.
Open .env, set GEMINI_API_KEY=your-key, then re-run this script.
(.env is gitignored - never commit it.)
MSG
  exit 1
fi

if ! grep -qE '^GEMINI_API_KEY=[^[:space:]]' .env; then
  cat <<'MSG'

GEMINI_API_KEY is empty in .env.
Open .env, set GEMINI_API_KEY=your-key, then re-run this script.
MSG
  exit 1
fi

if command -v curl >/dev/null 2>&1; then
  fetch() { curl -fsS --max-time 3 "$1" >/dev/null 2>&1; }
elif command -v wget >/dev/null 2>&1; then
  fetch() { wget -q -T 3 -O /dev/null "$1"; }
else
  echo "This script needs curl or wget." >&2
  exit 1
fi

echo "> Building app, prefect-runner, frontend..."
docker compose build app prefect-runner frontend
echo "> Starting the stack..."
docker compose up -d --force-recreate

echo "> Waiting for the API (up to 3 minutes)..."
i=0
while [ "$i" -lt 60 ]; do
  if fetch http://localhost:8000/api/v1/health; then
    echo "  API is healthy"
    break
  fi
  i=$((i + 1))
  printf '.'
  sleep 3
done
echo ""

if ! fetch http://localhost:8000/api/v1/health; then
  echo "API did not become healthy. Run: docker compose logs -f" >&2
  exit 1
fi

cat <<'MSG'

ProfAssist POC is up:
  App:          http://localhost:3000
  Register:     http://localhost:3000/register
  API:          http://localhost:8000
  API docs:     http://localhost:8000/docs
  Langfuse:     http://localhost:3100
  MLflow:       http://localhost:5000
  Prefect:      http://localhost:4200
  Moodle mock:  http://localhost:8090/health

Register at /register; the first user becomes app admin.
Moodle is preconfigured against the mock: Test/Sync at
  http://localhost:3000/admin/integrations/moodle

Logs: docker compose logs -f    Stop: docker compose down
MSG
