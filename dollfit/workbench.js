'use strict';
const $=s=>document.querySelector(s), VIEWS={front:'正面',left:'左侧面',back:'背面',right:'右侧面'};
var cloudUser=null;
let token='',current=null,photos={},references=[],dirty=false,busy=false;
let tripoFaceCounts=[], measurementFields=[], manualMeasurements={};
const sizeGroups=[
 ['chest','waist','hip','shoulder-breadth','shoulder-to-crotch'],
 ['arm-length','bicep','forearm','wrist'],
 ['leg-length','thigh','calf','ankle']
];
let pendingProfileSave=false,profileOwnerId=null,profileDraftId=null,bootstrapRequest=null;
const profileDialog=$('#profile-dialog'), sizesDialog=$('#sizes-dialog');
const label={pending:'等待生成',running:'正在生成',succeeded:'已完成',failed:'生成失败',queued:'排队中',partial_failure:'部分角度未完成',idle:'尚未开始',uploading:'上传图片',submitting:'提交任务',success:'生成成功',downloading:'保存模型',needs_attention:'需要处理',cancelled:'已取消'};
function el(tag,text,cls){const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n}
function notify(message,error=false){
 const output=[...document.querySelectorAll('dialog[open] [data-notice]')].at(-1)||$('#notice');
 output.hidden=false;
 output.textContent=message;
 output.dataset.error=String(error);
}
function requestId(){if(typeof crypto.randomUUID==='function')return crypto.randomUUID();if(typeof crypto.getRandomValues==='function')return Array.from(crypto.getRandomValues(new Uint8Array(16)),b=>b.toString(16).padStart(2,'0')).join('');return Date.now().toString(36)+'-'+Math.random().toString(36).slice(2)+'-'+Math.random().toString(36).slice(2)}
async function api(path,body){const response=await fetch('/api/'+path,{method:body===undefined?'GET':'POST',headers:body===undefined?{}:{'Content-Type':'application/json','X-DollFit-Token':token,'Idempotency-Key':requestId()},body:body===undefined?undefined:JSON.stringify(body)});let data;try{data=await response.json()}catch{throw Error('后台暂时无法连接，免费实例可能正在唤醒，请稍后刷新。')}if(!response.ok){const error=Error(data.error||'请求失败');error.status=response.status;if(response.status===401)window.dispatchEvent(new Event('dollfit-account-required'));throw error}return data}
function updateButtons(){
 const ready=cloudUser&&current&&!busy;
 $('#generate').disabled=!ready;
 $('#measure').disabled=!ready||profileDraftId!==current?.id||dirty||current?.measurement?.status==='running';
 const saved=!!(current&&profileDraftId===current.id&&!dirty&&cloudUser);
 const download=$('#tailoring-download');
 download.hidden=!saved;
 if(saved)download.href='/api/profile/'+current.id+'/tailoring';
 else download.removeAttribute('href');
 const manual=$('#manual-open');
 manual.disabled=busy||!measurementFields.length;
 const count=Object.keys(manualMeasurements).length;
 manual.textContent=count?'编辑实测尺寸 · '+count+' 项':'＋ 添加实测尺寸';
 const save=$('#save-profile');
 save.disabled=busy;
 save.textContent=busy?'正在处理，请稍候…':cloudUser?'保存并回到衣柜':'登录后保存娃娃档案';
 $('#profile-account-hint').hidden=!!cloudUser;
 for(const id of ['profile-open','new-profile','saved-profiles','import-open','import-submit','design-open']){
  $('#'+id).disabled=busy;
 }
}
async function action(fn){if(busy)return;busy=true;updateButtons();try{await fn()}catch(e){notify(e.message,true)}finally{busy=false;updateButtons()}}
async function readFile(file){if(file.size>10*1024*1024)throw Error('每张图片不能超过10MB。');if(!['image/png','image/jpeg','image/webp'].includes(file.type))throw Error('请使用PNG、JPEG或WebP图片。');return new Promise((resolve,reject)=>{const r=new FileReader();r.onload=()=>resolve(r.result);r.onerror=()=>reject(Error('图片读取失败'));r.readAsDataURL(file)})}
function uploadSlots(){const grid=$('#upload-grid');grid.replaceChildren();for(const [v,name]of Object.entries(VIEWS)){const box=el('div',undefined,'photo-slot'),lab=el('label',name+' '),small=el('small',v==='front'||v==='left'?'必需':'3D需提供'),thumb=el('div','＋ 上传原图','thumb'),input=el('input');input.type='file';input.accept='image/png,image/jpeg,image/webp';input.id='photo-'+v;lab.htmlFor=input.id;lab.append(small);box.append(lab,thumb,input);thumb.onclick=()=>input.click();grid.append(box);input.onchange=async()=>{try{if(!input.files[0])return;photos[v]=await readFile(input.files[0]);showThumb(thumb,photos[v],name);dirty=true;$('#profile-status').textContent='照片已更改，请保存档案。';updateButtons()}catch(e){input.value='';notify(e.message,true)}}}}
function showThumb(box,url,alt){box.replaceChildren();const img=el('img');img.src=url;img.alt=alt;box.append(img)}
function selectDialogPage(group,page){
 for(const button of document.querySelectorAll('[data-'+group+'-page]')){
  button.setAttribute('aria-pressed',String(button.getAttribute('data-'+group+'-page')===page));
 }
}
function profilePage(page){
 selectDialogPage('profile',page);
 $('#profile-info').hidden=page!=='info';
 $('#profile-photos').hidden=page!=='photos';
}
function sizePage(page){
 selectDialogPage('size',page);
 for(const panel of $('#manual-fields').children)panel.hidden=panel.dataset.group!==page;
}
function openSizes(estimate=false){
 $('#sizes-title').textContent=estimate?'AI 估测尺寸':'实测尺寸 · cm';
 $('#sizes-form').hidden=estimate;
 $('#estimate-panel').hidden=!estimate;
 $('#estimate-panel [data-notice]').hidden=true;
 if(estimate){
  measurement(profileDraftId===current?.id?current:{});
 }else{
  const fields=$('#manual-fields');
  fields.replaceChildren();
  sizeGroups.forEach((keys,index)=>{
   const panel=el('div',undefined,'manual-grid');
   panel.dataset.group=String(index);
   for(const key of keys){
    const name=measurementFields.find(field=>field.key===key)?.name;
    if(!name)continue;
    const field=el('label',name), input=el('input');
    input.type='number';
    input.inputMode='decimal';
    input.min='0.001';
    input.max='300';
    input.step='any';
    input.dataset.measurement=key;
    input.value=manualMeasurements[key]??'';
    field.append(input);
    panel.append(field);
   }
   fields.append(panel);
  });
  sizePage('0');
 }
 sizesDialog.showModal();
}
function measurement(p){
 const m=p?.measurement||{}, box=$('#measurements');
 box.replaceChildren();
 if(m.rows){
  const table=el('dl',undefined,'estimate-grid');
  for(const row of m.rows){
   const line=el('div');
   line.append(el('dt',row.name),el('dd',Number(row.value).toFixed(2)+' cm'));
   table.append(line);
  }
  box.append(table,el('p',m.note||'估测仅供参考，定制前请录入实测尺寸。','muted'));
 }else{
  box.append(el('p',m.error||(m.status==='running'?'正在处理原始正面和左侧面照片…':'保存档案后，可用正面和左侧面照片预测13项尺寸。'),'muted'));
 }
}
for(const button of document.querySelectorAll('[data-profile-page]'))button.onclick=()=>profilePage(button.dataset.profilePage);
for(const button of document.querySelectorAll('[data-size-page]'))button.onclick=()=>sizePage(button.dataset.sizePage);
$('#manual-open').onclick=()=>openSizes();
$('#estimate-open').onclick=()=>openSizes(true);
$('#sizes-close').onclick=()=>sizesDialog.close();
$('#sizes-form').noValidate=true;
$('#sizes-form').onsubmit=e=>{
 e.preventDefault();
 const fields=[...$('#manual-fields').querySelectorAll('input')];
 const invalid=fields.find(input=>!input.validity.valid);
 if(invalid){
  sizePage(invalid.closest('[data-group]').dataset.group);
  invalid.reportValidity();
  return;
 }
 const updated=Object.fromEntries(fields.filter(input=>input.value!=='').map(input=>[input.dataset.measurement,input.valueAsNumber]));
 if(fields.some(input=>updated[input.dataset.measurement]!==manualMeasurements[input.dataset.measurement])){
  manualMeasurements=updated;
  dirty=true;
  updateButtons();
 }
 sizesDialog.close();
};
function fillProfileForm(profile){
 profileDraftId=profile?.id||null;
 photos={};
 dirty=false;
 pendingProfileSave=false;
 $('#profile-form').reset();
 $('#saved-profiles').value=profileDraftId||'';
 manualMeasurements={...profile?.manual_measurements_cm};
 if(sizesDialog.open)sizesDialog.close();
 profilePage('info');
 uploadSlots();
 if(profile){
  $('#name').value=profile.name;
  $('#height').value=profile.height_cm;
  $('#gender').value=profile.gender;
  $('#notes').value=profile.notes;
  for(const [view,url] of Object.entries(profile.photos)){
   showThumb($('#photo-'+view).previousElementSibling,url,VIEWS[view]);
  }
 }
 $('#profile-status').textContent=profile?'已保存 '+profile.views.length+' 个角度。':'正面和左侧面必需；完整四视图还需要背面与右侧面。';
 measurement(profile||{});
 updateButtons();
}
function useProfile(profile,{keepDraft=false}={}){
 const changed=current?.id!==profile.id;
 current=profile;
 profileOwnerId=cloudUser?.id||null;
 localStorage.setItem('dollfit-active-profile',profile.id);
 if(changed){
  closeOutfit();
  wardrobePage=0;
 }
 if(!keepDraft)fillProfileForm(profile);
 renderDesigns(profile.designs);
 updateButtons();
}
async function loadProfile(id,options){
 useProfile(await api('profile/'+id),options);
}
async function bootstrap(){if(bootstrapRequest)return bootstrapRequest;bootstrapRequest=(async()=>{const b=await api('bootstrap');token=b.token;tripoFaceCounts=b.tripo_face_counts||[];measurementFields=b.measurement_fields||[];if(typeof accountState==='function')accountState(b);$('#tripo-base').value=b.tripo_base;const selector=$('#saved-profiles');selector.replaceChildren(el('option','新建娃娃档案'));selector.firstChild.value='';for(const p of b.profiles){const option=el('option',p.name);option.value=p.id;selector.append(option)}selector.value=profileDraftId||'';$('#api-status').textContent='合聚生图：'+(b.image_configured?'已配置':'尚未配置')+' · Tripo：'+(b.tripo_configured?'已配置':'尚未配置');return b})();try{return await bootstrapRequest}finally{bootstrapRequest=null}}
async function refresh(){
 const previous=current;
 if(!previous)return;
 const profile=await api('profile/'+previous.id);
 if(current!==previous)return;
 current=profile;
 if(profileDialog.open&&profileDraftId===profile.id){
  measurement(profile);
  updateButtons();
 }
 renderDesigns(profile.designs);
}
uploadSlots();
$('#profile-form').addEventListener('input',e=>{if(e.target.type!=='file'){dirty=true;updateButtons()}});
function hasUnsavedDraft(){return dirty||Object.keys(photos).length>0||references.length>0||$('#prompt').value.trim().length>0||$('#outfit-name').value.trim().length>0}
async function saveProfile(){
 if(!cloudUser){
  pendingProfileSave=true;
  notify('请先登录，已选择的照片和填写内容会保留。');
  showAccount();
  return;
 }
 await action(async()=>{
  if(!profileDraftId&&(!photos.front||!photos.left)){
   profilePage('photos');
   throw Error('请上传正面和左侧面原图。');
  }
  if(profileDraftId===current?.id&&!dirty){
   profileDialog.close();
   return;
  }
  const body={
   profile_id:profileDraftId,
   name:$('#name').value,
   height_cm:Number($('#height').value),
   gender:$('#gender').value,
   notes:$('#notes').value,
   manual_measurements_cm:manualMeasurements,
   views:photos
  };
  let saved;
  try{saved=await api('profile',body)}
  catch(error){if(error.status===401)pendingProfileSave=true;throw error}
  useProfile(saved);
  profileDialog.close();
  notify('娃娃档案已保存。');
  await bootstrap();
 });
}
$('#profile-form').onsubmit=e=>{e.preventDefault();saveProfile()};
$('#saved-profiles').onchange=()=>{
 const id=$('#saved-profiles').value;
 if(!id){fillProfileForm(null);return}
 return action(async()=>{
  try{
   await loadProfile(id);
   profileDialog.close();
  }catch(error){
   $('#saved-profiles').value=profileDraftId||'';
   throw error;
  }
 });
};
$('#new-profile').onclick=()=>{fillProfileForm(null);$('#name').focus()};
function openProfile({create=false}={}){
 if(create&&(!dirty||profileDraftId))fillProfileForm(null);
 else if(!dirty&&current)fillProfileForm(current);
 else if(profileDraftId===current?.id&&current)measurement(current);
 $('#profile-dialog [data-notice]').hidden=true;
 if(!profileDialog.open)profileDialog.showModal();
}
$('#profile-open').onclick=()=>openProfile();
$('#profile-close').onclick=()=>profileDialog.close();
$('#references').onchange=async()=>{try{const files=[...$('#references').files];if(files.length>3)throw Error('最多上传3张服装参考图。');references=await Promise.all(files.map(readFile));$('#reference-preview').replaceChildren();for(const url of references){const img=el('img');img.src=url;img.alt='服装参考';$('#reference-preview').append(img)}}catch(e){references=[];$('#references').value='';$('#reference-preview').replaceChildren();notify(e.message,true)}};
$('#measure').onclick=()=>action(async()=>{
 await api('measure',{profile_id:current.id});
 notify('正在预测原始娃体的13项尺寸。');
 await refresh();
});
function designPage(page){
 selectDialogPage('design',page);
 $('#design-style').hidden=page!=='style';
 $('#design-options').hidden=page!=='options';
}
for(const button of document.querySelectorAll('[data-design-page]'))button.onclick=()=>designPage(button.dataset.designPage);
$('#prompt').addEventListener('invalid',()=>designPage('style'));
$('#height').addEventListener('invalid',()=>profilePage('info'));
$('#design-open').onclick=()=>{
 if(!current){openProfile();notify('请先保存一个娃娃档案。');return}
 if(!cloudUser){showAccount();return}
 $('#design-doll').textContent=current.name+'的衣柜';
 const count=current.views.length;
 $('#design-angles').textContent=count===4?'将生成正面、左侧面、背面、右侧面，完成后自动收进衣柜。':
  '将为已上传的'+count+'个角度生成试穿图。做3D需要完整四视图。';
 $('#generate').textContent=count===4?'生成服装四视图':'生成已上传角度';
 $('#design-dialog [data-notice]').hidden=true;
 designPage('style');
 $('#design-dialog').showModal();
};
$('#design-close').onclick=()=>$('#design-dialog').close();

