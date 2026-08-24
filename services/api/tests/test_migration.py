from pathlib import Path

from alembic import command
from alembic.config import Config


def test_alembic_upgrade_and_downgrade_on_sqlite(tmp_path: Path) -> None:
    database_path = tmp_path / "migration.sqlite3"
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{database_path.as_posix()}")

    command.upgrade(config, "head")
    command.downgrade(config, "base")

    assert database_path.exists()
