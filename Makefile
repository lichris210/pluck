install:
	pip install -r requirements-api.txt
	cd frontend && npm install

dev:
	start "Pluck API" cmd /k ".venv\Scripts\uvicorn api.main:app --reload --port 8000"
	cd frontend && npm run dev

dev-api:
	.venv\Scripts\uvicorn api.main:app --reload --port 8000

dev-frontend:
	cd frontend && npm run dev

build:
	cd frontend && npm run build

test:
	.venv\Scripts\pytest tests/ --ignore=tests/integration -q

clean:
	if exist frontend\dist rmdir /s /q frontend\dist
