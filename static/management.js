'use strict';
const vesselTypes=[['','未分类 / 使用来源提供的分类'],['container','集装箱船'],['tanker','油轮'],['liquid_cargo','液货船（细分未提供）'],['bulk','散货船'],['cargo','货船（细分未提供）'],['passenger','客船'],['pilot','引航船'],['tug','拖轮'],['fishing','渔船'],['other','其他船舶']];
const aircraftRoles=[['','未分类 / 使用来源提供的分类'],['passenger','客机'],['cargo','货机'],['mixed','客货混合'],['other','其他用途']];
function profileFields(parent,kind,profile={}){
  if(kind==='vessel')select(parent,'船型','vessel_type',vesselTypes).value=profile.vessel_type||'';
  else{
    field(parent,'机型（可留空，使用来源信息）','aircraft_model','text',profile.aircraft_model||'',false);
    select(parent,'用途','aircraft_role',aircraftRoles).value=profile.aircraft_role||'';
  }
}
function takeProfile(value){
  const profile={};
  for(const key of ['vessel_type','aircraft_role','aircraft_model']){profile[key]=value[key]||null;delete value[key];}
  return profile;
}
function addProfileEditor(m){
  const box=$('dialog-body'),f=el('form'),grid=el('div',undefined,'form-grid');
  if(!m.deleted_at&&m.source?.profile_mode!=='provider'){
    profileFields(grid,m.kind,m.profile);f.append(grid,el('p','依据资产台账或已核实资料填写。留空使用来源信息；没有来源信息则显示未分类。','detail-note'));
    submit(f,'保存资产属性',async data=>{await api('/monitors/'+m.id+'/profile','PATCH',takeProfile(Object.fromEntries(data)));await refresh();await showMonitor(m.id);});box.append(f);
  }
  const remove=el('button',m.deleted_at?'恢复目标（保持暂停）':'删除监控目标','danger-button');
  remove.onclick=()=>action(async()=>{
    if(m.deleted_at)await api('/monitors/'+m.id+'/restore','POST');else await api('/monitors/'+m.id,'DELETE');
    $('dialog').close();await refresh();$('notice').textContent=m.deleted_at?'目标已恢复，仍处于暂停状态；需要时在详情中恢复监控。':'目标已移出列表并停止采集，历史证据保留。可在“目标与区域管理”中恢复。';
  },remove);box.append(remove);
}
async function manageTargets(){
  const [monitors,regions]=await Promise.all([api('/monitors?include_deleted=true'),api('/regions?include_deleted=true')]);
  openDialog('目标与区域管理');const box=$('dialog-body');
  box.append(el('p','删除目标会停止采集并移出跟踪列表；历史事件与证据保留。恢复后保持暂停。区域仍被目标引用时不能删除，暂停目标也算引用。','detail-note'));
  for(const [title,items,isRegion] of [['监控目标',monitors,false],['监控区域',regions,true]]){
    box.append(el('h3',title));if(!items.length)empty(box,'暂无记录');
    for(const item of items){
      const row=el('div',undefined,'list-row'),head=el('div',undefined,'row-head');
      head.append(el('strong',item.name),chip(item.deleted_at?'已删除':isRegion?'可用':item.enabled?'监控中':'已暂停'));
      const controls=el('div',undefined,'actions');
      if(!isRegion){const detail=el('button','详情');detail.onclick=()=>action(()=>showMonitor(item.id));controls.append(detail);}
      const button=el('button',item.deleted_at?'恢复':'删除',item.deleted_at?'':'danger-button');
      if(isRegion&&!item.deleted_at&&item.monitor_names.length){button.disabled=true;row.append(el('p','正在使用：'+item.monitor_names.join('、'),'detail-note'));}
      button.onclick=()=>action(async()=>{const prefix=isRegion?'/regions/':'/monitors/';await api(prefix+item.id+(item.deleted_at?'/restore':''),item.deleted_at?'POST':'DELETE');await refresh();await manageTargets();},button);
      controls.append(button);row.prepend(head);row.append(controls);box.append(row);
    }
  }
}
async function refreshGroup(group,button){
  await action(async()=>{
    const result=await api('/poll?group='+group,'POST');await refresh();
    $('notice').textContent=result.items.length?`${group==='vessel'?'船舶':'航空'}已采集 ${result.items.length} 个目标；最新航次、航班及位置状态已显示。`:'该类别没有启用的监控目标。';
  },button);
}
