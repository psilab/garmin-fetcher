DC = docker compose -f docker-compose.dev.yml

up:
	$(DC) up

down:
	$(DC) down

logs:
	$(DC) logs -f

composer:
	$(DC) run --rm backend composer $(filter-out $@,$(MAKECMDGOALS))

%:
	@:
