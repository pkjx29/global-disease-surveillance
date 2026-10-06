.PHONY: up down logs build test lint k8s-local k8s-delete

up:               ## build and start the whole stack (dashboard on http://localhost:8080)
	docker compose up --build -d

down:             ## stop the stack (add ARGS=-v to delete the data volumes)
	docker compose down $(ARGS)

logs:
	docker compose logs -f --tail=50

build:
	docker compose build

test:             ## backend and frontend tests
	cd backend && pytest -q
	cd frontend && npm test

lint:
	cd backend && ruff check .
	cd frontend && npm run lint

k8s-local:        ## deploy to the current kubectl context using the locally built images
	kubectl apply -k k8s/overlays/local

k8s-delete:
	kubectl delete -k k8s/overlays/local
