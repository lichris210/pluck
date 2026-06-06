import logging
import os
import sys

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

load_dotenv()

# Operator-facing log format: WHERE (name:funcName:lineno) + WHAT (the message).
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s:%(funcName)s:%(lineno)d - %(message)s"


def configure_logging() -> None:
    """Attach a stdout handler with LOG_FORMAT to the root logger.

    Level comes from LOG_LEVEL (default INFO). Logs go to stdout so Railway
    captures them. The handler is tagged so a re-import never stacks duplicates,
    and propagation is left intact so pytest's caplog still captures cleanly.
    """
    level_name = (os.environ.get("LOG_LEVEL") or "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    root = logging.getLogger()
    root.setLevel(level)
    root.handlers = [h for h in root.handlers if not getattr(h, "_pluck", False)]

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(LOG_FORMAT))
    handler._pluck = True  # marker so we replace (not stack) on re-import
    root.addHandler(handler)

    # Silence the per-request HTTP client logs — they add no operational value.
    # Apify and Pluck app logs stay at the root level (INFO by default).
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


configure_logging()

# Imported after logging is configured so module-level loggers inherit the root config.
from api import routes  # noqa: E402

app = FastAPI(title="Pluck.ai API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(routes.router)


@app.get("/api/health")
async def health():
    return {"status": "ok", "version": "1.0.0"}


_FRONTEND_DIST = os.path.join(os.path.dirname(__file__), "..", "frontend", "dist")

if os.path.isdir(_FRONTEND_DIST):
    app.mount("/", StaticFiles(directory=_FRONTEND_DIST, html=True), name="static")
