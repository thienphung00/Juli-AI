"""SQLAlchemy ORM models."""

from juli_backend.models.ingestion import ShopIngestionState
from juli_backend.models.models import *  # noqa: F403

#: Imported for its side effect: registers `shop_ingestion_state` on `Base.metadata`.
_REGISTERED_OUTSIDE_MODELS_PY = (ShopIngestionState,)
