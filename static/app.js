'use strict';
const $ = id => document.getElementById(id);
const el = (tag, text, cls) => { const n = document.createElement(tag); if (text !== undefined) n.textContent = text; if (cls) n.className = cls; return n; };
const fmt = value => value ? new Intl.DateTimeFormat('zh-CN', {timeZone:'Asia/Tokyo', month:'2-digit', day:'2-digit', hour:'2-digit', minute:'2-digit', second:'2-digit', hour12:false}).format(new Date(value)) : '—';
const healthLabel = {ok:'数据有效',unknown:'尚无有效数据',stale:'数据过期',missing:'字段缺失',error:'采集失败',invalid:'数据无效'};
const severityLabel = {high:'高风险',warning:'关注',info:'信息'};
let dashboard = null, offset = 0, loading = false;
async function api(path, method='GET', body) {
  const r = await fetch('/api/v1' + path, {method, headers:body === undefined ? {} : {'Content-Type':'application/json'}, body:body === undefined ? undefined : JSON.stringify(body)});
  const value = await r.json();
  if (!r.ok) throw new Error(typeof value.detail === 'string' ? value.detail : (value.detail || []).map(x => x.msg).join('；') || '请求失败');
  return value;
}
async function action(fn, button) {
  if (button) button.disabled = true;
  $('notice').textContent = ''; $('dialog-error').textContent = '';
  try { await fn(); } catch (e) { ($('dialog').open ? $('dialog-error') : $('notice')).textContent = e.message; }
  finally { if (button) button.disabled = false; }
}
function chip(text, level='') { return el('span', text, 'chip ' + level); }
function empty(parent, text) { parent.append(el('div', text, 'empty')); }
function risk(m) {
  if (!m.enabled) return ['已暂停',''];
  if (m.health !== 'ok') return [healthLabel[m.health] || m.health,'warning'];
  if (m.kind === 'vessel') return m.state.inside ? ['位于风险区域','high'] : ['位于区域外','good'];
  if (['cancelled','diverted'].includes(m.state.flight_status)) return [m.state.flight_status === 'cancelled' ? '已取消' : '已备降','high'];
  return m.state.exceeded ? [`延误 ${m.state.delay_minutes} 分钟`,'high'] : ['延误未超阈值','good'];
}
function metric(label, value, note, danger=false) { const n=el('div',undefined,'metric'); n.append(el('div',label,'metric-label'),el('div',String(value),'metric-value'),el('div',note,'muted')); if(danger)n.children[1].style.color='#c45b3d'; return n; }
function renderMonitors(items) {
  const ships=items.filter(m=>m.kind==='vessel'), flights=items.filter(m=>m.kind==='flight');
  const enabled=items.filter(m=>m.enabled);
  $('summary').replaceChildren(metric('指定船舶',ships.length,'船舶实体 / 含暂停'),metric('航空监控',flights.length,'按日期区分的航班实例'),metric('异常目标',enabled.filter(m=>risk(m)[1]==='high').length,'当前有效数据触发的异常',true),metric('数据待关注',enabled.filter(m=>m.health!=='ok').length,'未采集、缺失、过期或失败',true));
  for(const [id, list] of [['vessels',ships],['flights',flights]]) {
    const box=$(id);box.replaceChildren();if(!list.length)empty(box,'尚未添加目标，可载入演示数据或添加监控对象。');
    list.forEach(m=>{const b=el('button',undefined,'monitor-target'), head=el('div',undefined,'row-head');head.append(el('strong',m.name),chip(...risk(m)));b.append(head);
      if(m.kind==='vessel'){const d=m.latest?.data;b.append(el('p',`IMO ${m.asset?.imo || '—'} · MMSI ${m.asset?.mmsi || '—'}`),el('p',d ? `经纬度 ${d.longitude ?? '—'}°, ${d.latitude ?? '—'}° · ${d.navigation_status==='under_way'?'航行中':d.navigation_status||'航行状态未知'}`:'尚无有效定位'),el('p',m.region?.name));}
      else{b.append(el('p',`${m.flight.carrier}${m.flight.flight_number} · ${m.flight.service_date} · ${m.flight.departure} → ${m.flight.arrival}`),el('p',`计划起飞 ${fmt(m.flight.scheduled_departure)} · 预计 ${fmt(m.latest?.data.estimated_departure)}`),el('p',`${m.rule.config.delay_basis==='departure'?'起飞':'到达'}延误 > ${m.rule.config.threshold_minutes} 分钟触发 · 飞机实体 ${m.flight.aircraft_id ? '已关联' : '未关联'}`));}
      b.append(el('p',`数据时间 ${fmt(m.latest?.observed_at)} · ${healthLabel[m.health]||m.health}`));b.onclick=()=>action(()=>showMonitor(m.id));box.append(b);
    });
  }
  renderMap(ships);
}
function renderMap(ships) {
  const ns='http://www.w3.org/2000/svg',svg=document.createElementNS(ns,'svg');svg.setAttribute('viewBox','0 0 720 300');svg.setAttribute('role','img');svg.setAttribute('aria-label','船舶在全球经纬度网格上的位置，矩形表示监控区域');
  const shape=(tag,attrs,text)=>{const n=document.createElementNS(ns,tag);Object.entries(attrs).forEach(([k,v])=>n.setAttribute(k,v));if(text)n.textContent=text;svg.append(n);return n;};
  const x=lon=>(lon+180)*2, y=lat=>(90-lat)*1.66;
  for(let lon=-180;lon<=180;lon+=60){shape('line',{x1:x(lon),x2:x(lon),y1:0,y2:300,stroke:'#d4e2ed'});shape('text',{x:Math.min(x(lon)+4,680),y:290,fill:'#8ba2b9','font-size':11},lon+'°');}
  for(let lat=-60;lat<=60;lat+=30)shape('line',{x1:0,x2:720,y1:y(lat),y2:y(lat),stroke:'#d4e2ed'});
  const regions=new Map(ships.filter(m=>m.region).map(m=>[m.region.id,m.region]));
  regions.forEach(r=>{const [w,s,e,n]=r.geometry.bbox;shape('rect',{x:x(w),y:y(n),width:(e-w)*2,height:(n-s)*1.66,fill:'#e8a76344',stroke:'#cf925c'});});
  ships.forEach(m=>{const d=m.latest?.data;if(d?.longitude==null||d?.latitude==null)return;const dot=shape('circle',{cx:x(d.longitude),cy:y(d.latitude),r:5,fill:m.health!=='ok'?'#929dad':m.state.inside?'#dd684f':'#387ad4'});const title=document.createElementNS(ns,'title');title.textContent=`${m.name}：${d.longitude}, ${d.latitude}；${fmt(m.latest.observed_at)}`;dot.append(title);});
  $('vessel-map').replaceChildren(svg);
}
function renderTimeline(rows) {
  const box=$('timeline');box.replaceChildren();if(!rows.length)empty(box,'采集状态后将在此记录目标动态。');
  rows.forEach(r=>{const row=el('div',undefined,'timeline-row'),body=el('div');body.append(el('strong',r.name+' · 状态采集'),el('p',r.quality==='evaluated' ? (r.data.kind==='vessel'?`定位 ${r.data.longitude}, ${r.data.latitude}`:'航班时间及状态已更新') : `数据质量：${r.quality}，未据此推断安全状态`));row.append(el('span',fmt(r.observed_at),'time'),el('span',undefined,'timeline-dot'),body);box.append(row);});
}
async function loadEvents() {
  const params=new URLSearchParams({limit:10,offset});if($('event-kind').value)params.set('kind',$('event-kind').value);if($('event-severity').value)params.set('severity',$('event-severity').value);
  const page=await api('/events?'+params),box=$('events');box.replaceChildren();if(!page.items.length)empty(box,'当前筛选下没有风险事件。');
  page.items.forEach(e=>{const b=el('button',undefined,'list-row'),head=el('div',undefined,'row-head');head.append(el('strong',e.summary),chip(severityLabel[e.severity],e.severity));b.append(head,el('p',`${e.monitor_name} · ${fmt(e.occurred_at)} · 规则 v${e.evidence.rule_version} · 模拟数据`));b.onclick=()=>action(async()=>{const d=await api('/events/'+e.id);openDialog('风险事件与判断依据');$('dialog-body').append(el('p',d.summary,'detail-note'));jsonDetails('原始记录、规则版本与判断依据',d,true);});box.append(b);});
  $('event-page').textContent=`第 ${Math.floor(offset/10)+1} 页 · 共 ${page.total} 条`;$('event-prev').disabled=offset===0;$('event-next').disabled=offset+10>=page.total;
}
function renderNews(rows){const box=$('news');box.replaceChildren();if(!rows.length)empty(box,'暂无公开信息。可从现有系统导入，或手动录入带来源的资料。');rows.forEach(n=>{const row=el('article',undefined,'list-row'),head=el('div',undefined,'row-head');head.append(el('strong',n.title),chip(n.is_mock?'演示信息':n.category,n.is_mock?'warning':''));row.append(head,el('p',n.content),el('div',`${fmt(n.published_at)} · ${n.source}`,'time'));if(n.source_url){const a=el('a','查看原始来源','source');a.href=n.source_url;a.target='_blank';a.rel='noopener noreferrer';row.append(a);}box.append(row);});}
function renderAI(s){$('ai-enabled').checked=s.enabled;$('ai-auto').checked=s.auto_refresh;$('ai-enabled').disabled=!s.configured;$('ai-auto').disabled=!s.enabled;$('ai-refresh').disabled=!s.configured||!s.enabled||s.running;
  $('ai-state').textContent=!s.configured?'未配置接口 · 核心监控照常工作':!s.enabled?'AI 已关闭':s.running?'正在生成':s.last_attempt?.status==='failed'?'调用失败，保留上次分析':s.last_attempt?.status==='success'?'最近生成成功':'已启用 · 接口可用性尚待验证';
  $('ai-meta').textContent=s.analysis?`生成于 ${fmt(s.analysis.created_at)} · ${s.analysis.model} · ${s.analysis.prompt_version} · 依据最近最多 40 个目标、20 条规则事件和 10 条公开信息；之后的数据变化尚不一定包含在内。`:'服务端配置 AI_API_KEY、AI_MODEL 后重启，即可启用。AI 不负责采集数据或判定风险。';
  $('ai-content').textContent=s.analysis?.content||'暂无 AI 分析。规则事件、时间线和公开信息无需 AI 即可呈现。';
}
async function refresh(){if(loading)return;loading=true;try{dashboard=await api('/dashboard');renderMonitors(dashboard.monitors);renderTimeline(dashboard.timeline);renderNews(dashboard.news);renderAI(dashboard.ai);await loadEvents();$('updated').textContent=fmt(dashboard.updated_at)+' JST';$('system-status').textContent=dashboard.monitors.some(m=>m.enabled&&m.health!=='ok')?'数据待关注':'监控服务已连接';}catch(e){$('system-status').textContent='服务连接失败';throw e;}finally{loading=false;}}
function openDialog(title){$('dialog-title').textContent=title;$('dialog-body').replaceChildren();$('dialog-error').textContent='';if(!$('dialog').open)$('dialog').showModal();}
function jsonDetails(title,data,opened=false){const d=el('details');d.open=opened;d.append(el('summary',title),el('pre',JSON.stringify(data,null,2)));$('dialog-body').append(d);}
function field(form,label,name,type='text',value='',required=true){const l=el('label',undefined,'field'),input=el(type==='textarea'?'textarea':'input');l.append(el('span',label));input.name=name;if(type!=='textarea')input.type=type;input.value=value;input.required=required;l.append(input);form.append(l);return input;}
function select(form,label,name,options){const l=el('label',undefined,'field'),s=el('select');s.name=name;options.forEach(([value,text])=>{const o=el('option',text);o.value=value;s.append(o);});l.append(el('span',label),s);form.append(l);return s;}
function submit(form,text,handler){const b=el('button',text,'primary');b.type='submit';const a=el('div',undefined,'actions');a.append(b);form.append(a);form.onsubmit=e=>{e.preventDefault();action(()=>handler(new FormData(form)),b);};}
async function showMonitor(id){const m=await api('/monitors/'+id);openDialog(m.name);const box=$('dialog-body');box.append(el('p',`${risk(m)[0]} · ${healthLabel[m.health]||m.health} · 数据时间 ${fmt(m.latest?.observed_at)} · 规则 v${m.rule.version}`,'detail-note'));
  if(m.kind==='flight'){const table=el('table'),head=el('tr');['时间（JST）','计划','预计','实际'].forEach(t=>head.append(el('th',t)));table.append(head);for(const [key,label] of [['departure','起飞'],['arrival','到达']]){const tr=el('tr');[label,fmt(m.flight['scheduled_'+key]),fmt(m.latest?.data['estimated_'+key]),fmt(m.latest?.data['actual_'+key])].forEach(t=>tr.append(el('td',t)));table.append(tr);}box.append(table,el('p',`航班实例 ${m.flight.id}；飞机实体 ${m.flight.aircraft_id||'未关联'}。服务日期 ${m.flight.service_date}。`,'detail-note'));}
  const controls=el('div',undefined,'actions'),pause=el('button',m.enabled?'暂停监控':'恢复监控');pause.onclick=()=>action(async()=>{await api('/monitors/'+id,'PATCH',{enabled:!m.enabled});await refresh();await showMonitor(id);},pause);controls.append(pause);const scenarios=m.kind==='vessel'?[['outside','区域外'],['inside','区域内'],['boundary','区域边界']]:[['on_time','准点'],['delayed','延误超阈值'],['recovered','延误恢复'],['cancelled','取消'],['diverted','备降'],['actual','实际时间优先']];scenarios.push(['missing','字段缺失'],['stale','数据过期'],['failure','采集失败'],['duplicate','重复数据']);const scenario=el('select');scenario.setAttribute('aria-label','模拟状态');scenarios.forEach(([v,t])=>{const o=el('option',t);o.value=v;scenario.append(o);});const poll=el('button','采集所选状态');poll.disabled=!m.enabled;poll.onclick=()=>action(async()=>{const r=await api('/monitors/'+id+'/poll','POST',{scenario:scenario.value});await refresh();await showMonitor(id);$('dialog-error').textContent='采集结果：'+r.outcome;},poll);controls.append(scenario,poll);box.append(controls);
  if(m.kind==='flight'){const f=el('form'),grid=el('div',undefined,'form-grid');field(grid,'延误阈值（分钟）','threshold_minutes','number',m.rule.config.threshold_minutes);const basis=select(grid,'比较时间','delay_basis',[['departure','起飞'],['arrival','到达']]);basis.value=m.rule.config.delay_basis;f.append(grid);submit(f,'保存为新规则版本',async data=>{await api('/monitors/'+id+'/rule-versions','POST',{threshold_minutes:Number(data.get('threshold_minutes')),delay_basis:data.get('delay_basis')});await refresh();await showMonitor(id);});box.append(f);}
  jsonDetails('目标状态、历史采集、原始记录及配置审计',m);
}
async function addMonitor(){const regions=await api('/regions');openDialog('添加监控对象');const f=el('form'),grid=el('div',undefined,'form-grid'),kind=select(grid,'监控类型','kind',[['vessel','船舶实体'],['flight','具体日期的航班']]);field(grid,'显示名称','name');const body=el('div',undefined,'form-grid wide');grid.append(body);const day=new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Tokyo',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());
  const redraw=()=>{body.replaceChildren();if(kind.value==='vessel'){field(body,'IMO（与 MMSI 至少填一个）','imo','text','',false);field(body,'MMSI（9 位数字）','mmsi','text','',false);select(body,'风险区域','region_id',regions.map(r=>[r.id,r.name]));}else{field(body,'运营方代码','carrier','text','RM');field(body,'航班号（不含运营方）','flight_number','text','102');field(body,'服务日期（出发地）','service_date','date',day);field(body,'飞机注册号（可选）','aircraft_registration','text','',false);field(body,'出发机场代码','departure','text','HND');field(body,'到达机场代码','arrival','text','PVG');field(body,'计划起飞（须含时区）','scheduled_departure','text',day+'T10:00:00+09:00');field(body,'计划到达（须含时区）','scheduled_arrival','text',day+'T13:00:00+09:00');field(body,'延误阈值（分钟）','threshold_minutes','number','60');select(body,'比较时间','delay_basis',[['departure','起飞'],['arrival','到达']]);}};kind.onchange=redraw;redraw();f.append(grid);submit(f,'创建监控对象',async data=>{const value=Object.fromEntries([...data].filter(([,v])=>v!==''));if(value.threshold_minutes)value.threshold_minutes=Number(value.threshold_minutes);const m=await api('/monitors','POST',value);await refresh();await showMonitor(m.id);});$('dialog-body').append(f);if(regions.length){const b=el('button','新建风险区域');b.style.marginTop='20px';b.onclick=addRegion;$('dialog-body').append(b);}}
