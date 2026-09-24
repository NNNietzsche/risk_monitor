"""Reversible removals preserve original data and configuration history."""
from .store import NotFound, Conflict, stamp, uid, encoded, unpack
from .models import BusinessProfile


def update_profile(store, monitor_id, profile: BusinessProfile):
    with store.lock, store.connection() as db:
        db.execute('BEGIN IMMEDIATE')
        m=store._target(db,monitor_id)
        if m['deleted_at']:raise Conflict('目标已删除，请先恢复')
        values=profile.model_dump()
        if m['kind']=='vessel' and (values['aircraft_role'] or values['aircraft_model']):raise ValueError('船舶不能填写航空属性')
        if m['kind']!='vessel' and values['vessel_type']:raise ValueError('航空目标不能填写船型')
        db.execute('UPDATE monitors SET profile=? WHERE id=?',(encoded(values),monitor_id))
        store._audit(db,monitor_id,'profile_changed',m['profile'],values)
    return store.detail(monitor_id)


def remove_monitor(store,monitor_id):
    with store.lock, store.connection() as db:
        db.execute('BEGIN IMMEDIATE');m=store._target(db,monitor_id)
        if not m['deleted_at']:
            when=stamp();db.execute('UPDATE monitors SET deleted_at=?,enabled=0 WHERE id=?',(when,monitor_id))
            store._audit(db,monitor_id,'deleted',{'enabled':m['enabled'],'deleted_at':None},{'enabled':False,'deleted_at':when})
    return {'id':monitor_id,'deleted':True}


def restore_monitor(store,monitor_id):
    with store.lock, store.connection() as db:
        db.execute('BEGIN IMMEDIATE');m=store._target(db,monitor_id)
        if m['region'] and m['region'].get('deleted_at'):raise Conflict('请先恢复该目标使用的区域')
        if m['deleted_at']:
            db.execute('UPDATE monitors SET deleted_at=NULL,enabled=0 WHERE id=?',(monitor_id,))
            store._audit(db,monitor_id,'restored',{'deleted_at':m['deleted_at']},{'deleted_at':None,'enabled':False})
    return store.detail(monitor_id)


def change_region_deleted(store,region_id,deleted):
    with store.lock, store.connection() as db:
        db.execute('BEGIN IMMEDIATE')
        region=unpack(db.execute('SELECT * FROM regions WHERE id=?',(region_id,)).fetchone())
        if not region:raise NotFound('区域不存在')
        if deleted:
            users=db.execute("SELECT m.name FROM monitors m JOIN rule_versions r ON r.id=m.rule_id WHERE m.deleted_at IS NULL AND json_extract(r.config,'$.region_id')=?",(region_id,)).fetchall()
            if users:raise Conflict('区域仍被以下目标使用（含暂停目标）：'+'、'.join(row['name'] for row in users))
        when=stamp() if deleted else None
        if bool(region['deleted_at'])!=deleted:
            db.execute('UPDATE regions SET deleted_at=? WHERE id=?',(when,region_id))
            db.execute('INSERT INTO region_audit VALUES(?,?,?,?,?,?)',(uid(),region_id,'deleted' if deleted else 'restored',encoded({'deleted_at':region['deleted_at']}),encoded({'deleted_at':when}),stamp()))
    return {'id':region_id,'deleted':deleted}
