# coding=utf-8
from alembic.config import Config
from alembic import command
from euphorie.client.model import Session
from logging import getLogger
from pkg_resources import resource_filename
from sqlalchemy.exc import NoSuchTableError
from sqlalchemy.schema import Table
from sqlalchemy.schema import MetaData


logger = getLogger(__name__)


def TableExists(session, table):
    connection = session.bind
    return connection.dialect.has_table(connection, table)


def ColumnExists(session, table, column):
    connection = session.bind
    metadata = MetaData(connection)
    table = Table(table, metadata)
    try:
        connection.dialect.reflecttable(
            connection, table, None, exclude_columns=tuple()
        )
    except NoSuchTableError:
        return False
    return column in table.c


def alembic_upgrade(revision):
    script_location = resource_filename("euphorie.deployment.upgrade", "alembic")
    url = Session().bind.engine.url.__to_string__(hide_password=False)
    alembic_cfg = Config()
    alembic_cfg.set_main_option("script_location", script_location)
    alembic_cfg.set_main_option("sqlalchemy.url", url)
    try:
        command.upgrade(alembic_cfg, revision)
    except Exception:
        logger.exception(
            "Migration failed, you might need to adapt the script to match "
            "your DB state"
        )
