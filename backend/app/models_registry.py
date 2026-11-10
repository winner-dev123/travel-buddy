"""Imports every module's SQLAlchemy models so ``Base.metadata`` is complete.

Used only by Alembic (migrations/env.py) and schema tests. Application code must not import
this module.
"""

from app.core.db import Base
from app.modules.ai_assistant import models as ai_assistant_models
from app.modules.billing import models as billing_models
from app.modules.connections import models as connections_models
from app.modules.destinations import models as destinations_models
from app.modules.feed import models as feed_models
from app.modules.groups import models as groups_models
from app.modules.identity import models as identity_models
from app.modules.location import models as location_models
from app.modules.media import models as media_models
from app.modules.messaging import models as messaging_models
from app.modules.notifications import models as notifications_models
from app.modules.observability import models as observability_models
from app.modules.platform import models as platform_models
from app.modules.profiles import models as profiles_models
from app.modules.social import models as social_models
from app.modules.trips import models as trips_models
from app.modules.trust_safety import models as trust_safety_models

__all__ = [
    "Base",
    "ai_assistant_models",
    "billing_models",
    "connections_models",
    "destinations_models",
    "feed_models",
    "groups_models",
    "identity_models",
    "location_models",
    "media_models",
    "messaging_models",
    "notifications_models",
    "observability_models",
    "platform_models",
    "profiles_models",
    "social_models",
    "trips_models",
    "trust_safety_models",
]
