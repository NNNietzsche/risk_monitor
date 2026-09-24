'use strict';
// Local SVG basemap and observations share an equirectangular projection.
window.RiskMaps = (() => {
  const states = new Map();
  const ns = 'http://www.w3.org/2000/svg';
  const project = (lon, lat) => [(lon + 180) * 2, (90 - lat) * 2];
  function highlight(id, monitorId) {
    const state=states.get(id);
    if(!state)return false;
    state.activeId=monitorId;
    return state.updateHighlight?.() || false;
  }
  const create = (tag, attrs={}, text) => {
    const n = document.createElementNS(ns, tag);
    Object.entries(attrs).forEach(([k,v]) => n.setAttribute(k,v));
    if (text !== undefined) n.textContent = text;
    return n;
  };
  function draw(id, monitors, openTarget) {
    let state = states.get(id);
    if (!state) { state = {view:[0,0,720,360]}; states.set(id,state); }
    const root = document.getElementById(id);
    root.replaceChildren();
    const svg=create('svg',{viewBox:state.view.join(' '),role:'group','aria-label':id==='flight-map'?'航空位置世界地图':'船舶位置世界地图'});
    const ocean=create('rect',{x:0,y:0,width:720,height:360,fill:'#e8f1f7'});
    svg.append(ocean,create('image',{href:'/static/world-land.svg',x:0,y:0,width:720,height:360,'pointer-events':'none'}));
    for(let lon=-120;lon<=120;lon+=60){const [x]=project(lon,0);svg.append(create('line',{x1:x,x2:x,y1:0,y2:360,stroke:'#b7c9d5','stroke-width':.4,'stroke-dasharray':'2 3'}));}
    for(let lat=-60;lat<=60;lat+=30){const [,y]=project(0,lat);svg.append(create('line',{x1:0,x2:720,y1:y,y2:y,stroke:'#b7c9d5','stroke-width':.4,'stroke-dasharray':'2 3'}));}
    const geographicLabels=[[-108,46,'北美洲'],[-60,-17,'南美洲'],[18,52,'欧洲'],[18,5,'非洲'],[88,49,'亚洲'],[136,-26,'大洋洲'],[-140,0,'太平洋'],[170,0,'太平洋'],[-33,8,'大西洋'],[80,-25,'印度洋']];
    geographicLabels.forEach(([lon,lat,name])=>{const [x,y]=project(lon,lat);svg.append(create('text',{x,y,'text-anchor':'middle',fill:'#738b91','font-size':9,'pointer-events':'none'},name));});
    const regions=new Map(monitors.filter(m=>m.region).map(m=>[m.region.id,m.region]));
    regions.forEach(r=>{const [w,s,e,n]=r.geometry.bbox, [x,y]=project(w,n);const rect=create('rect',{x,y,width:(e-w)*2,height:(n-s)*2,fill:'#ef9b5240',stroke:'#c47b3a','stroke-width':1,'vector-effect':'non-scaling-stroke'});rect.append(create('title',{},r.name));svg.append(rect);});
    const points=[];
    monitors.forEach(m=>{
      const d=m.latest?.data;
      if(d?.longitude==null||d?.latitude==null)return;
      const [x,y]=project(d.longitude,d.latitude);
      const historical=(m.health!=='ok'||(d.position_observed_at&&(Date.now()-Date.parse(d.position_observed_at))/1000>m.rule.config.max_age_seconds))||!m.enabled||['cancelled'].includes(d.flight_status);
      const danger=m.state.inside||m.state.exceeded||['cancelled','diverted'].includes(m.state.flight_status);
      const color=historical?'#7f8b99':danger?'#cb6649':'#2d70c4';
      const marker=create('g',{tabindex:0,role:'button','data-monitor-id':m.id,'aria-label':`${m.name}，${d.longitude}，${d.latitude}${historical?'，历史定位':''}`,class:'map-marker'});
      const title=create('title',{},`${m.name}\n${d.longitude}°, ${d.latitude}°\n${d.position_observed_at||m.latest.observed_at}${historical?' · 历史定位':''}`);
      const dot=create('circle',{cx:0,cy:0,r:8,fill:color,stroke:'white','stroke-width':2});
      const icon=create('text',{x:0,y:3.5,'text-anchor':'middle',fill:'white','font-size':10,'pointer-events':'none'},m.kind==='vessel'?'◆':'✈');
      const label=create('text',{x:12,y:4,fill:'#29455e','font-size':10,'paint-order':'stroke',stroke:'#ffffff','stroke-width':3,'stroke-linejoin':'round','pointer-events':'none'},m.name.length>22?m.name.slice(0,22)+'…':m.name);
      if(x>580){label.setAttribute('x',-12);label.setAttribute('text-anchor','end');}
      const halo=create('circle',{cx:0,cy:0,r:15,fill:'#3182ce30',stroke:'#196cc2','stroke-width':2,class:'map-highlight-ring','pointer-events':'none'});
      marker.append(title,halo,dot,icon,label);marker.onclick=()=>openTarget(m.id);marker.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();openTarget(m.id);}};
      svg.append(marker);points.push({id:m.id,x,y,marker});
    });
    const hint=document.createElement('span');hint.className='map-highlight-hint';hint.hidden=true;hint.setAttribute('role','status');
    state.updateHighlight=()=>{
      const active=points.find(p=>p.id===state.activeId);
      points.forEach(p=>{p.marker.classList.toggle('is-highlighted',p===active);p.marker.classList.toggle('is-dimmed',!!active&&p!==active);});
      if(active)svg.append(active.marker);
      const [x,y,w,h]=state.view;
      hint.textContent=state.activeId&&!active?'该目标暂无有效定位':active&&(active.x<x||active.x>x+w||active.y<y||active.y>y+h)?'目标在当前视野外，请点击“显示全部目标”':'';
      hint.hidden=!hint.textContent;
      return !!active;
    };
    function apply(){let [x,y,w,h]=state.view;w=Math.max(45,Math.min(720,w));h=w/2;x=Math.max(0,Math.min(720-w,x));y=Math.max(0,Math.min(360-h,y));state.view=[x,y,w,h];svg.setAttribute('viewBox',state.view.join(' '));points.forEach(p=>p.marker.setAttribute('transform',`translate(${p.x} ${p.y}) scale(${w/720})`));state.updateHighlight();}
    function zoom(factor){const [x,y,w,h]=state.view,nw=Math.max(45,Math.min(720,w*factor));state.view=[x+(w-nw)/2,y+(h-nw/2)/2,nw,nw/2];apply();}
    const controls=document.createElement('div');controls.className='map-controls';
    function button(text,fn,title){const b=document.createElement('button');b.textContent=text;b.type='button';b.setAttribute('aria-label',title||text);b.onclick=fn;controls.append(b);}
    button('+',()=>zoom(.5),'放大地图');button('−',()=>zoom(2),'缩小地图');
    button('显示全部目标',()=>{if(!points.length)return;const xs=points.map(p=>p.x),ys=points.map(p=>p.y),xmin=Math.min(...xs),xmax=Math.max(...xs),ymin=Math.min(...ys),ymax=Math.max(...ys);const w=Math.min(720,Math.max(80,(xmax-xmin)*1.5,(ymax-ymin)*3));state.view=[(xmin+xmax-w)/2,(ymin+ymax-w/2)/2,w,w/2];apply();});
    button('全球',()=>{state.view=[0,0,720,360];apply();});
    let drag=null;
    svg.onpointerdown=e=>{if(e.target.closest('.map-marker')||e.button!==0)return;drag={x:e.clientX,y:e.clientY,view:[...state.view]};svg.setPointerCapture(e.pointerId);};
    svg.onpointermove=e=>{if(!drag)return;const rect=svg.getBoundingClientRect(),scale=Math.min(rect.width/drag.view[2],rect.height/drag.view[3]);state.view=[drag.view[0]-(e.clientX-drag.x)/scale,drag.view[1]-(e.clientY-drag.y)/scale,drag.view[2],drag.view[3]];apply();};
    svg.onpointerup=svg.onpointercancel=()=>{drag=null;};
    root.append(svg,controls,hint);
    if(!points.length){const note=document.createElement('span');note.className='map-empty';note.textContent='暂无有效定位 · 采集数据后显示';root.append(note);}
    apply();
  }
  return {draw,highlight};
})();
