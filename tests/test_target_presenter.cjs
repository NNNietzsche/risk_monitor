const test=require('node:test');
const assert=require('node:assert/strict');
const {metadata,flightLabel,route}=require('../static/target-presenter.js');
const {status,position}=require('../static/target-presenter.js');
test('satellite explanation requires fresh source evidence, port route ignores old ocean label',()=>{
  const m={kind:'vessel',enabled:true,health:'stale',current:{fresh:true,data:{departure_port:'SINGAPORE',arrival_port:'ROTTERDAM',has_newer_satellite_position:true}}};
  assert.equal(route(m,x=>x),'SINGAPORE → ROTTERDAM');
  assert.equal(status(m)[0],'岸基未更新 · 有卫星船位');
  m.current.fresh=false;assert.equal(status(m),null);
  m.current.fresh=true;m.current.data.has_newer_satellite_position=null;assert.equal(status(m),null);
});
test('confirmed landing or schedule is independent of old map position',()=>{
  const m={kind:'aircraft',name:'JA602F',enabled:true,health:'unavailable',current:{fresh:true,data:{flight_number:'NH8442',flight_status:'scheduled',flight_context:'scheduled',departure:'TPE',arrival:'NRT'}},latest:{data:{latitude:35,longitude:140,position_observed_at:'2026-09-30T00:00:00Z'}}};
  assert.equal(status(m)[0],'未起飞');assert.equal(flightLabel(m),'JA602F · 待飞航班 NH8442');
  assert.equal(route(m,x=>x),'TPE → NRT');assert.equal(position(m),m.latest.data);
  m.current.data.flight_status='landed';m.current.data.flight_context='recent';assert.equal(status(m)[0],'最近航班已降落');
  m.current.fresh=false;assert.equal(status(m),null);
});
test('demo contract: identity + ship type, model + aircraft role; no debug source suffix',()=>{
  assert.equal(metadata({kind:'vessel',asset:{imo:'9381234'},business:{category_label:'集装箱船'},source:{is_mock:false}}),'IMO 9381234 · 集装箱船');
  assert.equal(metadata({kind:'vessel',asset:{mmsi:'230000001'},business:{category_label:'油轮'},source:{is_mock:true}}),'MMSI 230000001 · 油轮');
  assert.equal(metadata({kind:'flight',business:{aircraft_model:'B777',category_label:'客机'},provider:'mock-v1'}),'B777 · 客机');
  assert.equal(metadata({kind:'aircraft',business:{aircraft_model:'B737',category_label:'货机'}}),'B737 · 货机');
});
test('aircraft registration, current flight, source category and historical route are distinct',()=>{
  const m={kind:'aircraft',name:'B-20EC',enabled:true,health:'ok',asset:{registration:'B-20EC'},business:{aircraft_model:'Boeing 787-9',category_label:'Passenger'},latest:{data:{flight_number:'HO1656',departure:'MEL',arrival:'PVG'}}};
  assert.equal(metadata(m),'B-20EC · Boeing 787-9 · Passenger');
  assert.equal(flightLabel(m),'B-20EC · 当前航班 HO1656');
  assert.equal(route(m,x=>x),'MEL → PVG');
  m.health='unavailable';
  assert.equal(flightLabel(m),'B-20EC · 最近航班 HO1656');
  assert.equal(route(m,x=>x),'MEL → PVG（历史）');
  m.health='ok';m.latest.data={flight_number:'HO1000',departure:'PVG'};
  assert.equal(route(m,x=>x),'PVG → 目的地未提供');
  assert.equal(flightLabel(m),'B-20EC · 当前航班 HO1000');
});
test('unavailable classification stays visible without guessing from model or vendor',()=>{
  assert.equal(metadata({kind:'aircraft',business:{aircraft_model:'B763'}}),'B763 · 未分类');
  assert.equal(metadata({kind:'flight'}),'机型未提供 · 未分类');
});
