# ──────────────────────────────────────────────────────────────
#  VigilZone Monorepo — One-command operations
# ──────────────────────────────────────────────────────────────

COMPOSE = docker compose

.PHONY: up down logs ps restart build clean

## Start all services (build if needed)
up:
	$(COMPOSE) up --build -d
	@echo ""
	@echo "  VigilZone is starting…"
	@echo "  UI:       http://localhost:8085"
	@echo "  Backend:  http://localhost:8000/api/"
	@echo "  AI:       http://localhost:8080"
	@echo "  RTSP:     rtsp://localhost:8554/webcam"
	@echo ""

## Stop all services and remove volumes
down:
	$(COMPOSE) down -v

## Tail logs from all services
logs:
	$(COMPOSE) logs -f

## Show running containers
ps:
	$(COMPOSE) ps

## Restart a specific service (usage: make restart s=backend)
restart:
	$(COMPOSE) restart $(s)

## Rebuild without cache
build:
	$(COMPOSE) build --no-cache

## Full cleanup: containers, volumes, images
clean:
	$(COMPOSE) down -v --rmi local
