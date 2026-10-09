'use strict';
const $ = id => document.getElementById(id);
const el = (tag, text, cls) => { const n = document.createElement(tag); if (text !== undefined) n.textContent = text; if (cls) n.className = cls; return n; };
const fmt = value => value ? new Intl.DateTimeFormat('zh-CN', {timeZone:'Asia/Tokyo', month:'2-digit', day:'2-digit', hour:'2-digit', minute:'2-digit', second:'2-digit', hour12:false}).format(new Date(value)) : '—';
const healthLabel = {ok:'数据有效',unknown:'尚无有效数据',stale:'数据过期',unavailable:'暂无实时位置',missing:'字段缺失',error:'采集失败',rate_limited:'数据源限流 · 等待重试',invalid:'数据无效',pending:'区域配置已更新 · 待核查'};
const severityLabel = {high:'高风险',warning:'关注',info:'信息'};
let dashboard = null, loading = false;
let schedulerSeconds = null;
const sourceLabel = m => m.source?.name || m.provider || '来源未知';
const timelines = new Map();
async function api(path, method='GET', body) {
  const r = await fetch('/api/v1' + path, {method, headers:body === undefined ? {} : {'Content-Type':'application/json'}, body:body === undefined ? undefined : JSON.stringify(body)});
  const value = await r.json();
  if (!r.ok) throw new Error(typeof value.detail === 'string' ? value.detail : (value.detail || []).map(x => x.msg.replace(/^Value error, /,'')).join('；') || '请求失败');
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
function needsAttention(m){if(m.kind==='vessel'&&!m.regions?.length)return true;return m.health!=='ok'&&!(m.current?.fresh&&m.kind==='aircraft'&&['landed','scheduled'].includes(TargetPresenter.data(m).flight_status));}
function risk(m) {
  if (!m.enabled) return ['已暂停',''];
  const operational=TargetPresenter.status(m);if(operational)return operational;
  if (m.health !== 'ok') return [healthLabel[m.health] || m.health,'warning'];
  if (m.kind === 'vessel') return !m.regions?.length ? ['尚未设置风险区域','warning'] : m.state.inside ? ['位于 '+(m.state.inside_regions||[]).join('、'),'high'] : ['全部风险区域外','good'];
  if (m.kind === 'aircraft' && !m.state.flight_risk_assessed) return [m.latest?.data.navigation_status==='on_ground'?'地面 · 航班未评估':'位置已更新 · 航班未评估',''];
  if (m.state.flight_status==='landed') return ['已落地',m.state.exceeded?'warning':'good'];
  if (['cancelled','diverted'].includes(m.state.flight_status)) return [m.state.flight_status === 'cancelled' ? '已取消' : '已备降','high'];
  return m.state.exceeded ? [`延误 ${TargetPresenter.minutes(m.state.delay_minutes)} 分钟`,'high'] : ['延误未超阈值','good'];
}
function metric(label,value,tone){const n=el('div',undefined,'risk-pill '+tone);n.append(el('span',label,'risk-label'),el('strong',String(value),'risk-value'));return n;}
function renderMonitors(items) {
  const ships=items.filter(m=>m.kind==='vessel'), flights=items.filter(m=>m.kind!=='vessel');
  const enabled=items.filter(m=>m.enabled);
  $('summary').replaceChildren(metric('高风险',enabled.filter(m=>risk(m)[1]==='high').length,'high'),metric('待关注',enabled.filter(m=>risk(m)[1]!=='high'&&(needsAttention(m)||risk(m)[1]==='warning')).length,'warning'));
  for(const [id,list,unit] of [['vessel-count',ships,'艘'],['flight-count',flights,'架']]){
    $(id).replaceChildren(el('strong',String(list.length)),el('span',unit));
    $(id).title=`已添加 ${list.length} ${unit}，其中 ${list.filter(m=>m.enabled).length} 个监控中（数量含暂停目标）`;
  }
  for(const [id,list] of [['vessels',ships],['flights',flights]]){
    const box=$(id);box.replaceChildren();if(!list.length)empty(box,'尚未添加目标。');
    list.forEach(m=>{
      const [status,level]=risk(m),isShip=m.kind==='vessel';
      const button=el('button',undefined,'monitor-target target-item compact-target');
      const identity=el('div',undefined,'target-info');
      const dot=el('span',undefined,'target-status '+({high:'danger',warning:'warning',good:'normal'}[level]||'neutral'));dot.setAttribute('aria-hidden','true');
      const text=el('div',undefined,'target-text');const name=el('div',TargetPresenter.flightLabel(m),'target-name');name.title=name.textContent;
      const meta=TargetPresenter.metadata(m);
      const metadata=el('div',meta,'target-meta');metadata.title=meta;text.append(name,metadata);if(m.remark){const remark=el('div','备注：'+m.remark,'target-remark');remark.title=m.remark;text.append(remark);}identity.append(dot,text);
      const place=el('div',undefined,'target-location');
      const label=TargetPresenter.route(m,RiskPlaces.airport);
      const location=el('div',label,'compact-location');
      location.title=isShip?'最近离港 → 本次目的港；来自航次信息。':'按注册号跟踪当前、待飞或最近航班。';
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
  RiskMaps.draw('vessel-map',ships,id=>action(()=>showMonitor(id)),dashboard.regions);
  RiskMaps.draw('flight-map',flights,id=>action(()=>showMonitor(id)));
  for(const [listId,mapId] of [['vessels','vessel-map'],['flights','flight-map']]){RiskMaps.highlight(mapId,null);for(const row of $(listId).querySelectorAll('[data-monitor-id]')){if(row.matches(':hover')||row===document.activeElement)RiskMaps.highlight(mapId,row.dataset.monitorId);}}
}
const eventTitles = {
  'vessel.first_seen_inside':'首次定位位于风险区域', 'vessel.entered_region':'进入风险区域', 'vessel.exited_region':'离开风险区域',
  'flight.delay_exceeded':'延误超过阈值', 'flight.delay_recovered':'延误恢复', 'flight.cancelled':'航班取消',
  'flight.diverted':'航班备降', 'flight.status_restored':'航班状态恢复'
};
function renderTimeline(id,rows) {
  const box=$(id);box.replaceChildren();
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

    const target=el('button','目标详情','timeline-link');target.onclick=()=>action(()=>showMonitor(r.monitor_id));tags.append(target);
    events.forEach((event,index)=>{const b=el('button',events.length===1?'查看判断依据':`依据 ${index+1} · ${eventTitles[event.type]||'风险事件'}`,'timeline-link');b.onclick=()=>action(()=>showEvent(event.id));tags.append(b);});
    content.append(tags);item.append(time,line,content);box.append(item);
  });
}
async function showEvent(id){
  const d=await api('/events/'+id);openDialog('风险事件与判断依据');
  const box=$('dialog-body');box.append(el('p',TargetPresenter.eventSummary(d),'detail-note'));
  const facts=el('table');
  for(const [label,value] of [['目标',d.monitor_name],['发生时间',fmt(d.occurred_at)+' JST'],['级别',severityLabel[d.severity]],['规则版本','v'+d.rule.version],['数据来源',d.raw_record.provider]]){const row=el('tr');row.append(el('th',label),el('td',value));facts.append(row);}
  box.append(facts);jsonDetails('原始记录、历史规则与完整证据',d);
}
function initializeTimelines(){
  for(const kind of ['vessel','aircraft']){
    const prefix=kind+'-timeline',type=$(prefix+'-type'),severity=$(prefix+'-severity'),input=$(prefix+'-input');
    const pager=TimelinePager.create(params=>{
      const query=new URLSearchParams({...params,kind});if(!params.severity)query.delete('severity');
      return api('/timeline?'+query);
    },page=>{
      $(prefix+'-error').textContent='';
      renderTimeline(prefix,page.items);
      $(prefix+'-page').textContent=`${page.page} / ${page.totalPages} 页 · ${page.total} 条`;
      $(prefix+'-prev').disabled=page.page===1;$(prefix+'-next').disabled=page.page===page.totalPages;
      input.max=page.totalPages;if(document.activeElement!==input)input.value=page.page;
    });
    timelines.set(kind,pager);
    const run=async fn=>{const error=$(prefix+'-error');error.textContent='';try{await fn();}catch(e){error.textContent=e.message;}};
    type.onchange=()=>{if(type.value==='quality')severity.value='';run(()=>pager.filter({entry_type:type.value,severity:severity.value}));};
    severity.onchange=()=>{if(severity.value)type.value='events';run(()=>pager.filter({entry_type:type.value,severity:severity.value}));};
    for(const [suffix,fn] of [['prev',pager.previous],['next',pager.next],['latest',pager.latest]])$(prefix+'-'+suffix).onclick=()=>run(fn);
    $(prefix+'-jump').onsubmit=e=>{e.preventDefault();run(()=>pager.go(input.value));};
  }
}
function renderHeader(items,updated){
  const enabled=items.filter(m=>m.enabled),states=enabled.map(risk);
  let tone='good',label='监控正常';
  if(states.some(s=>s[1]==='high')){tone='high';label='存在风险目标';}
  else if(enabled.some(needsAttention)||states.some(s=>s[1]==='warning')){tone='warning';label='数据待关注';}
  else if(!enabled.length){tone='neutral';label=items.length?'监控已暂停':'尚无监控目标';}
  $('header-status').className='status '+tone;$('system-status').textContent=label;
  $('updated').textContent=fmt(updated)+' JST';
}
function renderMapNotes(){
  const period=schedulerSeconds===null?'按 10 分钟周期分散采集':schedulerSeconds?`按 ${schedulerSeconds/60} 分钟周期分散采集`:'自动采集已关闭';
  $('vessel-note').textContent=period+' · 橙色为风险区域 · 灰色为历史定位 · Ctrl＋滚轮缩放';
  $('flight-note').textContent=period+' · 灰色为历史定位 · Ctrl＋滚轮缩放';
}
async function refresh(){
  if(loading)return;loading=true;
  try{dashboard=await api('/dashboard');renderMonitors(dashboard.monitors);renderHeader(dashboard.monitors,dashboard.updated_at);renderMapNotes();await Promise.all([...timelines].map(async([kind,pager])=>{try{await pager.refresh();}catch(e){$(kind+'-timeline-error').textContent=e.message;}}));}
  catch(e){$('system-status').textContent='服务连接失败';$('header-status').className='status high';throw e;}
  finally{loading=false;}
}
function openDialog(title){$('dialog-title').textContent=title;$('dialog-body').replaceChildren();$('dialog-error').textContent='';if(!$('dialog').open)$('dialog').showModal();$('dialog').scrollTop=0;}
function jsonDetails(title,data,opened=false){const d=el('details');d.open=opened;d.append(el('summary',title),el('pre',JSON.stringify(data,null,2)));$('dialog-body').append(d);}
function field(form,label,name,type='text',value='',required=true){const l=el('label',undefined,'field'),input=el(type==='textarea'?'textarea':'input');const caption=el('span',label);caption.append(el('span',required?' *':'（选填）',required?'required':'optional'));l.append(caption);input.name=name;if(type!=='textarea')input.type=type;input.value=value;input.required=required;l.append(input);form.append(l);return input;}
function select(form,label,name,options){const l=el('label',undefined,'field'),s=el('select');s.name=name;options.forEach(([value,text])=>{const o=el('option',text);o.value=value;s.append(o);});l.append(el('span',label),s);form.append(l);return s;}
function submit(form,text,handler){const b=el('button',text,'primary');b.type='submit';const a=el('div',undefined,'actions');a.append(b);form.append(a);form.onsubmit=e=>{e.preventDefault();action(()=>handler(new FormData(form)),b);};}
function detailFacts(parent,title,items){
  const section=el('section',undefined,'detail-section');section.append(el('h3',title));
  const grid=el('dl',undefined,'detail-facts');
  for(const [name,value] of items){const pair=el('div');pair.append(el('dt',name),el('dd',value??'未提供'));grid.append(pair);}
  section.append(grid);parent.append(section);
}
function detailTimes(parent,m,d){
  const section=el('section',undefined,'detail-section');section.append(el('h3',m.kind==='vessel'?'航次时间':'航班时间'));
  const table=el('table',undefined,'detail-times'),head=el('tr');['JST · 日本时间','计划','预计','实际'].forEach(t=>head.append(el('th',t)));table.append(head);
  for(const [key,label] of [['departure',m.kind==='vessel'?'离港':'起飞'],['arrival','到达']]){
    const tr=el('tr');[label,fmt((m.flight||d)['scheduled_'+key]),fmt(d['estimated_'+key]),fmt(d['actual_'+key])].forEach(t=>tr.append(el('td',t)));table.append(tr);
  }
  const wrap=el('div',undefined,'detail-table-wrap');wrap.append(table);section.append(wrap);parent.append(section);
}
async function showMonitor(id){
  const m=await api('/monitors/'+id);openDialog(m.name);
  const box=$('dialog-body'),d=TargetPresenter.data(m),position=TargetPresenter.position(m),isShip=m.kind==='vessel';
  const hero=el('section',undefined,'detail-hero'),badges=el('div',undefined,'detail-badges');
  const [status,tone]=risk(m);badges.append(chip(status,tone));
  hero.append(badges,el('div',isShip?'本次航次':d.flight_context==='scheduled'?'待执行航班':d.flight_context==='recent'?'最近航班':'当前航班','detail-eyebrow'));
  hero.append(el('div',TargetPresenter.route(m,RiskPlaces.airport),'detail-route'));
  hero.append(el('p',isShip?m.business.category_label:((d.flight_number||m.name)+' · '+(m.business.aircraft_model||'机型未提供')),'detail-subtitle'));
  let explanation='';
  if(m.current?.fresh&&isShip&&d.has_newer_satellite_position&&m.health!=='ok')explanation='来源提示有更新的卫星船位，当前未接入付费卫星坐标。地图保留最后岸基位置，暂不重新判断区域风险。';
  else if(m.current?.fresh&&m.health==='unavailable'&&d.flight_status==='landed')explanation='最近航班已确认降落，来源当前未返回实时坐标。地图显示最后有效位置。';
  else if(m.current?.fresh&&d.flight_status==='scheduled')explanation='来源已指派航班，尚无实际起飞记录。';
  else if(m.last_error)explanation=m.last_error;
  else if(m.health!=='ok')explanation=healthLabel[m.health]||'当前信息有待更新';
  if(explanation)hero.append(el('p',explanation,'detail-explanation'));
  box.append(hero);
  if(isShip){
    detailFacts(box,'航次概况',[
      ['出发港代码',d.departure_port_code],['到达港代码',d.arrival_port_code],
      ['AIS 报告目的地',d.reported_destination],['最近航行状态',({under_way:'航行中',at_anchor:'锚泊',moored:'靠泊'})[d.navigation_status]||'未提供']]);
  }
  detailTimes(box,m,d);
  if(!isShip&&m.rule.config.delay_basis){
    const basis=m.rule.config.delay_basis==='departure'?'起飞':'到达';
    box.append(el('p',`延误按${basis}时间计算：实际时间优先，尚无实际时间时使用预计时间，与计划时间相减；超过 ${m.rule.config.threshold_minutes} 分钟提示风险。显示最多 1 位小数，判断使用原始精度。`,'detail-note'));
  }
  if(isShip)detailFacts(box,'船舶资料',[
    ['IMO',m.asset?.imo],['MMSI',m.asset?.mmsi],['船型 · 来源原文',m.business.category_label],['船旗',d.vessel_flag],
    ['船长 / 船宽',d.vessel_length&&d.vessel_width?`${d.vessel_length} / ${d.vessel_width} m`:null],['呼号',d.callsign]]);
  else detailFacts(box,'飞机资料',[
    ['注册号',m.asset?.registration||m.rule.config.aircraft_registration],['机型',m.business.aircraft_model],
    ['分类 · 来源原文',m.business.category_label],['呼号',d.callsign]]);
  const positionTime=position?.position_observed_at||position?.observed_at;
  const historical=m.health!=='ok'||!m.enabled||(positionTime&&(Date.now()-Date.parse(positionTime))/1000>m.rule.config.max_age_seconds);
  const positionItems=[['定位时间 · JST',fmt(positionTime)],['坐标',position?`${position.latitude.toFixed(4)}°, ${position.longitude.toFixed(4)}°${historical?'（历史）':''}`:'暂无有效定位']];
  if(isShip)positionItems.push(['最近位置海域',position?.location_name||RiskPlaces.seaName(position)],['航速 / 航向',position?.speed_knots!=null?`${position.speed_knots} kn / ${position.course_degrees??'—'}°`:null],['吃水',position?.draught_meters!=null?`${position.draught_meters} m`:null],['适用风险区域',m.regions.map(r=>r.name).join('、')||'尚未设置']);
  detailFacts(box,'最后有效位置',positionItems);
  const schedule=schedulerSeconds===null?'':schedulerSeconds?` · 自动采集每 ${schedulerSeconds/60} 分钟`:' · 自动采集关闭';
  const meta=el('p',`${sourceLabel(m)} · 最近采集 ${fmt(m.last_poll_at)} JST${schedule}`,'detail-source');box.append(meta);
  box.append(el('h3','监控设置','detail-settings-title'));
  const controls=el('div',undefined,'actions'),pause=el('button',m.enabled?'暂停监控':'恢复监控');pause.disabled=!!m.deleted_at;pause.onclick=()=>action(async()=>{await api('/monitors/'+id,'PATCH',{enabled:!m.enabled});await refresh();await showMonitor(id);},pause);controls.append(pause);box.append(controls);
  if((m.kind==='flight'||m.rule.config.capabilities?.includes('current_flight'))&&!m.deleted_at){const f=el('form'),grid=el('div',undefined,'form-grid');field(grid,'延误阈值（分钟）','threshold_minutes','number',m.rule.config.threshold_minutes);const basis=select(grid,'比较时间','delay_basis',[['departure','起飞'],['arrival','到达']]);basis.value=m.rule.config.delay_basis;f.append(grid);submit(f,'保存为新规则版本',async data=>{await api('/monitors/'+id+'/rule-versions','POST',{threshold_minutes:Number(data.get('threshold_minutes')),delay_basis:data.get('delay_basis')});await refresh();await showMonitor(id);});box.append(f);}
  addRemarkEditor(m);
  jsonDetails('目标状态、历史采集、原始记录及配置审计',m);
}
async function addMonitor(){
  openDialog('添加监控对象');
  const f=el('form'),grid=el('div',undefined,'form-grid');
  const kind=select(grid,'监控类型 *','kind',[['vessel','船舶'],['aircraft','飞机']]);
  const type=select(grid,'标识码类型 *','identifier_type',[]);
  const identifier=field(grid,'标识码','identifier');identifier.autocomplete='off';identifier.maxLength=20;
  const remark=field(grid,'备注','remark','text','',false);remark.maxLength=100;remark.placeholder='例如：项目简称、内部资产编号';
  const help=el('p',undefined,'field-help wide');help.id='identifier-help';identifier.setAttribute('aria-describedby',help.id);grid.append(help);
  const fieldHelp=()=>{
    const rules={ship_id:['例如：5630138','MarineTraffic 船舶页面中的 shipId，填写正整数。','[0-9]{1,18}'],imo:['例如：9811000','IMO 为 7 位数字，系统会检查校验位。','[0-9]{7}'],mmsi:['例如：636026627','MMSI 为 9 位数字。','[0-9]{9}'],registration:['例如：JA602F','按飞机注册号持续跟踪当前及后续航班。','[A-Za-z0-9-]{3,12}']};
    const [placeholder,text,pattern]=rules[type.value];identifier.placeholder=placeholder;identifier.pattern=pattern;identifier.inputMode=type.value==='registration'?'text':'numeric';
    help.textContent=text+(kind.value==='vessel'?' 三种标识码任选一种；船名自动读取，所有风险区域自动适用。':'');
  };
  const redraw=()=>{type.replaceChildren();(kind.value==='vessel'?[['ship_id','shipId'],['imo','IMO'],['mmsi','MMSI']]:[['registration','飞机注册号']]).forEach(([v,t])=>{const o=el('option',t);o.value=v;type.append(o);});identifier.value='';fieldHelp();};
  kind.onchange=redraw;type.onchange=()=>{identifier.value='';fieldHelp();};redraw();f.append(grid);
  const progress=el('p','填写带 * 的必填项。系统会先查询并核对身份。','enrollment-state');progress.setAttribute('role','status');f.append(progress);
  submit(f,'查询并添加',async data=>{
    progress.textContent='正在查询身份并读取首次状态，请稍候…';
    try{const m=await api('/monitors','POST',Object.fromEntries(data));await refresh();await showMonitor(m.id);}
    catch(e){progress.textContent='尚未创建，请根据提示核对后重试。';throw e;}
  });
  $('dialog-body').append(f);
}
function addRegion(){openDialog('新建风险区域');const f=el('form'),grid=el('div',undefined,'form-grid');field(grid,'区域名称','name');for(const [n,l,v] of [['west','西经度',40],['south','南纬度',10],['east','东经度',50],['north','北纬度',20]]){const input=field(grid,l,n,'number',v);input.step='any';}f.append(grid,el('p','新增矩形区域适用于所有船舶，边界计为区域内；下一次有效采集时核查。经度东正西负，纬度北正南负。','detail-note'));submit(f,'添加区域',async data=>{const value=Object.fromEntries(data);for(const n of ['west','south','east','north'])value[n]=Number(value[n]);await api('/regions','POST',value);await refresh();await manageTargets();});$('dialog-body').append(f);}
$('close-dialog').onclick=()=>$('dialog').close();$('add').onclick=()=>action(addMonitor);
$('manage').onclick=()=>action(manageTargets);
initializeTimelines();

action(async()=>{await RiskPlaces.load();const health=await api('/health');schedulerSeconds=health.scheduler_seconds;await refresh();});
setInterval(()=>{if(!document.hidden&&!$('dialog').open)action(refresh);},15000);
