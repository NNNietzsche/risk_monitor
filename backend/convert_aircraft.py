"""Explicit, atomic conversion of selected fixed-flight monitors; retain all evidence."""
import argparse
import json
from .store import Store, Conflict, encoded, uid, stamp
from .rules import ENGINE_VERSION


def convert(store, registrations):
    changed=[]
    with store.lock, store.connection() as db:
        db.execute('BEGIN IMMEDIATE')
        for reg in registrations:
            rows=db.execute("SELECT m.id FROM monitors m JOIN flight_instances f ON f.id=m.flight_id JOIN assets a ON a.id=f.aircraft_id WHERE m.kind='flight' AND m.deleted_at IS NULL AND m.provider='flightradar-sdk-v1' AND a.registration=?",(reg,)).fetchall()
            if not rows:continue
            if len(rows)!=1:raise Conflict('同一注册号有多个航班监控，请先选择需转换的记录：'+reg)
            m=store._target(db,rows[0]['id']);asset_id=m['flight']['aircraft_id']
            if db.execute('SELECT 1 FROM monitors WHERE asset_id=?',(asset_id,)).fetchone():
                raise Conflict('该飞机已有实体监控，保留原记录并停止转换：'+reg)
            old=m['rule'];config={k:v for k,v in old['config'].items() if k not in {'source_ref','aircraft_registration'}}
            config.update(capabilities=['position','current_flight'],icao24=None)
            rule_id=uid()
            db.execute('INSERT INTO rule_versions VALUES(?,?,?,?,?,?)',(rule_id,'aircraft',old['version']+1,ENGINE_VERSION,encoded(config),stamp()))
            db.execute("UPDATE monitors SET kind='aircraft',name=?,asset_id=?,flight_id=NULL,rule_id=?,state='{}',profile='{}',health='unknown',last_error=NULL,last_poll_at=NULL WHERE id=?",(reg,asset_id,rule_id,m['id']))
            store._audit(db,m['id'],'tracking_changed_to_aircraft',
                         {'kind':m['kind'],'name':m['name'],'flight':m['flight'],'rule':old,'profile':m['profile']},
                         {'kind':'aircraft','registration':reg,'asset_id':asset_id,'rule_id':rule_id})
            changed.append(m['id'])
    return changed


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--db',required=True);p.add_argument('--registration',action='append',required=True)
    args=p.parse_args();print(json.dumps({'converted':convert(Store(args.db),args.registration)}))