$('#design-form').onsubmit=e=>{
 e.preventDefault();
 action(async()=>{
  if(!current)throw Error('请先保存娃娃档案。');
  const job=await api('design',{
   profile_id:current.id,
   outfit_name:$('#outfit-name').value,
   prompt:$('#prompt').value,
   references,
   quality:$('#design-form input[name="image-quality"]:checked').value,
   new_outfit:true
  });
  $('#design-form').reset();
  references=[];
  $('#reference-preview').replaceChildren();
  $('#design-dialog').close();
  notify('已开始生成，试穿图会自动保存到当前娃娃的衣柜。');
  recordOutfit(job);
 });
};
$('#settings-link').onclick=e=>{e.preventDefault();$('#api-settings').showModal()};$('.dialog-close').onclick=()=>$('#api-settings').close();$('#settings-form').onsubmit=e=>e.preventDefault();
setInterval(()=>{if(!busy)refresh().catch(e=>notify('连接暂时中断：'+e.message,true))},5000);

$('#test-tripo').onclick=()=>action(async()=>{try{const d=await api('test-tripo',{probe_upload:true});const summary=d.provider==='seller'?'卖家服务鉴权成功 · 已使用 '+d.usage_count+' 次'+(d.expires_at?' · 有效期 '+d.expires_at:''):'Tripo官方鉴权成功 · 可用余额 '+d.balance;$('#api-status').textContent=summary;notify(summary+(d.input_source==='signed_links'?' · 四视图将通过短期授权链接交给3D服务':''))}catch(e){$('#api-status').textContent=e.message;throw e}});

