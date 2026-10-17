.PHONY: help up down logs seed test build-frontend dev-backend dev-frontend

help:
	@echo "HCA System"
	@echo "  make up             Build and start the Docker stack (seeds the administrator)"
	@echo "  make down           Stop the stack"
	@echo "  make logs           Follow backend logs"
	@echo "  make seed           Re-run the idempotent administrator bootstrap"
	@echo "  make test           Run backend tests"
	@echo "  make build-frontend Build the production frontend bundle"

up:
	docker compose up --build -d
	@echo "Frontend: http://localhost:8080  API: http://localhost:8000/docs"

down:
	docker compose down

logs:
	docker compose logs -f backend

seed:
	docker compose exec backend python -m app.seed_admin

test:
	cd backend && python -m pytest -q

build-frontend:
	cd frontend && npm run build

dev-backend:
	cd backend && uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

dev-frontend:
	cd frontend && npm run dev -- --host 0.0.0.0
