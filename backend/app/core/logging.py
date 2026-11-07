import logging
import sys

from app.core.config import get_settings


class SafeFormatter(logging.Formatter):
    """Logging formatter that ensures readable formatting while stripping sensitive strings."""

    SENSITIVE_KEYWORDS = [
        "password",
        "secret",
        "token",
        "api_key",
        "apikey",
        "authorization",
        "postgres://",
        "postgresql://",
    ]

    def format(self, record: logging.LogRecord) -> str:
        formatted = super().format(record)
        # Basic safeguard against accidental credential exposure in logs
        for keyword in self.SENSITIVE_KEYWORDS:
            if keyword in formatted.lower():
                # Redact if raw URLs containing credentials appear
                if "@" in formatted and ("://" in formatted):
                    parts = formatted.split("://", 1)
                    if len(parts) == 2 and "@" in parts[1]:
                        scheme = parts[0]
                        rest = parts[1]
                        userinfo, hostinfo = rest.split("@", 1)
                        formatted = f"{scheme}://***:***@{hostinfo}"
        return formatted


def setup_logging(log_level: str | None = None) -> None:
    """Configure console logging for the application using settings or explicit level."""
    if log_level is None:
        settings = get_settings()
        log_level = settings.LOG_LEVEL

    numeric_level = getattr(logging, log_level.upper(), logging.INFO)

    log_format = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
    date_format = "%Y-%m-%d %H:%M:%S"

    formatter = SafeFormatter(fmt=log_format, datefmt=date_format)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.setLevel(numeric_level)

    # Avoid duplicate handlers on reloads
    root_logger.handlers = [handler]

    # Reduce log noise from third-party libraries
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.WARNING)


logger = logging.getLogger("unified_ai_gateway")