$('#import-open').onclick=()=>{
 if(!current){openProfile();notify('先保存娃娃档案，再导入这只娃娃的试穿图。');return}
 if(!cloudUser){showAccount();return}
 $('#import-error').textContent='';$('#import-dialog').showModal();
};
$('#import-close').onclick=()=>$('#import-dialog').close();
$('#import-form').onsubmit=e=>{e.preventDefault();action(async()=>{
 try{
  if(!current)throw Error('请先保存娃娃档案。');
  const views={};for(const view of Object.keys(VIEWS)){const file=$('#import-'+view).files[0];if(!file)throw Error('请提供'+VIEWS[view]+'试穿图。');views[view]=await readFile(file)}
  const job=await api('import-design',{profile_id:current.id,views});
  $('#import-dialog').close();
  $('#import-form').reset();
  recordOutfit(job);
  notify('四张试穿图已收进衣柜。');
 }catch(error){$('#import-error').textContent=error.message;throw error}
})};

let entryMode=new URLSearchParams(location.search).get('entry');
if(window.parent!==window){
 document.body.classList.add('embedded-workbench');
 window.addEventListener('message',event=>{
  if(event.origin!==location.origin||event.source!==window.parent||event.data?.type!=='dollfit:entry')return;
  if(event.data.entry==='profile'){
   entryMode='profile';
   openProfile({create:true});
  }else if(event.data.entry==='studio'){
   entryMode='studio';
   profileDialog.close();
  }
 });
 document.addEventListener('keydown',event=>{
  if(event.key==='Escape'&&!document.querySelector('dialog[open]')){
   window.parent.postMessage({type:'dollfit:close'},location.origin);
  }
 });
}
