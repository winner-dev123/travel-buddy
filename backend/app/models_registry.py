"""Imports every module's SQLAlchemy models so ``Base.metadata`` is complete.

Used only by Alembic (migrations/env.py) and schema tests. Application code must not import
this module.
"""

from app.core.db import Base
from app.modules.identity import models as identity_models
from app.modules.observability import models as observability_models
from app.modules.platform import models as platform_models
from app.modules.profiles import models as profiles_models

__all__ = ["Base", "identity_models", "observability_models", "platform_models", "profiles_models"]
