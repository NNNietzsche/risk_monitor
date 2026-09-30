const test=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
function create(fetch,render){const context={window:{}};vm.runInNewContext(fs.readFileSync('static/timeline-pager.js','utf8'),context);return context.window.TimelinePager.create(fetch,render);}
test('columns page independently, keep historical snapshots and reject invalid page numbers',async()=>{
  const calls=[],renders=[];let snapshot=50;
  const fetch=async p=>{calls.push({...p});return {...p,snapshot:p.snapshot??snapshot,total:25,items:[]};};
  const ship=create(fetch,r=>renders.push(r)),air=create(fetch,()=>{});
  await ship.latest();await air.latest();await ship.go('4');
  assert.equal(calls.at(-1).offset,18);assert.equal(calls.at(-1).snapshot,50);
  snapshot=100;const count=calls.length;await ship.refresh();assert.equal(calls.length,count);
  await air.refresh();assert.equal(calls.at(-1).offset,0);assert.equal(calls.at(-1).snapshot,undefined);
  for(const invalid of ['',0,-1,1.5,6,'bad','Infinity'])await assert.rejects(ship.go(invalid),/整数页码/);
  await ship.previous();assert.equal(calls.at(-1).offset,12);assert.equal(calls.at(-1).snapshot,50);
  await ship.filter({entry_type:'events',severity:'high'});assert.equal(calls.at(-1).offset,0);assert.equal(calls.at(-1).snapshot,undefined);assert.equal(renders.at(-1).page,1);
});
test('outdated responses cannot overwrite filters and automatic refresh cannot cancel navigation',async()=>{
  const pending=[],renders=[];
  const pager=create(p=>new Promise(resolve=>pending.push({p,resolve})),r=>renders.push(r));
  const first=pager.latest();pending[0].resolve({...pending[0].p,total:36,items:[],snapshot:50});await first;
  const navigate=pager.go(3);await pager.refresh();assert.equal(pending.length,2);
  const filter=pager.filter({entry_type:'quality',severity:''});
  pending[2].resolve({...pending[2].p,total:0,items:[],snapshot:60});await filter;
  pending[1].resolve({...pending[1].p,total:36,items:[],snapshot:50});await navigate;
  assert.equal(renders.length,2);assert.equal(renders.at(-1).total,0);assert.equal(renders.at(-1).page,1);assert.equal(renders.at(-1).totalPages,1);
});
test('removed targets clamp historical page to last existing page and failures keep the current page',async()=>{
  let total=24,fail=false;const calls=[],renders=[];
  const pager=create(async p=>{calls.push({...p});if(fail)throw new Error('offline');return {...p,total,items:[],snapshot:50};},r=>renders.push(r));
  await pager.latest();await pager.go(4);total=8;await pager.go(3);
  assert.equal(renders.at(-1).page,2);assert.equal(calls.at(-1).offset,6);assert.equal(calls.at(-1).snapshot,50);
  fail=true;await assert.rejects(pager.latest(),/offline/);const count=calls.length;await pager.refresh();assert.equal(calls.length,count);
});
