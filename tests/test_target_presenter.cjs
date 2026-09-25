const test=require('node:test');
const assert=require('node:assert/strict');
const {metadata,flightLabel,route}=require('../static/target-presenter.js');
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
