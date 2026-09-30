import json,sqlite3
from pathlib import Path
from backend.store import Store,stamp,encoded
from backend.migrations import migrate_aircraft,migrate_management


def test_v4_migration_preserves_evidence_archives_old_regions_and_demo(tmp_path):
    path=tmp_path/'legacy.db';now=stamp()
    with sqlite3.connect(path) as db:
        db.executescript((Path(__file__).parent/'fixtures/schema-v4.sql').read_text())
        db.execute('INSERT INTO schema_versions VALUES(1,?)',(now,))
    migrate_aircraft(path);migrate_management(path)
    with sqlite3.connect(path) as db:
        db.execute('INSERT INTO regions(id,name,version,geometry,created_at) VALUES(?,?,?,?,?)',('old','Old area',1,encoded({'bbox':[40,10,50,20]}),now))
        for ident,provider in [('live','marinetraffic-sdk-v1'),('demo','mock-v1')]:
            db.execute('INSERT INTO assets(id,kind,name,mmsi) VALUES(?,?,?,?)',(ident,'vessel',ident,'999000001' if ident=='live' else '999000002'))
            db.execute('INSERT INTO rule_versions VALUES(?,?,?,?,?,?)',(ident,'vessel',1,'1.1.0',encoded({'region_id':'old','source_ref':'5630138','max_age_seconds':3600}),now))
            db.execute('INSERT INTO monitors(id,name,kind,asset_id,rule_id,provider,created_at) VALUES(?,?,?,?,?,?,?)',(ident,ident,'vessel',ident,ident,provider,now))
        db.execute('INSERT INTO raw_records VALUES(?,?,?,?,?,?,?,?)',('raw','live','marinetraffic-sdk-v1',now,'{}','hash','evaluated',None))
        db.execute('INSERT INTO observations VALUES(?,?,?,?,?,?)',('observation','live','raw',now,encoded({'kind':'vessel','observed_at':now,'latitude':15,'longitude':45}),'evaluated'))
        db.execute('INSERT INTO evaluations VALUES(?,?,?,?,?,?,?)',('evaluation','live','observation','live',now,'evaluated',encoded({'region':{'id':'old'}})))
        db.execute('INSERT INTO risk_events VALUES(?,?,?,?,?,?,?,?,?,?)',('event','live','evaluation','live','vessel.first_seen_inside','warning',now,now,'Old evidence',encoded({'raw_id':'raw'})))
        for table in ['public_news','ai_runs','ai_settings']:
            db.execute('CREATE TABLE '+table+'(id TEXT PRIMARY KEY)')
            db.execute('INSERT INTO '+table+' VALUES(?)',('retired',))
        preserved={t:db.execute('SELECT * FROM '+t).fetchall() for t in ['raw_records','observations','evaluations','risk_events']}
    store=Store(path)
    assert {r['id'] for r in store.regions()}=={'hormuz','aden'}
    assert store.detail('live')['health']=='pending'
    assert store.detail('live')['rule']['version']==2
    assert store.detail('live')['asset']['source_ref']=='5630138'
    assert store.detail('demo')['deleted_at'] and not store.detail('demo')['enabled']
    assert [m['id'] for m in store.monitors()]==['live']
    with sqlite3.connect(path) as db:
        for t,rows in preserved.items():assert db.execute('SELECT * FROM '+t).fetchall()==rows
        assert not db.execute('PRAGMA foreign_key_check').fetchall()
        assert db.execute("SELECT config FROM rule_versions WHERE id='live'").fetchone()[0].find('region_id')>=0
        for table in ['public_news','ai_runs','ai_settings']:
            assert db.execute('SELECT id FROM '+table).fetchone()[0]=='retired'
    reopened=Store(path)
    assert reopened.detail('live')['rule']['version']==2
    assert len(reopened.regions(include_deleted=True))==3
    with sqlite3.connect(str(path)+'.before-core.bak') as backup:
        assert backup.execute('SELECT id FROM public_news').fetchone()[0]=='retired'
