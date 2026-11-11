"""
Alembic environment configuration for ExpenseTrack.
Integrates directly with database/engine.py (MariaDB & SQL Server / Azure SQL)
without storing plaintext URLs or credentials in alembic.ini.
"""

from __future__ import annotations

import logging
from logging.config import fileConfig

from alembic import context

from database.engine import (
    create_db_engine,
    dispose_engine,
    load_database_settings,
)
from database.models import Base

config = context.config

# Configure Alembic logging without clobbering existing application root loggers
if config.config_file_name is not None and not logging.getLogger().handlers:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def include_object(object_, name, type_, reflected, compare_to):
    """
    Exclude MariaDB's migration-managed virtual column and dialect-specific budget
    uniqueness indexes from noisy diff noise during cross-engine checks.
    """
    if type_ == "column" and reflected and name == "category_scope_key":
        return False
    if type_ == "index" and name in (
        "uq_budgets_user_scope_period",
        "uq_budgets_user_overall_period",
        "uq_budgets_user_category_period",
    ):
        return False
    return True


def run_migrations_offline() -> None:
    """Emit SQL DDL offline without opening a live database socket."""
    settings = load_database_settings()
    dialect_url = settings.url

    context.configure(
        url=dialect_url.render_as_string(hide_password=False),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        include_object=include_object,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against live MariaDB or SQL Server via database/engine.py."""
    connectable = create_db_engine(pool_size=1, max_overflow=0)
    try:
        with connectable.connect() as connection:
            context.configure(
                connection=connection,
                target_metadata=target_metadata,
                compare_type=True,
                include_object=include_object,
                transactional_ddl=True,
            )

            with context.begin_transaction():
                context.run_migrations()
    finally:
        dispose_engine(connectable)


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

