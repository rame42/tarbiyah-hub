"""Apply database migrations programmatically (called on every start)."""
from __future__ import annotations

from alembic import command
from alembic.config import Config as AlembicConfig

from .config import PROJECT_ROOT, get_config


def alembic_config() -> AlembicConfig:
    cfg = AlembicConfig()
    cfg.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", get_config().db_url)
    return cfg


def upgrade_db() -> None:
    command.upgrade(alembic_config(), "head")
