// Candidates are actual recent observations, never synthetic target identities.
async function publicTargets(){
  openDialog('接入公开真实数据');
  $('dialog-body').append(el('p','正在读取公开源最近的船舶和东京附近飞机，请稍候。','detail-note'));
  const [result,regions]=await Promise.all([api('/public/targets'),api('/regions')]);
  openDialog('接入公开真实数据');
  const box=$('dialog-body');
  box.append(el('p','从当前有信号的目标开始试用。公开接收范围会变化；飞机离开范围后可能失去更新。船舶需选择监控围栏，测试围栏不代表真实风险评级。','detail-note'));
  for(const error of result.errors)box.append(el('p',error,'detail-note'));
  const region=select(box,'船舶监控区域','region_id',regions.map(r=>[r.id,r.name]));
  const test=regions.find(r=>r.name.startsWith('波罗的海测试围栏'));if(test)region.value=test.id;
  for(const item of result.items){
    const row=el('div',undefined,'list-row'),isShip=item.kind==='vessel';
    row.append(el('p',result.sources[item.provider]?.name||item.provider,'detail-note'));
    row.append(el('strong',item.name),el('p',`${isShip?'MMSI '+item.mmsi:'ICAO24 '+item.icao24+' · 呼号 '+(item.callsign||'未提供')} · 数据时间 ${fmt(item.observed_at)} JST`));
    const add=el('button','添加并采集');
    const exists=dashboard?.monitors.some(m=>isShip?m.kind==='vessel'&&m.asset.mmsi===item.mmsi:m.kind==='aircraft'&&m.asset.registration===item.aircraft_registration);
    if(exists){add.disabled=true;add.textContent='已添加';}
    add.onclick=()=>action(async()=>{
      const value={kind:item.kind,name:item.name,provider:item.provider};
      if(isShip){value.mmsi=item.mmsi;value.region_id=region.value;}else{value.aircraft_registration=item.aircraft_registration;value.icao24=item.icao24;}
      const target=await api('/monitors','POST',value);
      const polled=await api('/monitors/'+target.id+'/poll','POST',{});
      await refresh();await showMonitor(target.id);$('dialog-error').textContent='采集结果：'+polled.outcome;
    },add);
    row.append(add);box.append(row);
  }
}
