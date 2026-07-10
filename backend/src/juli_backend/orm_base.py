"""Declarative base shared by the ORM models and the database layer.

Kept intentionally dependency-free (no models, no repositories, no engine
wiring) so that importing it never triggers the ``database`` or ``models``
package ``__init__`` modules. Both ``database.database`` and ``models.models``
import ``Base`` from here, which breaks the historical import cycle between the
two packages regardless of which one is imported first.
"""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
