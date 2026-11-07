from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Declarative Base for all future database models.

    Future models (User, ProviderAccount, ProviderCredential, ModelRegistry,
    VirtualAPIKey, UsageRecord, RoutingPolicy) will inherit from this class.
    """

    pass
