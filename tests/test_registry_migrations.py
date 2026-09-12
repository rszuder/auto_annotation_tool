import sqlite3
import tempfile
import unittest
from pathlib import Path

from auto_annotation_tool.registry import RegistryDatabase, SCHEMA_VERSION
from auto_annotation_tool.registry.schema import SCHEMA_V1_STATEMENTS


class RegistryMigrationTests(unittest.TestCase):
    def test_existing_v1_database_migrates_to_v2_without_losing_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "alpr_registry.sqlite3"
            connection = sqlite3.connect(str(db_path))
            try:
                connection.execute("PRAGMA foreign_keys = ON")
                for statement in SCHEMA_V1_STATEMENTS:
                    connection.execute(statement)
                connection.execute("PRAGMA user_version = 1")
                connection.execute(
                    """
                    INSERT INTO projects (
                        project_id,
                        campaign_key,
                        folder_name,
                        display_name
                    ) VALUES (?, ?, ?, ?)
                    """,
                    ("PRJ-OLD", "old", "old_ABC123", "Old"),
                )
                connection.execute(
                    """
                    INSERT INTO datasets (
                        dataset_id,
                        owner_project_id,
                        target,
                        name,
                        purpose,
                        provenance_status
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "DS-MT-OLD",
                        "PRJ-OLD",
                        "plate",
                        "old_dataset",
                        "training",
                        "partial",
                    ),
                )
                connection.commit()
            finally:
                connection.close()

            database = RegistryDatabase(db_path)
            version = database.initialize()
            self.assertEqual(version, SCHEMA_VERSION)

            with database.read_connection() as connection:
                project_count = connection.execute(
                    "SELECT COUNT(*) FROM projects"
                ).fetchone()[0]
                dataset_count = connection.execute(
                    "SELECT COUNT(*) FROM datasets"
                ).fetchone()[0]
                locations_exists = connection.execute(
                    """
                    SELECT COUNT(*)
                    FROM sqlite_master
                    WHERE type='table' AND name='dataset_locations'
                    """
                ).fetchone()[0]

            self.assertEqual(project_count, 1)
            self.assertEqual(dataset_count, 1)
            self.assertEqual(locations_exists, 1)


if __name__ == "__main__":
    unittest.main()
