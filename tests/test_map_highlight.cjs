const test=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
// Small DOM double exercises map interaction without launching a browser.
class Node {
  constructor(tag){this.tag=tag;this.attributes={};this.children=[];this.classes=new Set();this.classList={toggle:(name,on)=>on?this.classes.add(name):this.classes.delete(name)};}
  setAttribute(k,v){this.attributes[k]=String(v);}
  append(...children){for(const c of children){if(c.parent)c.parent.children=c.parent.children.filter(x=>x!==c);c.parent=this;this.children.push(c);}}
  replaceChildren(){this.children=[];}
}
function setup(){
  const roots={'vessel-map':new Node('div'),'flight-map':new Node('div')};
  const context={window:{},document:{getElementById:id=>roots[id],createElement:t=>new Node(t),createElementNS:(_,t)=>new Node(t)}};
  vm.runInNewContext(fs.readFileSync('static/target-presenter.js','utf8'),context);
  vm.runInNewContext(fs.readFileSync('static/maps.js','utf8'),context);
  return {maps:context.window.RiskMaps,roots};
}
const target=(id,longitude=20)=>({id,name:id,kind:'vessel',enabled:true,health:'ok',state:{inside:id==='a'},latest:{observed_at:'2026-09-11T00:00:00Z',data:{longitude,latitude:60}}});
const markers=root=>root.children[0].children.filter(n=>n.attributes['data-monitor-id']);
test('first stale source position has a timestamp and does not require evaluated history',()=>{
  const {maps,roots}=setup();const m={...target('new'),health:'stale',latest:null,current:{data:{latitude:15,longitude:45,observed_at:'2026-09-29T01:00:00Z'}}};
  maps.draw('vessel-map',[m],()=>{});
  const marker=markers(roots['vessel-map'])[0];assert(marker);
  assert.match(marker.children.find(n=>n.tag==='title').textContent,/2026-09-29T01:00:00Z · 历史定位/);
});
test('highlight picks one target, retains risk color and view, clears and stays map-local',()=>{
  const {maps,roots}=setup();maps.draw('vessel-map',[target('a'),target('b')],()=>{});maps.draw('flight-map',[target('c')],()=>{});
  const [a,b]=markers(roots['vessel-map']);const before=JSON.stringify(roots['vessel-map'].children[0].attributes);const dot=a.children.find(n=>n.tag==='circle'&&n.attributes.r==='8');
  const color=dot.attributes.fill;
  assert.equal(maps.highlight('vessel-map','a'),true);assert(a.classes.has('is-highlighted'));assert(b.classes.has('is-dimmed'));
  assert.equal(markers(roots['vessel-map']).at(-1),a);assert.equal(dot.attributes.fill,color);assert.equal(JSON.stringify(roots['vessel-map'].children[0].attributes),before);
  assert(!markers(roots['flight-map'])[0].classes.has('is-dimmed'));
  maps.highlight('vessel-map','b');assert(!a.classes.has('is-highlighted'));assert(b.classes.has('is-highlighted'));
  maps.highlight('vessel-map',null);assert(!a.classes.has('is-dimmed'));assert(!b.classes.has('is-highlighted'));
});
test('missing and off-screen targets are explained and redraw retains highlight',()=>{
  const {maps,roots}=setup();maps.draw('vessel-map',[target('a',-170),target('b',170)],()=>{});
  assert.equal(maps.highlight('vessel-map','missing'),false);assert.equal(roots['vessel-map'].children[2].hidden,false);
  roots['vessel-map'].children[1].children[0].onclick();maps.highlight('vessel-map','b');assert.match(roots['vessel-map'].children[2].textContent,/视野外/);
  maps.draw('vessel-map',[target('a',-170),target('b',170)],()=>{});assert(markers(roots['vessel-map']).find(n=>n.attributes['data-monitor-id']==='b').classes.has('is-highlighted'));
  maps.highlight('vessel-map',null);assert(roots['vessel-map'].children[2].hidden);
});
