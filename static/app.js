'use strict';
const $ = id => document.getElementById(id);
const el = (tag, text, cls) => { const n = document.createElement(tag); if (text !== undefined) n.textContent = text; if (cls) n.className = cls; return n; };
const fmt = value => value ? new Intl.DateTimeFormat('zh-CN', {timeZone:'Asia/Tokyo', month:'2-digit', day:'2-digit', hour:'2-digit', minute:'2-digit', second:'2-digit', hour12:false}).format(new Date(value)) : '—';
const healthLabel = {ok:'数据有效',unknown:'尚无有效数据',stale:'数据过期',missing:'字段缺失',error:'采集失败',invalid:'数据无效'};
const severityLabel = {high:'高风险',warning:'关注',info:'信息'};
let dashboard = null, loading = false;
const isMock = m => m.source?.is_mock === true;
const dataLabel = m => m.source?.is_mock === true ? '模拟' : m.source?.is_mock === false ? '真实' : '来源未知';
const sourceLabel = m => m.source?.name || m.provider || '来源未知';
let timelineOffset = 0, timelineSnapshot = null, timelineRequest = 0;
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
  if (m.kind === 'aircraft') return ['仅位置 · 航班未评估',''];
  if (['cancelled','diverted'].includes(m.state.flight_status)) return [m.state.flight_status === 'cancelled' ? '已取消' : '已备降','high'];
  return m.state.exceeded ? [`延误 ${m.state.delay_minutes} 分钟`,'high'] : ['延误未超阈值','good'];
}
function metric(label, value, note, danger=false) { const n=el('div',undefined,'metric'); n.append(el('div',label,'metric-label'),el('div',String(value),'metric-value'),el('div',note,'muted')); if(danger)n.children[1].style.color='#c45b3d'; return n; }
function renderMonitors(items) {
  const ships=items.filter(m=>m.kind==='vessel'), flights=items.filter(m=>m.kind!=='vessel');
  const enabled=items.filter(m=>m.enabled);
  $('summary').replaceChildren(metric('指定船舶',ships.length,'船舶实体 / 含暂停'),metric('航空监控',flights.length,'飞机实体 / 航班实例分别跟踪'),metric('异常目标',enabled.filter(m=>risk(m)[1]==='high').length,'当前有效数据触发的异常',true),metric('数据待关注',enabled.filter(m=>m.health!=='ok').length,'未采集、缺失、过期或失败',true));
  for(const [id,list,unit] of [['vessel-count',ships,'艘'],['flight-count',flights,'个目标']]){
    $(id).textContent=`${list.length} ${unit}`;
    $(id).title=`已添加 ${list.length} ${unit}，其中 ${list.filter(m=>m.enabled).length} 个监控中（数量含暂停目标）`;
  }
  for(const [id,list] of [['vessels',ships],['flights',flights]]){
    const box=$(id);box.replaceChildren();if(!list.length)empty(box,'尚未添加目标，可接入公开数据或添加监控对象。');
    list.forEach(m=>{
      const [status,level]=risk(m),isShip=m.kind==='vessel';
      const button=el('button',undefined,'monitor-target target-item compact-target');
      const identity=el('div',undefined,'target-info');
      const dot=el('span',undefined,'target-status '+({high:'danger',warning:'warning',good:'normal'}[level]||'neutral'));dot.setAttribute('aria-hidden','true');
      const text=el('div',undefined,'target-text');const name=el('div',m.name,'target-name');name.title=m.name;
      const meta=m.kind==='aircraft'?`${m.asset.registration} · ${m.latest?.data.callsign||'呼号未提供'}`:isShip?(m.asset?.imo?'IMO '+m.asset.imo:'MMSI '+(m.asset?.mmsi||'—')):`${m.flight.carrier}${m.flight.flight_number} · ${m.flight.service_date}`;
      const metadata=el('div',meta+(' · '+dataLabel(m)),'target-meta');metadata.title=meta;text.append(name,metadata);identity.append(dot,text);
      const place=el('div',undefined,'target-location');
      const label=m.kind==='aircraft'?'仅位置 · 航线未提供':isShip?RiskPlaces.seaName(m.latest?.data):`${RiskPlaces.airport(m.flight.departure)} → ${RiskPlaces.airport(m.flight.arrival)}`;
      const historical=isShip&&m.latest&&(!m.enabled||m.health!=='ok');
      const location=el('div',label+(historical?'（历史）':''),'compact-location');
      location.title=m.kind==='aircraft'?'飞机实体定位；不能仅凭呼号确认具体航班实例。':isShip?'大致海域，仅供位置理解；不参与风险规则。':`${m.flight.departure} → ${m.flight.arrival}`;
      place.append(location,chip(status,level));
      button.append(identity,place,el('span','›','target-chevron'));
      button.setAttribute('aria-label',`${m.name}，${meta}，${label}，${status}，查看详情`);
      button.dataset.monitorId=m.id;
      const mapId=isShip?'vessel-map':'flight-map';
      const highlight=()=>RiskMaps.highlight(mapId,m.id);
      const clearHighlight=()=>{if(!button.matches(':hover')&&document.activeElement!==button)RiskMaps.highlight(mapId,null);};
      button.onmouseenter=button.onfocus=highlight;button.onmouseleave=button.onblur=clearHighlight;
      button.onclick=()=>action(()=>showMonitor(m.id));box.append(button);
    });
  }
  RiskMaps.draw('vessel-map',ships,id=>action(()=>showMonitor(id)));
  RiskMaps.draw('flight-map',flights,id=>action(()=>showMonitor(id)));
  for(const [listId,mapId] of [['vessels','vessel-map'],['flights','flight-map']]){RiskMaps.highlight(mapId,null);for(const row of $(listId).querySelectorAll('[data-monitor-id]')){if(row.matches(':hover')||row===document.activeElement)RiskMaps.highlight(mapId,row.dataset.monitorId);}}
}
const eventTitles = {
  'vessel.first_seen_inside':'首次定位位于风险区域', 'vessel.entered_region':'进入风险区域', 'vessel.exited_region':'离开风险区域',
  'flight.delay_exceeded':'延误超过阈值', 'flight.delay_recovered':'延误恢复', 'flight.cancelled':'航班取消',
  'flight.diverted':'航班备降', 'flight.status_restored':'航班状态恢复'
};
function renderTimeline(rows) {
  const box=$('timeline');box.replaceChildren();
  if(!rows.length){empty(box,'当前筛选下没有目标动态。');return;}
  rows.forEach(r=>{
    const assessment=r.assessment||{tone:'unknown',label:'未评估',description:'尚无对应的判断记录。'};
    const events=r.events||[],isShip=r.data.kind==='vessel';
    const item=el('article',undefined,'timeline-item');
    const time=el('time',undefined,'timeline-time');time.dateTime=r.observed_at;time.title=fmt(r.observed_at)+' JST';
    time.append(el('span',new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Tokyo',month:'2-digit',day:'2-digit'}).format(new Date(r.observed_at)),'timeline-date'),el('span',new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Tokyo',hour:'2-digit',minute:'2-digit',second:'2-digit',hour12:false}).format(new Date(r.observed_at))));
    const line=el('div',undefined,'timeline-line');line.setAttribute('aria-hidden','true');line.append(el('span',undefined,'timeline-dot '+assessment.tone));
    const content=el('div',undefined,'timeline-content');
    const title=events.length ? (eventTitles[events[0].type]||'触发风险事件')+(events.length>1?`等 ${events.length} 项动态`:'') : r.quality!=='evaluated'?'数据待关注':r.data.kind!=='flight'?'更新位置':'更新航班状态';
    content.append(el('h3',r.name+' '+title,'timeline-title'),el('p',assessment.description,'timeline-description'));
    const tags=el('div',undefined,'timeline-tags');
    tags.append(el('span',isShip?'船舶':r.data.kind==='aircraft'?'飞机实体':'航班','tag '+(isShip?'tag-ship':'tag-flight')),el('span',assessment.label,'tag '+({normal:'tag-normal',warning:'tag-warning',danger:'tag-danger',unknown:'tag-muted'}[assessment.tone]||'tag-muted')));
    if(events.length)tags.append(el('span','规则事件','tag tag-muted'));
    tags.append(el('span',dataLabel(r)+' · '+sourceLabel(r),'tag tag-muted'));
    const target=el('button','目标详情','timeline-link');target.onclick=()=>action(()=>showMonitor(r.monitor_id));tags.append(target);
    events.forEach((event,index)=>{const b=el('button',events.length===1?'查看判断依据':`依据 ${index+1} · ${eventTitles[event.type]||'风险事件'}`,'timeline-link');b.onclick=()=>action(()=>showEvent(event.id));tags.append(b);});
    content.append(tags);item.append(time,line,content);box.append(item);
  });
}
async function showEvent(id){
  const d=await api('/events/'+id);openDialog('风险事件与判断依据');
  const box=$('dialog-body');box.append(el('p',d.summary,'detail-note'));
  const facts=el('table');
  for(const [label,value] of [['目标',d.monitor_name],['发生时间',fmt(d.occurred_at)+' JST'],['级别',severityLabel[d.severity]],['规则版本','v'+d.rule.version],['数据来源',d.raw_record.provider]]){const row=el('tr');row.append(el('th',label),el('td',value));facts.append(row);}
  box.append(facts);jsonDetails('原始记录、历史规则与完整证据',d);
}
async function loadTimeline(resetSnapshot=false) {
  const request = ++timelineRequest;
  const params = new URLSearchParams({limit:10,offset:timelineOffset,entry_type:$('timeline-type').value});
  if($('timeline-kind').value)params.set('kind',$('timeline-kind').value);
  if($('timeline-severity').value)params.set('severity',$('timeline-severity').value);
  if (timelineSnapshot !== null && !resetSnapshot) params.set('snapshot',timelineSnapshot);
  const page = await api('/timeline?'+params);
  if (request !== timelineRequest) return;
  timelineSnapshot = page.snapshot;
  renderTimeline(page.items);
  $('timeline-page').textContent = `第 ${Math.floor(page.offset/10)+1} / ${Math.max(1,Math.ceil(page.total/10))} 页 · 共 ${page.total} 条${page.offset?' · 历史快照':''}`;
  $('timeline-prev').disabled = page.offset === 0;
  $('timeline-next').disabled = page.offset + page.limit >= page.total;
}
function renderNews(rows){const box=$('news');box.replaceChildren();if(!rows.length)empty(box,'暂无公开信息。可从现有系统导入，或手动录入带来源的资料。');rows.forEach(n=>{const row=el('article',undefined,'list-row'),head=el('div',undefined,'row-head');head.append(el('strong',n.title),chip(n.is_mock?'演示信息':n.category,n.is_mock?'warning':''));row.append(head,el('p',n.content),el('div',`${fmt(n.published_at)} · ${n.source}`,'time'));if(n.source_url){const a=el('a','查看原始来源','source');a.href=n.source_url;a.target='_blank';a.rel='noopener noreferrer';row.append(a);}box.append(row);});}
function renderAI(s){$('ai-enabled').checked=s.enabled;$('ai-auto').checked=s.auto_refresh;$('ai-enabled').disabled=!s.configured;$('ai-auto').disabled=!s.enabled;$('ai-refresh').disabled=!s.configured||!s.enabled||s.running;
  $('ai-state').textContent=!s.configured?'未配置接口 · 核心监控照常工作':!s.enabled?'AI 已关闭':s.running?'正在生成':s.last_attempt?.status==='failed'?'调用失败，保留上次分析':s.last_attempt?.status==='success'?'最近生成成功':'已启用 · 接口可用性尚待验证';
  $('ai-meta').textContent=s.analysis?`生成于 ${fmt(s.analysis.created_at)} · ${s.analysis.model} · ${s.analysis.prompt_version} · 依据最近最多 40 个目标、20 条规则事件和 10 条公开信息；之后的数据变化尚不一定包含在内。`:'服务端配置 AI_API_KEY、AI_MODEL 后重启，即可启用。AI 不负责采集数据或判定风险。';
  $('ai-content').textContent=s.analysis?.content||'暂无 AI 分析。规则事件、时间线和公开信息无需 AI 即可呈现。';
}
async function refresh(){if(loading)return;loading=true;try{const [data,catalog]=await Promise.all([api('/dashboard'),api('/public/sources')]);dashboard=data;renderSources(catalog);renderMonitors(dashboard.monitors);const sources=new Set(dashboard.monitors.filter(m=>m.enabled).map(m=>isMock(m)?'mock':'live'));$('data-mode').textContent=sources.size>1?'真实 + 模拟（各目标标注）':sources.has('live')?'LIVE · 公开真实数据':'MOCK · 模拟数据';await loadTimeline(timelineOffset===0);renderNews(dashboard.news);renderAI(dashboard.ai);$('updated').textContent=fmt(dashboard.updated_at)+' JST';$('system-status').textContent=dashboard.monitors.some(m=>m.enabled&&m.health!=='ok')?'数据待关注':'监控服务已连接';}catch(e){$('system-status').textContent='服务连接失败';throw e;}finally{loading=false;}}
function openDialog(title){$('dialog-title').textContent=title;$('dialog-body').replaceChildren();$('dialog-error').textContent='';if(!$('dialog').open)$('dialog').showModal();$('dialog').scrollTop=0;}
function jsonDetails(title,data,opened=false){const d=el('details');d.open=opened;d.append(el('summary',title),el('pre',JSON.stringify(data,null,2)));$('dialog-body').append(d);}
function field(form,label,name,type='text',value='',required=true){const l=el('label',undefined,'field'),input=el(type==='textarea'?'textarea':'input');l.append(el('span',label));input.name=name;if(type!=='textarea')input.type=type;input.value=value;input.required=required;l.append(input);form.append(l);return input;}
function select(form,label,name,options){const l=el('label',undefined,'field'),s=el('select');s.name=name;options.forEach(([value,text])=>{const o=el('option',text);o.value=value;s.append(o);});l.append(el('span',label),s);form.append(l);return s;}
function submit(form,text,handler){const b=el('button',text,'primary');b.type='submit';const a=el('div',undefined,'actions');a.append(b);form.append(a);form.onsubmit=e=>{e.preventDefault();action(()=>handler(new FormData(form)),b);};}
async function showMonitor(id){const m=await api('/monitors/'+id);openDialog(m.name);const box=$('dialog-body');box.append(el('p',`${risk(m)[0]} · ${healthLabel[m.health]||m.health} · 数据时间 ${fmt(m.latest?.observed_at)} · 规则 v${m.rule.version}`,'detail-note'));
  const position=m.latest?.data;box.append(el('p',position?.longitude!=null&&position?.latitude!=null?`位置（${isMock(m)?'模拟':'真实公开源'}）：经度 ${position.longitude}°，纬度 ${position.latitude}°${m.health!=='ok'?'（历史定位）':''}`:'暂无定位数据','detail-note'));
  box.append(el('p',`数据源：${sourceLabel(m)}。${isMock(m)?'模拟场景用于验证规则。':`每个目标至少间隔 ${m.rule.config.min_poll_seconds||m.source?.min_poll_seconds||60} 秒采集；失败时保留历史数据。`}`,'detail-note'));
  if(m.last_error)box.append(el('p',m.last_error,'detail-note'));
  if(m.kind==='aircraft')box.append(el('p',`飞机注册号 ${m.asset.registration} · ICAO24 ${m.rule.config.icao24} · 呼号 ${position?.callsign||'未提供'} · 机型 ${position?.aircraft_type||'未提供'}。此监控仅评估位置，未评估航班延误、取消或备降。`,'detail-note'));
  if(m.kind==='vessel'){box.append(el('p',`身份标识：IMO ${m.asset?.imo||'—'} · MMSI ${m.asset?.mmsi||'—'}；大致海域：${RiskPlaces.seaName(position)}；监控区域：${m.region?.name||'未配置'}`,'detail-note'));}
  if(m.kind==='flight'){box.append(el('p',`航线：${RiskPlaces.airport(m.flight.departure)}（${m.flight.departure}） → ${RiskPlaces.airport(m.flight.arrival)}（${m.flight.arrival}）`,'detail-note'));const table=el('table'),head=el('tr');['时间（JST）','计划','预计','实际'].forEach(t=>head.append(el('th',t)));table.append(head);for(const [key,label] of [['departure','起飞'],['arrival','到达']]){const tr=el('tr');[label,fmt(m.flight['scheduled_'+key]),fmt(m.latest?.data['estimated_'+key]),fmt(m.latest?.data['actual_'+key])].forEach(t=>tr.append(el('td',t)));table.append(tr);}box.append(table,el('p',`航班实例 ${m.flight.id}；飞机实体 ${m.flight.aircraft_id||'未关联'}。服务日期 ${m.flight.service_date}。`,'detail-note'));}
  const controls=el('div',undefined,'actions'),pause=el('button',m.enabled?'暂停监控':'恢复监控');pause.onclick=()=>action(async()=>{await api('/monitors/'+id,'PATCH',{enabled:!m.enabled});await refresh();await showMonitor(id);},pause);controls.append(pause);const scenarios=m.kind==='vessel'?[['outside','区域外'],['inside','区域内'],['boundary','区域边界']]:[['on_time','准点'],['delayed','延误超阈值'],['recovered','延误恢复'],['cancelled','取消'],['diverted','备降'],['actual','实际时间优先']];scenarios.push(['missing','字段缺失'],['stale','数据过期'],['failure','采集失败'],['duplicate','重复数据']);const scenario=el('select');scenario.setAttribute('aria-label','模拟状态');scenarios.forEach(([v,t])=>{const o=el('option',t);o.value=v;scenario.append(o);});const poll=el('button',isMock(m)?'采集所选状态':'采集真实状态');poll.disabled=!m.enabled;poll.onclick=()=>action(async()=>{const r=await api('/monitors/'+id+'/poll','POST',{scenario:isMock(m)?scenario.value:'sequence'});await refresh();await showMonitor(id);$('dialog-error').textContent='采集结果：'+r.outcome;},poll);if(isMock(m))controls.append(scenario);controls.append(poll);box.append(controls);
  if(m.kind==='flight'){const f=el('form'),grid=el('div',undefined,'form-grid');field(grid,'延误阈值（分钟）','threshold_minutes','number',m.rule.config.threshold_minutes);const basis=select(grid,'比较时间','delay_basis',[['departure','起飞'],['arrival','到达']]);basis.value=m.rule.config.delay_basis;f.append(grid);submit(f,'保存为新规则版本',async data=>{await api('/monitors/'+id+'/rule-versions','POST',{threshold_minutes:Number(data.get('threshold_minutes')),delay_basis:data.get('delay_basis')});await refresh();await showMonitor(id);});box.append(f);}
  jsonDetails('目标状态、历史采集、原始记录及配置审计',m);
}
async function addMonitor(){
  const [regions,sources]=await Promise.all([api('/regions'),api('/public/sources')]);
  openDialog('添加监控对象');
  const f=el('form'),grid=el('div',undefined,'form-grid');
  const kind=select(grid,'监控类型','kind',[['vessel','船舶实体'],['aircraft','飞机实体'],['flight','具体日期的航班']]);
  field(grid,'显示名称','name');
  const provider=select(grid,'数据源','provider',[]);provider.required=true;
  const note=el('p',undefined,'detail-note wide');grid.append(note);
  const body=el('div',undefined,'form-grid wide');grid.append(body);
  const day=new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Tokyo',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());
  const updateSource=()=>{
    const spec=sources[provider.value];
    note.textContent=spec?spec.coverage:'尚无支持该类型的数据源';
    for(const name of ['imo','mmsi','icao24']){const input=body.querySelector(`[name="${name}"]`);if(input)input.required=(spec?.required_fields?.[kind.value]||[]).includes(name);}
  };
  const redraw=()=>{
    body.replaceChildren();provider.replaceChildren();
    Object.entries(sources).filter(([,s])=>s.kinds.includes(kind.value)).sort((a,b)=>Number(a[1].is_mock)-Number(b[1].is_mock)).forEach(([id,s])=>{const o=el('option',s.name+' · '+(s.is_mock?'模拟':'真实'));o.value=id;provider.append(o);});
    if(kind.value==='vessel'){
      field(body,'IMO（与 MMSI 至少填一个）','imo','text','',false);
      field(body,'MMSI（部分数据源必填）','mmsi','text','',false);
      select(body,'风险区域','region_id',regions.map(r=>[r.id,r.name]));
    }else if(kind.value==='aircraft'){
      field(body,'飞机注册号','aircraft_registration');
      field(body,'ICAO24（部分数据源必填，6 位小写十六进制）','icao24','text','',false);
    }else{
      field(body,'运营方代码','carrier','text','RM');field(body,'航班号（不含运营方）','flight_number','text','102');
      field(body,'服务日期（出发地）','service_date','date',day);field(body,'飞机注册号（可选）','aircraft_registration','text','',false);
      field(body,'出发机场代码','departure','text','HND');field(body,'到达机场代码','arrival','text','PVG');
      field(body,'计划起飞（须含时区）','scheduled_departure','text',day+'T10:00:00+09:00');field(body,'计划到达（须含时区）','scheduled_arrival','text',day+'T13:00:00+09:00');
      field(body,'延误阈值（分钟）','threshold_minutes','number','60');select(body,'比较时间','delay_basis',[['departure','起飞'],['arrival','到达']]);
    }
    updateSource();
  };
  kind.onchange=redraw;provider.onchange=updateSource;redraw();f.append(grid);
  submit(f,'创建监控对象',async data=>{const value=Object.fromEntries([...data].filter(([,v])=>v!==''));if(value.threshold_minutes)value.threshold_minutes=Number(value.threshold_minutes);const m=await api('/monitors','POST',value);await refresh();await showMonitor(m.id);});
  $('dialog-body').append(f);
  const b=el('button','新建风险区域');b.style.marginTop='20px';b.onclick=addRegion;$('dialog-body').append(b);
}
function renderSources(catalog){
  const box=$('source-attribution');box.replaceChildren();
  Object.values(catalog).filter(s=>!s.is_mock).forEach(s=>{
    const line=el('span');
    if(s.url&&/^https?:\/\//.test(s.url)){const a=el('a',s.name);a.href=s.url;a.target='_blank';a.rel='noopener noreferrer';line.append(a);}else line.append(el('span',s.name));
    line.append(el('span',`（${s.license||'许可见来源说明'}）：${s.coverage}。 `));box.append(line);
  });
  box.append(el('span','测试围栏不代表真实风险评级。'));
}

function addRegion(){openDialog('新建风险区域');const f=el('form'),grid=el('div',undefined,'form-grid');field(grid,'区域名称','name');for(const [n,l,v] of [['west','西经度',40],['south','南纬度',10],['east','东经度',50],['north','北纬度',20]]){const input=field(grid,l,n,'number',v);input.step='any';}f.append(grid,el('p','MVP 使用矩形区域，边界计为区域内。暂不支持跨日界线。新建区域为不可变版本。','detail-note'));submit(f,'创建区域并返回',async data=>{const value=Object.fromEntries(data);for(const n of ['west','south','east','north'])value[n]=Number(value[n]);await api('/regions','POST',value);await addMonitor();});$('dialog-body').append(f);}
function addNews(){openDialog('录入公开风险信息');const f=el('form'),grid=el('div',undefined,'form-grid');field(grid,'标题','title');field(grid,'类别','category','text','综合');field(grid,'来源名称','source');field(grid,'原始链接（HTTPS / HTTP）','source_url','url');field(grid,'发布时间（含时区）','published_at','text',new Date().toISOString());field(grid,'内容','content','textarea');f.append(grid);submit(f,'保存公开信息',async data=>{await api('/news','POST',Object.fromEntries(data));$('dialog').close();await refresh();});$('dialog-body').append(f);}
$('public-targets').onclick=()=>action(publicTargets,$('public-targets'));
$('close-dialog').onclick=()=>$('dialog').close();$('add').onclick=()=>action(addMonitor);$('add-news').onclick=addNews;
for(const [id,path] of [['seed','/demo/seed'],['poll','/poll']])$(id).onclick=()=>action(async()=>{await api(path,'POST');await refresh();},$(id));
$('refresh').onclick=()=>action(refresh,$('refresh'));
for(const id of ['timeline-kind','timeline-type','timeline-severity'])$(id).onchange=()=>{if(id==='timeline-type'&&$('timeline-type').value==='quality')$('timeline-severity').value='';if(id==='timeline-severity'&&$('timeline-severity').value)$('timeline-type').value='events';timelineOffset=0;timelineSnapshot=null;action(loadTimeline);};
$('timeline-prev').onclick=()=>{timelineOffset=Math.max(0,timelineOffset-10);action(loadTimeline);};
$('timeline-next').onclick=()=>{timelineOffset+=10;action(loadTimeline);};
$('timeline-latest').onclick=()=>{timelineOffset=0;timelineSnapshot=null;action(loadTimeline);};

for(const id of ['ai-enabled','ai-auto'])$(id).onchange=()=>action(async()=>{try{renderAI(await api('/ai/settings','PATCH',{enabled:$('ai-enabled').checked,auto_refresh:$('ai-auto').checked}));}catch(e){renderAI(await api('/ai/status'));throw e;}});
$('ai-refresh').onclick=()=>action(async()=>{renderAI(await api('/ai/refresh','POST'));},$('ai-refresh'));
$('header-date').textContent=new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Tokyo',dateStyle:'long'}).format(new Date());
action(async()=>{await RiskPlaces.load();await refresh();const health=await api('/health');$('schedule').textContent=health.scheduler_seconds?`每 ${health.scheduler_seconds} 秒检查 · 公开源按各自间隔采集 · 页面每 15 秒刷新`:'自动采集关闭 · 点击采集一次状态 · 时间为 JST';});
setInterval(()=>{if(!document.hidden&&!$('dialog').open)action(refresh);},15000);
