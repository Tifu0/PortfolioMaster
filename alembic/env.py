import os
import sys
from logging.config import fileConfig
from dotenv import load_dotenv

load_dotenv()

from sqlalchemy import engine_from_config, pool
from alembic import context

# Add project root and src to path
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(CURRENT_DIR, ".."))
SRC_DIR = os.path.join(PROJECT_ROOT, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from portfoliomaster.db.schema import Base
from portfoliomaster.db.session import get_database_url, normalize_database_url, psycopg_connect_args

try:
    config = context.config
except AttributeError:
    config = None

if config is not None and config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def get_url(cfg=None) -> str:
    """Resolve database URL for Alembic migrations.
    
    Priority:
    1. Environment variable DATABASE_URL (always wins in deployment/production).
    2. Explicit non-placeholder alembic.ini config (if set and not driver:// or placeholder).
    3. Project get_database_url() (handles normalization and production fail-closed).
    """
    env_url = os.environ.get("DATABASE_URL")
    if env_url and env_url.strip():
        return get_database_url()

    active_config = cfg or config
    if active_config is not None:
        ini_url = active_config.get_main_option("sqlalchemy.url")
        if ini_url and ini_url.strip():
            clean_ini = ini_url.strip()
            if not clean_ini.startswith("driver://") and "user:pass@localhost" not in clean_ini:
                return normalize_database_url(clean_ini)

    return get_database_url()


def _ensure_offline_mock_inspector() -> None:
    """Register a minimal inspector for SQLAlchemy MockConnection during offline --sql mode."""
    from sqlalchemy.engine.mock import MockConnection
    from sqlalchemy.inspection import _inspects, _registrars

    if MockConnection in _registrars:
        return

    class _OfflineMockInspector:
        def get_table_names(self, schema=None):
            return []

        def get_indexes(self, table_name, schema=None):
            return []

        def get_unique_constraints(self, table_name, schema=None):
            return []

        def get_check_constraints(self, table_name, schema=None):
            return []

    @_inspects(MockConnection)
    def _inspect_mock_connection(subject):
        return _OfflineMockInspector()


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    _ensure_offline_mock_inspector()
    url = get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,
        output_buffer=config.stdout,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    configuration = config.get_section(config.config_ini_section, {})
    url = get_url()
    configuration["sqlalchemy.url"] = url

    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        connect_args=psycopg_connect_args(url),
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if config is not None:
    if context.is_offline_mode():
        run_migrations_offline()
    else:
        run_migrations_online()
