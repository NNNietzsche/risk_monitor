'use strict';
(() => {
  const airports = {HND:'东京羽田',NRT:'东京成田',DLC:'大连周水子',PVG:'上海浦东',SHA:'上海虹桥',MEL:'墨尔本'};
  function inRing(x,y,ring) {
    let inside=false;
    for(let i=0,j=ring.length-1;i<ring.length;j=i++){
      const [ax,ay]=ring[j],[bx,by]=ring[i];
      const cross=(x-ax)*(by-ay)-(y-ay)*(bx-ax);
      if(Math.abs(cross)<1e-9 && x>=Math.min(ax,bx) && x<=Math.max(ax,bx) && y>=Math.min(ay,by) && y<=Math.max(ay,by))return true;
      if((ay>y)!==(by>y) && x<(bx-ax)*(y-ay)/(by-ay)+ax)inside=!inside;
    }
    return inside;
  }
  function prepare(poly){const xs=poly[0].map(p=>p[0]),ys=poly[0].map(p=>p[1]);return {poly,bounds:[Math.min(...xs),Math.min(...ys),Math.max(...xs),Math.max(...ys)]};}
  function contains(x,y,shape){const [w,s,e,n]=shape.bounds;return x>=w&&x<=e&&y>=s&&y<=n&&inRing(x,y,shape.poly[0])&&!shape.poly.slice(1).some(ring=>inRing(x,y,ring));}
  function createLookup(data){
    const land=data.land.map(prepare),seas=data.seas.map(s=>({name:s.name,...prepare(s.polygon)}));
    return (longitude,latitude)=>{
      if(!Number.isFinite(longitude)||!Number.isFinite(latitude)||Math.abs(longitude)>180||Math.abs(latitude)>90)return '暂无定位';
      if(land.some(p=>contains(longitude,latitude,p)))return '海域未知';
      return seas.find(p=>contains(longitude,latitude,p))?.name||'海域未知';
    };
  }
  let lookup=null;
  const api={
    createLookup,
    airport:code=>airports[code]||code||'未知机场',
    seaName:data=>data?.longitude==null||data?.latitude==null?'暂无定位':lookup?lookup(data.longitude,data.latitude):'海域暂不可用',
    async load(){try{const response=await fetch('/static/places.json');if(!response.ok)throw new Error('Unavailable');lookup=createLookup(await response.json());}catch{lookup=null;}}
  };
  if(typeof module!=='undefined'&&module.exports)module.exports=api;
  else window.RiskPlaces=api;
})();
