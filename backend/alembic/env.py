"""Alembic migration environment.

- Reads MYSQL_DSN from .env
- Uses sync engine (alembic does not support async DSN)
- Auto-detects models from Base.metadata
"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# Make the `app` package importable
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.config import settings
from app.db.base import Base
from app.db.models import *  # noqa: F401, F403  register all models

# Alembic config object
config = context.config

# Convert aiomysql DSN to pymysql (alembic is sync).
sync_dsn = settings.mysql_dsn.replace("+aiomysql", "+pymysql")

# IMPORTANT: Do NOT use config.set_main_option() because alembic's
# configparser treats `%` as interpolation syntax (e.g. `%(here)s`),
# which breaks URL-encoded passwords like `Lb%40403706`.
# Workaround: pass the DSN directly via engine_from_config override,
# which skips configparser interpolation entirely.

# Build a section dict where sqlalchemy.url is our sync DSN, then merge
# on top of any [alembic] section values from alembic.ini.
config_section = config.get_section(config.config_ini_section, {})
config_section["sqlalchemy.url"] = sync_dsn

# Configure logging from alembic.ini (if present)
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Target metadata (for autogenerate)
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Offline mode: generate SQL without DB connection."""
    context.configure(
        url=sync_dsn,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Online mode: connect to DB and run migrations."""
    connectable = engine_from_config(
        config_section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()