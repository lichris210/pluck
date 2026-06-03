# Pluck — dev commands

`python` is not on PATH. Use `.venv\Scripts\python.exe` for everything.

## Run the API server

```powershell
.venv\Scripts\python.exe -m uvicorn api.main:app --reload --port 8000
```

ASGI app object: `app` in `api/main.py`. Runs on http://localhost:8000.

## Run tests

```powershell
.venv\Scripts\python.exe -m pytest -q -m "not integration"
```

Integration tests hit live network and are deselected by default. To run a single file:

```powershell
.venv\Scripts\python.exe -m pytest tests/test_cache_store.py -v
```
