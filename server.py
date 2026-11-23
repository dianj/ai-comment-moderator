"""Entry point: `uvicorn server:app`. The application lives in the `moderator` package."""
from moderator.api import app  # noqa: F401
