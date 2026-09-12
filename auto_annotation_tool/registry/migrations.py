"""Migracje schematu lokalnego rejestru SQLite."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable

from .schema import SCHEMA_V1_STATEMENTS, SCHEMA_VERSION


class RegistryMigrationError(RuntimeError):
    """Błąd migracji lub niezgodności wersji rejestru."""


def get_user_version(connection: sqlite3.Connection) -> int:
    row = connection.execute("PRAGMA user_version").fetchone()
    return int(row[0] if row else 0)


def _migrate_to_v1(connection: sqlite3.Connection) -> None:
    for statement in SCHEMA_V1_STATEMENTS:
        connection.execute(statement)


MIGRATIONS: dict[int, Callable[[sqlite3.Connection], None]] = {
    1: _migrate_to_v1,
}


def migrate_database(
    connection: sqlite3.Connection,
    *,
    target_version: int = SCHEMA_VERSION,
) -> int:
    current = get_user_version(connection)
    if current > target_version:
        raise RegistryMigrationError(
            f"Rejestr ma nowszy schemat ({current}) niż obsługiwany przez aplikację "
            f"({target_version})."
        )

    while current < target_version:
        next_version = current + 1
        migration = MIGRATIONS.get(next_version)
        if migration is None:
            raise RegistryMigrationError(
                f"Brak migracji rejestru {current} -> {next_version}."
            )

        try:
            connection.execute("BEGIN IMMEDIATE")
            migration(connection)
            connection.execute(f"PRAGMA user_version = {next_version}")
            connection.commit()
        except Exception as exc:
            connection.rollback()
            raise RegistryMigrationError(
                f"Nie udało się wykonać migracji rejestru "
                f"{current} -> {next_version}: {exc}"
            ) from exc

        current = next_version

    return current
