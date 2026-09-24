const test=require('node:test');
const assert=require('node:assert/strict');
const {metadata}=require('../static/target-presenter.js');
test('demo contract: identity + ship type, model + aircraft role; no debug source suffix',()=>{
  assert.equal(metadata({kind:'vessel',asset:{imo:'9381234'},business:{category_label:'集装箱船'},source:{is_mock:false}}),'IMO 9381234 · 集装箱船');
  assert.equal(metadata({kind:'vessel',asset:{mmsi:'230000001'},business:{category_label:'油轮'},source:{is_mock:true}}),'MMSI 230000001 · 油轮');
  assert.equal(metadata({kind:'flight',business:{aircraft_model:'B777',category_label:'客机'},provider:'mock-v1'}),'B777 · 客机');
  assert.equal(metadata({kind:'aircraft',business:{aircraft_model:'B737',category_label:'货机'}}),'B737 · 货机');
});
test('unavailable classification stays visible without guessing from model or vendor',()=>{
  assert.equal(metadata({kind:'aircraft',business:{aircraft_model:'B763'}}),'B763 · 未分类');
  assert.equal(metadata({kind:'flight'}),'机型未提供 · 未分类');
});
