'use strict';
(() => {
  function metadata(m){
    const business=m.business||{};
    if(m.kind==='vessel')return `${m.asset?.imo?'IMO '+m.asset.imo:'MMSI '+(m.asset?.mmsi||'—')} · ${business.category_label||'未分类'}`;
    const registration=m.asset?.registration||m.rule?.config?.aircraft_registration;
    return `${registration?registration+' · ':''}${business.aircraft_model||'机型未提供'} · ${business.category_label||'未分类'}`;
  }
  function flightLabel(m){
    if(m.kind!=='aircraft')return m.name;
    const number=m.latest?.data.flight_number;
    if(!number)return m.name;
    return `${m.name} · ${m.health==='ok'?'当前航班':'最近航班'} ${number}`;
  }
  function route(m,airport){
    const data=m.kind==='flight'?m.flight:m.latest?.data;
    const from=data?.departure,to=data?.arrival;
    const value=from||to?`${from?airport(from):'出发地未提供'} → ${to?airport(to):'目的地未提供'}`:'航线未提供';
    return value+(m.kind==='aircraft'&&data&&(m.health!=='ok'||!m.enabled)?'（历史）':'');
  }
  const api={metadata,flightLabel,route};
  if(typeof module!=='undefined'&&module.exports)module.exports=api;
  else window.TargetPresenter=api;
})();
