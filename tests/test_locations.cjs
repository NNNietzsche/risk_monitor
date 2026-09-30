const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {createLookup,airport}=require('../static/locations.js');
const source=JSON.parse(fs.readFileSync(path.join(__dirname,'../static/places.json'),'utf8'));
test('local marine labels, land exclusion, dateline and invalid coordinates',()=>{
  const lookup=createLookup(source);
  assert.equal(lookup(40,18),'红海');
  assert.equal(lookup(47,12),'亚丁湾');
  assert.equal(lookup(52,12),'阿拉伯海');
  assert.match(lookup(-150,20),/太平洋/);
  assert.match(lookup(179,10),/太平洋/);
  assert.match(lookup(-179,10),/太平洋/);
  assert.equal(lookup(45,15),'海域未知');
  assert.equal(lookup(null,null),'暂无定位');
  assert.equal(lookup(181,10),'暂无定位');
});
test('marine holes do not count as the surrounding sea',()=>{
  const polygon=[[[0,0],[10,0],[10,10],[0,10],[0,0]],[[2,2],[4,2],[4,4],[2,4],[2,2]]];
  const lookup=createLookup({land:[],seas:[{name:'Test sea',polygon}]});
  assert.equal(lookup(1,1),'Test sea');
  assert.equal(lookup(3,3),'海域未知');
});
test('airport labels use names and retain codes with explicit missing data',()=>{
  assert.equal(airport('HND'),'东京羽田（HND）');
  assert.equal(airport('PVG'),'上海浦东（PVG）');
  assert.equal(airport('TPE'),'台北桃园（TPE）');
  assert.equal(airport('ABC','Source Airport'),'Source Airport（ABC）');
  assert.equal(airport('ZZZ'),'机场名称未提供（ZZZ）');
});
