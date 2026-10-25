"""The database upgrades itself when the code adds a column."""
import sqlite3
import tempfile
import unittest
from pathlib import Path

import helpers  # noqa: F401
from tracker import db


class Upgrade(unittest.TestCase):
    def test_old_database_gets_new_column_and_keeps_its_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "old.db"
            old = sqlite3.connect(path)  # a database made before company_cik existed
            old.execute("CREATE TABLE filings (accession_number TEXT PRIMARY KEY, cik INTEGER NOT NULL, "
                        "status TEXT DEFAULT 'pending', selected INTEGER DEFAULT 1)")
            old.execute("INSERT INTO filings (accession_number, cik, status) VALUES ('A1', 320193, 'downloaded')")
            old.commit()
            old.close()

            conn = db.connect(path)
            row = conn.execute("SELECT cik, company_cik, status FROM filings").fetchone()
            conn.close()
        self.assertEqual(tuple(row), (320193, 320193, "downloaded"))


if __name__ == "__main__":
    unittest.main()
