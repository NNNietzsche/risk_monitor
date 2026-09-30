"""Retire per-vessel geofences and demo targets without changing evidence IDs."""
import json
import sqlite3
import uuid
from datetime import datetime, timezone
from contextlib import closing
from pathlib import Path
from .regions import defaults
from .rules import ENGINE_VERSION


def migrate_core(path):
    db = sqlite3.connect(path, timeout=15)
    db.row_factory = sqlite3.Row
    try:
        if db.execute('SELECT 1 FROM schema_versions WHERE version=5').fetchone():
            return
        backup = Path(str(path)+'.before-core.bak')
        if not backup.exists():
            with sqlite3.connect(backup) as copy:
                db.backup(copy)
        now = datetime.now(timezone.utc).isoformat()
        dump = lambda v: json.dumps(v, ensure_ascii=False, sort_keys=True)
        db.execute('PRAGMA foreign_keys=OFF')
        db.execute('BEGIN IMMEDIATE')
        columns = {r['name'] for r in db.execute('PRAGMA table_info(assets)')}
        if 'source_ref' not in columns:
            db.execute('''CREATE TABLE assets_new(
                id TEXT PRIMARY KEY, kind TEXT NOT NULL CHECK(kind IN ('vessel','aircraft')),
                name TEXT NOT NULL, imo TEXT UNIQUE, mmsi TEXT UNIQUE, registration TEXT UNIQUE,
                source_ref TEXT UNIQUE,
                CHECK((kind='vessel' AND (imo IS NOT NULL OR mmsi IS NOT NULL OR source_ref IS NOT NULL))
                    OR (kind='aircraft' AND registration IS NOT NULL)))''')
            db.execute('INSERT INTO assets_new(id,kind,name,imo,mmsi,registration) SELECT id,kind,name,imo,mmsi,registration FROM assets')
            db.execute('DROP TABLE assets')
            db.execute('ALTER TABLE assets_new RENAME TO assets')
        if 'remark' not in {r['name'] for r in db.execute('PRAGMA table_info(monitors)')}:
            db.execute("ALTER TABLE monitors ADD COLUMN remark TEXT NOT NULL DEFAULT ''")
        # Previous boundaries remain available to historical event evidence.
        for r in db.execute('SELECT * FROM regions WHERE deleted_at IS NULL').fetchall():
            db.execute('UPDATE regions SET deleted_at=? WHERE id=?', (now,r['id']))
            db.execute('INSERT INTO region_audit VALUES(?,?,?,?,?,?)',
                       (str(uuid.uuid4()),r['id'],'retired',dump({'deleted_at':None}),dump({'deleted_at':now}),now))
        for r in defaults():
            db.execute('INSERT INTO regions(id,name,version,geometry,created_at) VALUES(?,?,?,?,?)',
                       (r['id'],r['name'],1,dump(r['geometry']),now))
        for row in db.execute('SELECT m.*,r.version,r.config FROM monitors m JOIN rule_versions r ON r.id=m.rule_id').fetchall():
            if row['provider'] in {'mock-v1','digitraffic-v1','adsblol-v1'}:
                db.execute('UPDATE monitors SET deleted_at=COALESCE(deleted_at,?),enabled=0 WHERE id=?',(now,row['id']))
                db.execute('INSERT INTO configuration_audit VALUES(?,?,?,?,?,?)',
                           (str(uuid.uuid4()),row['id'],'retired_source_archived',dump({'enabled':bool(row['enabled'])}),dump({'enabled':False,'deleted_at':now}),now))
            if row['kind'] != 'vessel':
                continue
            config = json.loads(row['config'])
            if row['provider'] == 'marinetraffic-sdk-v1' and config.get('source_ref'):
                db.execute('UPDATE assets SET source_ref=? WHERE id=?',(config['source_ref'],row['asset_id']))
            config.pop('region_id',None)
            config.pop('min_poll_seconds',None)
            config['region_scope'] = 'all_active'
            rule_id = str(uuid.uuid4())
            db.execute('INSERT INTO rule_versions VALUES(?,?,?,?,?,?)',
                       (rule_id,'vessel',row['version']+1,ENGINE_VERSION,dump(config),now))
            db.execute("""UPDATE monitors SET rule_id=?,state='{}',
                       health=CASE WHEN EXISTS(SELECT 1 FROM observations WHERE monitor_id=monitors.id AND quality='evaluated')
                                   THEN 'pending' ELSE 'unknown' END WHERE id=?""",(rule_id,row['id']))
            db.execute('INSERT INTO configuration_audit VALUES(?,?,?,?,?,?)',
                       (str(uuid.uuid4()),row['id'],'global_regions_enabled',dump({'rule_id':row['rule_id']}),dump({'rule_id':rule_id,'region_scope':'all_active'}),now))
        db.execute('CREATE INDEX IF NOT EXISTS idx_evaluations_observation ON evaluations(observation_id)')
        # The separately versioned cleanup runs after this evidence migration.
        if db.execute('PRAGMA foreign_key_check').fetchall():
            raise RuntimeError('Core migration failed foreign-key validation')
        db.execute('INSERT INTO schema_versions VALUES(5,?)',(now,))
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def retire_unused_feature_data(path):
    """User-authorized removal of the unused news and AI tables, schema v6."""
    with closing(sqlite3.connect(path, timeout=15)) as db, db:
        if db.execute('SELECT 1 FROM schema_versions WHERE version=6').fetchone():
            return
        tables = ('ai_runs', 'ai_settings', 'public_news')
        existing = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        now = datetime.now(timezone.utc)
        if existing.intersection(tables):
            backup = Path(str(path)+'.before-feature-cleanup.'+now.strftime('%Y%m%dT%H%M%S%fZ')+'.bak')
            with sqlite3.connect(backup) as copy:
                db.backup(copy)
                if copy.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
                    raise RuntimeError('Feature cleanup backup failed validation')
        db.execute('PRAGMA foreign_keys=ON')
        db.execute('BEGIN IMMEDIATE')
        for table in tables:
            db.execute('DROP TABLE IF EXISTS '+table)
        if db.execute('PRAGMA foreign_key_check').fetchall():
            raise RuntimeError('Feature cleanup failed foreign-key validation')
        db.execute('INSERT INTO schema_versions VALUES(6,?)', (now.isoformat(),))
