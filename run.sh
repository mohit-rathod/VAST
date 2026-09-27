#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
exec .venv/bin/uvicorn app.main:app --reload --port 8000
