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


def migrate_management(path):
    db=sqlite3.connect(path,timeout=15)
    try:
        if db.execute('SELECT 1 FROM schema_versions WHERE version=4').fetchone():return
        backup=Path(str(path)+'.before-management.bak')
        if not backup.exists():
            with sqlite3.connect(backup) as copy:db.backup(copy)
        db.execute('BEGIN IMMEDIATE')
        for table,column,kind in [('monitors','deleted_at','TEXT'),('monitors','profile',"TEXT NOT NULL DEFAULT '{}'"),('regions','deleted_at','TEXT')]:
            columns={r[1] for r in db.execute('PRAGMA table_info('+table+')')}
            if column not in columns:db.execute(f'ALTER TABLE {table} ADD COLUMN {column} {kind}')
        db.execute('CREATE TABLE IF NOT EXISTS region_audit(id TEXT PRIMARY KEY,region_id TEXT NOT NULL REFERENCES regions(id),action TEXT NOT NULL,before_value TEXT NOT NULL,after_value TEXT NOT NULL,created_at TEXT NOT NULL)')
        db.execute('INSERT INTO schema_versions VALUES(4,?)',(datetime.now(timezone.utc).isoformat(),))
        db.commit()
    except Exception:
        db.rollback();raise
    finally:
        db.close()
