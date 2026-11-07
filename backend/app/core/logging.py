import logging
import sys


def setup_logging(log_level: str = "INFO") -> None:
    """Configure structured console logging for the application."""
    level = getattr(logging, log_level.upper(), logging.INFO)

    log_format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

    logging.basicConfig(
        level=level,
        format=log_format,
        handlers=[logging.StreamHandler(sys.stdout)],
        force=True,
    )

    # Silence overly verbose third-party loggers
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


logger = logging.getLogger("unified_ai_gateway")
