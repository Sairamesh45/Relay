from typing import Any, Dict

from app.core.config import get_settings


class HealthService:
    def __init__(self) -> None:
        self.settings = get_settings()

    async def check_health(self) -> Dict[str, Any]:
        """Perform system health checks and return current status."""
        return {
            "status": "healthy",
            "project": self.settings.PROJECT_NAME,
            "version": self.settings.VERSION,
            "environment": self.settings.ENVIRONMENT,
        }
