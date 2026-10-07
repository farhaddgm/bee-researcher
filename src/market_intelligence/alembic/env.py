import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool, schema, text
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.config import get_settings
from app.models import Base


config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

settings = get_settings()
config.set_main_option("sqlalchemy.url", settings.database_url)
target_metadata = Base.metadata


def do_run_migrations(connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        include_schemas=True,
        version_table="alembic_version",
        version_table_schema=settings.database_schema,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    configuration = config.get_section(config.config_ini_section)
    connectable = async_engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        exists = await connection.scalar(text("SELECT to_regnamespace(:schema)"), {"schema": settings.database_schema})
        if exists is None:
            await connection.execute(text(f'CREATE SCHEMA "{settings.database_schema}"'))
        await connection.commit()
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    context.configure(
        url=settings.database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        include_schemas=True,
        version_table="alembic_version",
        version_table_schema=settings.database_schema,
    )
    with context.begin_transaction():
        context.execute(
            schema.CreateSchema(settings.database_schema, if_not_exists=True)
        )
        context.run_migrations()
else:
    run_migrations_online()
