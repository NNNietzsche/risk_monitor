"""Rebuild the monitor CHECK constraint without changing IDs or audit history."""
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


def migrate_aircraft(path):
    db=sqlite3.connect(path,timeout=15)
    try:
        sql=db.execute("SELECT sql FROM sqlite_master WHERE name='monitors'").fetchone()[0]
        if "'aircraft'" not in sql:
            backup=Path(str(path)+'.before-aircraft.bak')
            if not backup.exists():
                with sqlite3.connect(backup) as copy:
                    db.backup(copy)
            db.execute("PRAGMA foreign_keys=OFF")
            db.execute("BEGIN IMMEDIATE")
            new=sql.replace('CREATE TABLE monitors','CREATE TABLE monitors_new').replace("kind='vessel' AND asset_id", "kind IN ('vessel','aircraft') AND asset_id")
            db.execute(new)
            db.execute("INSERT INTO monitors_new SELECT * FROM monitors")
            db.execute("DROP TABLE monitors")
            db.execute("ALTER TABLE monitors_new RENAME TO monitors")
            if db.execute("PRAGMA foreign_key_check").fetchall():
                raise RuntimeError("Monitor migration failed foreign-key validation")
        db.execute("INSERT OR IGNORE INTO schema_versions VALUES(3,?)",(datetime.now(timezone.utc).isoformat(),))
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
