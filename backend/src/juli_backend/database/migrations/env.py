from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from juli_backend.core.config.runtime import migration_database_url
from juli_backend.database.database import Base
from juli_backend.models.models import Shop, TikTokCredential, User  # noqa: F401 — register models

config = context.config

# DATABASE_DIRECT_URL first, then DATABASE_URL (#1575).
#
# This read DATABASE_URL directly, which since #1339's cutover is the non-owner
# runtime role `juli_app`. It cannot read public.alembic_version, so alembic
# failed before applying anything — while every other step in the migration path
# (pg_dump, row counts, the revision read) resolved through the helper and
# correctly used the owner. The backup and the migration ran as two roles.
#
# The precedence lives in migration_database_url so this file and
# safe_alembic_helpers cannot drift apart again.
config.set_main_option(
    "sqlalchemy.url",
    migration_database_url(default="postgresql://localhost/juli"),
)

# disable_existing_loggers=False: fileConfig() defaults to True, which sets
# logger.disabled = True on every already-created logger not named in alembic.ini.
# When the migration chain runs in-process (e.g. a test fixture), that permanently
# kills every juli_backend.* logger for the rest of the process — see #1019. Do not
# remove this kwarg "for cleanliness"; that reintroduces the bug.
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
