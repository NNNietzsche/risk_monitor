'use strict';
function addRemarkEditor(m){
  const box=$('dialog-body');
  if(!m.deleted_at){
    const f=el('form');const input=field(f,'备注','remark','text',m.remark||'',false);input.maxLength=100;
    submit(f,'保存备注',async data=>{await api('/monitors/'+m.id+'/remark','PATCH',{remark:data.get('remark')});await refresh();await showMonitor(m.id);});box.append(f);
  }
  if(!m.source?.kinds?.length)return;
  const remove=el('button',m.deleted_at?'恢复目标（保持暂停）':'删除监控目标','danger-button');
  remove.onclick=()=>action(async()=>{
    if(m.deleted_at)await api('/monitors/'+m.id+'/restore','POST');else await api('/monitors/'+m.id,'DELETE');
    $('dialog').close();await refresh();$('notice').textContent=m.deleted_at?'目标已恢复，仍处于暂停状态。':'目标已移出列表并停止采集，历史证据保留。可在管理中恢复。';
  },remove);box.append(remove);
}
async function manageTargets(){
  const [all,regions]=await Promise.all([api('/monitors?include_deleted=true'),api('/regions?include_deleted=true')]);
  const monitors=all.filter(m=>m.source?.kinds?.length);
  openDialog('目标与区域管理');const box=$('dialog-body');
  box.append(el('p','全部有效风险区域适用于每艘船；配置变更在下一次有效采集时核查。删除目标会停止采集，历史证据保留，恢复后保持暂停。','detail-note'));
  const add=el('button','＋ 添加风险区域');add.onclick=addRegion;box.append(add);
  for(const [title,items,isRegion] of [['监控目标',monitors,false],['风险区域',regions,true]]){
    box.append(el('h3',title,'management-heading'));if(!items.length)empty(box,'暂无记录');
    const current=items.filter(i=>!i.deleted_at),deleted=items.filter(i=>i.deleted_at);
    const archive=el('details');archive.append(el('summary',`已删除记录（${deleted.length}）`));
    for(const item of [...current,...deleted]){
      const row=el('div',undefined,'list-row'),head=el('div',undefined,'row-head');
      head.append(el('strong',item.name),chip(item.deleted_at?'已删除':isRegion?'适用于全部船舶':item.enabled?'监控中':'已暂停'));
      const controls=el('div',undefined,'actions');
      if(!isRegion){const detail=el('button','详情');detail.onclick=()=>action(()=>showMonitor(item.id));controls.append(detail);}
      const button=el('button',item.deleted_at?'恢复':'删除',item.deleted_at?'':'danger-button');
      button.onclick=()=>action(async()=>{const prefix=isRegion?'/regions/':'/monitors/';await api(prefix+item.id+(item.deleted_at?'/restore':''),item.deleted_at?'POST':'DELETE');await refresh();await manageTargets();},button);
      controls.append(button);row.append(head,controls);(item.deleted_at?archive:box).append(row);
    }
    if(deleted.length)box.append(archive);
  }
}
