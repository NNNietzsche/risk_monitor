'use strict';
(() => {
  function metadata(m){
    const business=m.business||{};
    if(m.kind==='vessel')return `${m.asset?.imo?'IMO '+m.asset.imo:'MMSI '+(m.asset?.mmsi||'—')} · ${business.category_label||'未分类'}`;
    return `${business.aircraft_model||'机型未提供'} · ${business.category_label||'未分类'}`;
  }
  const api={metadata};
  if(typeof module!=='undefined'&&module.exports)module.exports=api;
  else window.TargetPresenter=api;
})();
