"""Explicit test fixture import; never runs on service startup or replaces history."""
import argparse
import json
import os
from pathlib import Path
from .models import MonitorCreate,RegionCreate
from .store import Store


def add_samples(store,path):
    rows=json.loads(Path(path).read_text(encoding='utf-8'))
    region=next((r for r in store.regions() if r['name']=='红海测试围栏（仅联调，非风险评级）'),None)
    if not region:region=store.create_region(RegionCreate(name='红海测试围栏（仅联调，非风险评级）',west=32,south=12,east=44,north=30))
    ids=[]
    for row in rows:
        existing=next((m for m in store.monitors(include_deleted=True) if m['provider']==row['provider'] and m['rule']['config'].get('source_ref')==row['source_ref']),None)
        if existing:
            if existing['deleted_at']:continue
            ids.append(existing['id']);continue
        data=dict(row)
        if data['kind']=='vessel':data['region_id']=region['id']
        ids.append(store.create_monitor(MonitorCreate(**data))['id'])
    return ids


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--file',required=True)
    parser.add_argument('--db',default=os.getenv('RISK_DB_PATH','data/risk.db'))
    parser.add_argument('--poll',action='store_true',help='Explicitly fetch each imported sample once')
    args=parser.parse_args();store=Store(args.db)
    ids=add_samples(store,args.file)
    for mid in ids:
        result=store.poll(mid) if args.poll else {'outcome':'registered_without_fetch'}
        print(json.dumps({'name':store.detail(mid)['name'],**result},ensure_ascii=True))
