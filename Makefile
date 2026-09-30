# Makefile for QE Agentic Dashboard
# Simplified Docker commands

# Default version tag
VERSION ?= latest

# Docker compose file location
# Auto-detect OS: on Linux, layer the host-networking override on top of the base file.
# Set COMPOSE_MODE=portable to force bridge networking even on Linux
# (useful when ports 8000/8080/8501 are already in use on the host).
UNAME_S := $(shell uname -s)
COMPOSE_MODE ?= auto
# --env-file makes docker-compose read the project-root .env for ${VAR} substitution
# in the compose file (otherwise it looks next to the compose file at docker/.env).
ENV_FILE = --env-file .env
ifeq ($(COMPOSE_MODE),portable)
  COMPOSE = docker-compose $(ENV_FILE) -f docker/docker-compose.yml
else ifeq ($(UNAME_S),Linux)
  COMPOSE = docker-compose $(ENV_FILE) -f docker/docker-compose.yml -f docker/docker-compose.linux.yml
else
  COMPOSE = docker-compose $(ENV_FILE) -f docker/docker-compose.yml
endif

.PHONY: help build up down logs clean restart rebuild version ps shell-backend shell-frontend health setup ollama first-run

# Default target
help:
	@echo "QE Agentic Dashboard - Docker Commands"
	@echo ""
	@echo "Current Version: $(VERSION)"
	@echo ""
	@echo "Commands:"
	@echo "  make build      - Build containers"
	@echo "  make up         - Start all services"
	@echo "  make down       - Stop all services"
	@echo "  make logs       - View logs (all services)"
	@echo "  make restart    - Restart all services"
	@echo "  make rebuild    - Rebuild and restart"
	@echo ""
	@echo "Utility Commands:"
	@echo "  make clean      - Remove containers, volumes, and images"
	@echo "  make prune      - Remove unused images only"
	@echo "  make ps         - Show running containers"
	@echo "  make shell-backend  - Open bash shell in backend container"
	@echo "  make shell-frontend - Open shell in frontend container"
	@echo "  make health     - Check health of all services"
	@echo ""
	@echo "Setup Commands:"
	@echo "  make setup      - First-time setup (copy .env template)"
	@echo "  make ollama     - Pull required Ollama models"
	@echo "  make first-run  - Complete first-time setup"
	@echo ""
	@echo "Version Management:"
	@echo "  make version    - Show current version"
	@echo "  make build          - Build all Docker images"

# Main Commands
build:
	@echo "Building Docker images..."
	$(COMPOSE) build

up:
	$(COMPOSE) up -d --remove-orphans --force-recreate

down:
	$(COMPOSE) down

logs:
	$(COMPOSE) logs -f

restart:
	$(COMPOSE) restart

rebuild:
	$(COMPOSE) down
	$(COMPOSE) build --no-cache
	$(COMPOSE) up -d

# Utility Commands
clean:
	$(COMPOSE) down -v --rmi all
	docker system prune -f

prune:
	@echo "Removing old images (keeping latest only)..."
	@docker images --format "{{.Repository}}:{{.Tag}}" | grep -E "^(qe-dashboard|custom-monitoring-dashboard)" | grep -v ":latest" | xargs -r docker rmi 2>/dev/null || true
	@docker rmi qe-dashboard-backend:latest 2>/dev/null || true
	@docker rmi qe-dashboard-frontend:latest 2>/dev/null || true
	@docker image prune -f
	@echo "✅ Cleanup complete - only 'latest' tags remain"

ps:
	$(COMPOSE) ps

shell-backend:
	$(COMPOSE) exec backend bash

shell-frontend:
	$(COMPOSE) exec frontend sh

health:
	@echo "Checking service health..."
	@curl -s http://localhost:8000/api/health | python -m json.tool || echo "Backend not responding"
	@curl -s http://localhost:3000 > /dev/null && echo "Frontend: OK" || echo "Frontend: Not responding"

# Setup Commands
setup:
	@if [ ! -f .env ]; then \
		cp backend/env_template.txt .env; \
		echo ".env file created. Please edit it with your credentials."; \
	else \
		echo ".env file already exists."; \
	fi

ollama:
	@echo "Pulling required Ollama models..."
	ollama pull llama3.2
	ollama pull gemma3:1b
	@echo "Models installed. Verify with: ollama list"

version:
	@echo "Docker images:"
	@docker images | grep qe-dashboard || echo "No images built yet"

# Combined commands
first-run: setup ollama build up

	@echo ""
	@echo "✅ First-time setup complete!"
	@echo "📝 Edit .env file with your credentials"
	@echo "🔄 Then run: make rebuild"
	@echo ""
	@echo "Access the dashboard at:"
	@echo "  Frontend: http://localhost:3000"
	@echo "  Backend:  http://localhost:8000"
	@echo "  API Docs: http://localhost:8000/docs"
