"""Imports every module's SQLAlchemy models so ``Base.metadata`` is complete.

Used only by Alembic (migrations/env.py) and schema tests. Application code must not import
this module.
"""

from app.core.db import Base
from app.modules.destinations import models as destinations_models
from app.modules.identity import models as identity_models
from app.modules.location import models as location_models
from app.modules.observability import models as observability_models
from app.modules.platform import models as platform_models
from app.modules.profiles import models as profiles_models
from app.modules.social import models as social_models

__all__ = [
    "Base",
    "destinations_models",
    "identity_models",
    "location_models",
    "observability_models",
    "platform_models",
    "profiles_models",
    "social_models",
]
