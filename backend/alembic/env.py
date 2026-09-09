"""
Configurazione dell'ambiente Alembic: collega le migrazioni ai modelli SQLAlchemy
dell'app e usa la DATABASE_URL definita in app.core.config.
"""
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.database import Base, DATABASE_URL
from app.models import integrations, organization, saved_view, user  # noqa: F401  (registrano i modelli su Base.metadata)

config = context.config
# Usa l'URL già risolto da app.database (ancora i percorsi SQLite relativi a
# backend/ invece che alla cartella da cui viene lanciato `alembic`).
config.set_main_option("sqlalchemy.url", DATABASE_URL)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Esegue le migrazioni in modalità 'offline' (genera solo SQL)."""
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
    """Esegue le migrazioni in modalità 'online' (connessione diretta al DB)."""
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
