'use strict';
(() => {
  const data=m=>m.current?.data||m.latest?.data||{};
  function position(m){
    return [m.current?.data,m.latest?.data].filter(d=>d?.latitude!=null&&d?.longitude!=null)
      .sort((a,b)=>Date.parse(b.position_observed_at||b.observed_at)-Date.parse(a.position_observed_at||a.observed_at))[0];
  }
  function status(m){
    if(!m.enabled||!m.current?.fresh)return null;
    const d=data(m);
    if(m.kind==='vessel'&&d.has_newer_satellite_position===true&&m.health!=='ok')return ['岸基未更新 · 有卫星船位','warning'];
    if(m.kind==='vessel')return null;
    if(d.flight_status==='landed')return [d.flight_context==='recent'?'最近航班已降落':'已降落',''];
    if(d.flight_status==='scheduled')return ['未起飞',''];
    if(d.flight_status==='cancelled')return ['航班已取消','high'];
    if(d.flight_status==='diverted')return ['航班已备降','high'];
    if(d.flight_status==='active'&&m.health==='unavailable')return ['航班进行中 · 无实时位置','warning'];
    return null;
  }
  function metadata(m){
    const business=m.business||{};
    if(m.kind==='vessel')return `${m.asset?.imo?'IMO '+m.asset.imo:'MMSI '+(m.asset?.mmsi||'—')} · ${business.category_label||'未分类'}`;
    const registration=m.asset?.registration||m.rule?.config?.aircraft_registration;
    return `${registration?registration+' · ':''}${business.aircraft_model||'机型未提供'} · ${business.category_label||'未分类'}`;
  }
  function flightLabel(m){
    if(m.kind!=='aircraft')return m.name;
    const d=data(m),number=d.flight_number;
    if(!number)return m.name;
    const label=d.flight_context==='scheduled'?'待飞航班':d.flight_context==='recent'||m.health!=='ok'?'最近航班':'当前航班';
    return `${m.name} · ${label} ${number}`;
  }
  function route(m,airport){
    const d=m.kind==='flight'?m.flight:data(m);
    if(m.kind==='vessel'){
      const from=d.departure_port,to=d.arrival_port;
      return from||to?`${from||'出发港未提供'} → ${to||'到达港未提供'}`:'航次未提供';
    }
    const from=d?.departure,to=d?.arrival;
    const value=from||to?`${from?airport(from):'出发地未提供'} → ${to?airport(to):'目的地未提供'}`:'航线未提供';
    return value+(m.kind==='aircraft'&&Object.keys(d).length&&(!m.enabled||(!m.current?.fresh&&m.health!=='ok'))?'（历史）':'');
  }
  const api={metadata,flightLabel,route,data,position,status};
  if(typeof module!=='undefined'&&module.exports)module.exports=api;
  else window.TargetPresenter=api;
})();
