.PHONY: help venv install run agent ingest reingest slots book match db reset clean

PY  := .venv/bin/python
PIP := .venv/bin/pip

CLINIC ?= 1
PATIENT ?= 1
DATE   ?= 2026-09-30
TIME   ?= 09:00

help:
	@echo "make venv      - create the virtualenv"
	@echo "make install   - install dependencies"
	@echo "make run       - start the chat UI and API on http://127.0.0.1:8000"
	@echo "make agent     - chat with the NextDim portal agent in the terminal"
	@echo "make ingest    - load data/*.csv into SQLite"
	@echo "make reingest  - reset the database, then ingest"
	@echo "make slots     - free slots of a clinic      (CLINIC=4 DATE=2026-09-30)"
	@echo "make book      - book a slot                  (CLINIC=4 PATIENT=7 DATE=2026-09-30 TIME=09:30)"
	@echo "make match     - top 3 clinics for a patient  (PATIENT=7 DATE=2026-09-30, needs OPENAI_API_KEY)"
	@echo "make db        - print the database path"
	@echo "make reset     - delete the database"
	@echo "make clean     - delete the database and caches"

venv:
	python3 -m venv .venv

install:
	$(PIP) install -r requirements.txt

run:
	.venv/bin/uvicorn app.main:app --reload --port 8000

agent:
	$(PY) -m agents.nextdim.agent

ingest:
	$(PY) -m app.ingest

reingest: reset
	$(PY) -m app.ingest

slots:
	@$(PY) -c "import json; from tools.available_slots import available_slots; print(json.dumps(available_slots($(CLINIC), '$(DATE)'), indent=2))"

book:
	@$(PY) -c "import json; from tools.book import book_appointment; print(json.dumps(book_appointment($(CLINIC), $(PATIENT), '$(DATE)', '$(TIME)'), indent=2))"

match:
	@$(PY) -c "import json; from tools.match_clinics import suggest_clinics; print(json.dumps(suggest_clinics($(PATIENT), '$(DATE)'), indent=2))"

db:
	@$(PY) -c "from app.db import DB_PATH; print(DB_PATH)"

reset:
	rm -f data/vast.db data/vast.db-wal data/vast.db-shm

clean: reset
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
