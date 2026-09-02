"""Compatibility surface for ``from juli_backend.repositories.repos import X``.

Every repository used to live in this one module. They now live one aggregate
per module (see the package docstring); this file re-exports them so existing
imports keep working. New code imports from ``juli_backend.repositories``.

``ProcessedEventsRepo`` is the MMU-9a legacy alias for the ETL ingest
repository. It is the only name here that is not a repository of this package,
and the ``repositories -> services`` edge it needs is carried in the
import-boundary baseline for this file alone; the real modules stay inside the
``repositories -> {models, database}`` matrix.
"""

from __future__ import annotations

from juli_backend.repositories import *  # noqa: F401,F403
from juli_backend.repositories import __all__ as _package_all
from juli_backend.services.etl.persistence.ingest import ProcessedEventsRepo

__all__ = [*_package_all, "ProcessedEventsRepo"]
