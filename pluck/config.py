import logging
import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


_TRUTHY = {"1", "true", "yes", "on"}


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in _TRUTHY


@dataclass
class Config:
    anthropic_api_key: str | None
    apify_token: str | None
    use_planner: bool = False


def get_config() -> Config:
    anthropic_api_key = os.getenv("ANTHROPIC_API_KEY")
    apify_token = os.getenv("APIFY_TOKEN")
    use_planner = _truthy(os.getenv("USE_PLANNER"))

    if not anthropic_api_key:
        logger.debug("ANTHROPIC_API_KEY is not set — Claude extraction will not be available")

    return Config(
        anthropic_api_key=anthropic_api_key,
        apify_token=apify_token,
        use_planner=use_planner,
    )
