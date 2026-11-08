"""SQLAlchemy models registration package."""

from app.db.base import Base
from app.models.gateway_request_log import GatewayRequestLog
from app.models.model_sync_log import ModelSyncLog
from app.models.provider_credential import ProviderCredential
from app.models.provider_model import ProviderModel
from app.models.rate_limit import RateLimitBucket
from app.models.refresh_token import RefreshToken
from app.models.reliability import (
    CircuitBreakerState,
    CircuitState,
    CredentialHealth,
    HealthStatus,
    QuotaConfidence,
    QuotaResourceType,
    QuotaScope,
    QuotaState,
    ReliabilityEvent,
    ReliabilityEventType,
)
from app.models.routing_decision_log import RoutingDecisionLog
from app.models.routing_policy import VirtualKeyRoutingPolicy
from app.models.routing_state import CredentialPoolState
from app.models.unified_model import UnifiedModel
from app.models.user import User
from app.models.virtual_api_key import VirtualAPIKey

__all__ = [
    "Base",
    "User",
    "ProviderCredential",
    "UnifiedModel",
    "ProviderModel",
    "ModelSyncLog",
    "VirtualAPIKey",
    "GatewayRequestLog",
    "RateLimitBucket",
    "RefreshToken",
    "VirtualKeyRoutingPolicy",
    "CredentialPoolState",
    "RoutingDecisionLog",
    "CredentialHealth",
    "HealthStatus",
    "QuotaState",
    "QuotaScope",
    "QuotaResourceType",
    "QuotaConfidence",
    "CircuitBreakerState",
    "CircuitState",
    "ReliabilityEvent",
    "ReliabilityEventType",
]
