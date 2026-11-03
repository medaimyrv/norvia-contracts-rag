.PHONY: help install lint fmt test test-unit test-integration samples eval eval-fake up down logs ps

BACKEND := backend
UV := uv --directory $(BACKEND)

help:  ## Lista los comandos disponibles
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-18s %s\n", $$1, $$2}'

install:  ## Instala dependencias del backend (crea backend/.venv)
	$(UV) sync

lint:  ## Lint y formato (sin modificar archivos)
	$(UV) run ruff check .
	$(UV) run ruff format --check .

fmt:  ## Aplica formato y arreglos automáticos
	$(UV) run ruff check --fix .
	$(UV) run ruff format .

test:  ## Todos los tests (los de integración requieren Docker)
	$(UV) run pytest

test-unit:  ## Solo tests unitarios (sin Docker)
	$(UV) run pytest -m "not integration"

test-integration:  ## Solo tests de integración (requiere Docker)
	$(UV) run pytest -m integration

samples:  ## Regenera los PDFs sintéticos de samples/ (deterministas)
	$(UV) run python scripts/generate_samples.py

eval:  ## Eval de recuperación con Gemini (usa la caché; la clave de .env solo si faltan vectores)
	@set -a; [ -f .env ] && . ./.env; set +a; LITELLM_MODE=PRODUCTION \
		$(UV) run python ../eval/run_eval.py --provider gemini --write ../eval/results_gemini.md

eval-fake:  ## Eval con el proveedor falso (prueba del script, no mide calidad semántica)
	$(UV) run python ../eval/run_eval.py --provider fake --write ../eval/results_fake.md

up:  ## Levanta todo el stack (API, worker, PostgreSQL, Redis)
	docker compose up --build -d

down:  ## Para el stack (conserva los volúmenes)
	docker compose down

logs:  ## Sigue los logs de API y worker
	docker compose logs -f api worker

ps:  ## Estado y salud de los servicios
	docker compose ps
