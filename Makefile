# Company Brain — local command surface.
# Every target calls the repo's real commands. Docker targets need a running
# stack (run `make compose-up` first). Override the compose file to drive the
# lean CI stack instead:  make migrate COMPOSE="docker compose -f docker-compose.ci.yml"

COMPOSE ?= docker compose

.PHONY: help test frontend-check compose-config compose-up compose-down \
        migrate health-check worker-smoke quarantine-integration demo-seed

help:
	@echo "Targets:"
	@echo "  test                   backend pytest suite"
	@echo "  frontend-check         frontend lint + build"
	@echo "  compose-config         validate docker-compose.yml"
	@echo "  compose-up             build + start the full stack (detached)"
	@echo "  compose-down           stop the stack and remove volumes"
	@echo "  migrate                alembic upgrade head + current (in backend container)"
	@echo "  health-check           curl /health/live and /health/ready"
	@echo "  worker-smoke           enqueue tasks.ping and confirm the worker returns it"
	@echo "  quarantine-integration live PG+Redis quarantine lock test"
	@echo "  demo-seed              seed deterministic demo data (needs ENABLE_DEMO_SEED=true)"

# ── Static checks (no running stack needed) ──────────────────────────────────
test:
	cd backend && python -m pytest -q

frontend-check:
	cd frontend && npm run lint && npm run build

compose-config:
	$(COMPOSE) config >/dev/null && echo "compose config OK"

# ── Live stack ───────────────────────────────────────────────────────────────
compose-up:
	$(COMPOSE) up -d --build
	$(COMPOSE) ps

compose-down:
	$(COMPOSE) down -v

migrate:
	$(COMPOSE) exec -T backend alembic upgrade head
	$(COMPOSE) exec -T backend alembic current

health-check:
	curl -f http://localhost:8000/health/live
	curl -f http://localhost:8000/health/ready

worker-smoke:
	$(COMPOSE) exec -T backend python -c "from app.worker import ping; r = ping.delay('local').get(timeout=30); print('ping result:', r); assert r['ok']"

quarantine-integration:
	$(COMPOSE) exec -T -e QUARANTINE_INTEGRATION=1 backend python -m pytest tests/test_integration_quarantine_lock.py -q

# Runs the seed INSIDE the backend container against the live DB. The seed itself
# refuses to run unless ENABLE_DEMO_SEED=true (set here for the container only).
demo-seed:
	$(COMPOSE) exec -T -e ENABLE_DEMO_SEED=true backend python scripts/seed_demo.py