function addRegion(){openDialog('新建风险区域');const f=el('form'),grid=el('div',undefined,'form-grid');field(grid,'区域名称','name');for(const [n,l,v] of [['west','西经度',40],['south','南纬度',10],['east','东经度',50],['north','北纬度',20]]){const input=field(grid,l,n,'number',v);input.step='any';}f.append(grid,el('p','MVP 使用矩形区域，边界计为区域内。暂不支持跨日界线。新建区域为不可变版本。','detail-note'));submit(f,'创建区域并返回',async data=>{const value=Object.fromEntries(data);for(const n of ['west','south','east','north'])value[n]=Number(value[n]);await api('/regions','POST',value);await addMonitor();});$('dialog-body').append(f);}
function addNews(){openDialog('录入公开风险信息');const f=el('form'),grid=el('div',undefined,'form-grid');field(grid,'标题','title');field(grid,'类别','category','text','综合');field(grid,'来源名称','source');field(grid,'原始链接（HTTPS / HTTP）','source_url','url');field(grid,'发布时间（含时区）','published_at','text',new Date().toISOString());field(grid,'内容','content','textarea');f.append(grid);submit(f,'保存公开信息',async data=>{await api('/news','POST',Object.fromEntries(data));$('dialog').close();await refresh();});$('dialog-body').append(f);}
$('close-dialog').onclick=()=>$('dialog').close();$('add').onclick=()=>action(addMonitor);$('add-news').onclick=addNews;
for(const [id,path] of [['seed','/demo/seed'],['poll','/poll']])$(id).onclick=()=>action(async()=>{await api(path,'POST');await refresh();},$(id));
$('refresh').onclick=()=>action(refresh,$('refresh'));
for(const id of ['event-kind','event-severity'])$(id).onchange=()=>{offset=0;action(loadEvents);};
$('event-prev').onclick=()=>{offset=Math.max(0,offset-10);action(loadEvents);};$('event-next').onclick=()=>{offset+=10;action(loadEvents);};
for(const id of ['ai-enabled','ai-auto'])$(id).onchange=()=>action(async()=>{try{renderAI(await api('/ai/settings','PATCH',{enabled:$('ai-enabled').checked,auto_refresh:$('ai-auto').checked}));}catch(e){renderAI(await api('/ai/status'));throw e;}});
$('ai-refresh').onclick=()=>action(async()=>{renderAI(await api('/ai/refresh','POST'));},$('ai-refresh'));
$('header-date').textContent=new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Tokyo',dateStyle:'long'}).format(new Date());
action(async()=>{await refresh();const health=await api('/health');$('schedule').textContent=health.scheduler_seconds?`每 ${health.scheduler_seconds} 秒模拟采集 · 页面每 15 秒刷新`:'自动采集关闭 · 点击推进模拟 · 时间为 JST';});
setInterval(()=>{if(!document.hidden&&!$('dialog').open)action(refresh);},15000);
