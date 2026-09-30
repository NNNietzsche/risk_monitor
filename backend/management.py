"""Reversible removals preserve original data and configuration history."""
from .store import NotFound, Conflict, stamp, uid, encoded, unpack


def update_remark(store, monitor_id, body):
    with store.lock, store.connection() as db:
        db.execute('BEGIN IMMEDIATE')
        m=store._target(db,monitor_id)
        if m['deleted_at']:raise Conflict('目标已删除，请先恢复')
        db.execute('UPDATE monitors SET remark=? WHERE id=?',(body.remark,monitor_id))
        store._audit(db,monitor_id,'remark_changed',{'remark':m['remark']},body.model_dump())
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
        if m['provider'] not in store.providers:raise Conflict('该历史目标的数据源已停用，无法恢复')
        if m['deleted_at']:
            db.execute('UPDATE monitors SET deleted_at=NULL,enabled=0 WHERE id=?',(monitor_id,))
            store._audit(db,monitor_id,'restored',{'deleted_at':m['deleted_at']},{'deleted_at':None,'enabled':False})
    return store.detail(monitor_id)


def change_region_deleted(store,region_id,deleted):
    with store.lock, store.connection() as db:
        db.execute('BEGIN IMMEDIATE')
        region=unpack(db.execute('SELECT * FROM regions WHERE id=?',(region_id,)).fetchone())
        if not region:raise NotFound('区域不存在')
        when=stamp() if deleted else None
        if bool(region['deleted_at'])!=deleted:
            db.execute('UPDATE regions SET deleted_at=? WHERE id=?',(when,region_id))
            db.execute('INSERT INTO region_audit VALUES(?,?,?,?,?,?)',(uid(),region_id,'deleted' if deleted else 'restored',encoded({'deleted_at':region['deleted_at']}),encoded({'deleted_at':when}),stamp()))
    return {'id':region_id,'deleted':deleted}
