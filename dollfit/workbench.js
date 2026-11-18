'use strict';
const $=s=>document.querySelector(s), VIEWS={front:'正面',left:'左侧面',back:'背面',right:'右侧面'};
var cloudUser=null;
let token='',current=null,photos={},references=[],dirty=false,busy=false;
let pendingProfileSave=false,profileOwnerId=null,bootstrapRequest=null;
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
function updateButtons(){const ready=cloudUser&&current&&!dirty&&!busy;$('#generate').disabled=!ready;$('#measure').disabled=!ready;const save=$('#save-profile');save.disabled=busy;save.textContent=busy?'正在处理，请稍候…':cloudUser?'保存娃娃档案':'登录后保存娃娃档案';$('#profile-account-hint').hidden=!!cloudUser;$('#new-profile').disabled=busy;$('#saved-profiles').disabled=busy;$('#import-open').disabled=busy;$('#import-submit').disabled=busy;$('#design-open').disabled=busy}
async function action(fn){if(busy)return;busy=true;updateButtons();try{await fn()}catch(e){notify(e.message,true)}finally{busy=false;updateButtons()}}
async function readFile(file){if(file.size>10*1024*1024)throw Error('每张图片不能超过10MB。');if(!['image/png','image/jpeg','image/webp'].includes(file.type))throw Error('请使用PNG、JPEG或WebP图片。');return new Promise((resolve,reject)=>{const r=new FileReader();r.onload=()=>resolve(r.result);r.onerror=()=>reject(Error('图片读取失败'));r.readAsDataURL(file)})}
function uploadSlots(){const grid=$('#upload-grid');grid.replaceChildren();for(const [v,name]of Object.entries(VIEWS)){const box=el('div',undefined,'photo-slot'),lab=el('label',name+' '),small=el('small',v==='front'||v==='left'?'必需':'3D需提供'),thumb=el('div','＋ 上传原图','thumb'),input=el('input');input.type='file';input.accept='image/png,image/jpeg,image/webp';input.id='photo-'+v;lab.htmlFor=input.id;lab.append(small);box.append(lab,thumb,input);grid.append(box);input.onchange=async()=>{try{if(!input.files[0])return;photos[v]=await readFile(input.files[0]);showThumb(thumb,photos[v],name);dirty=true;$('#profile-status').textContent='照片已更改，请保存档案。';updateButtons()}catch(e){input.value='';notify(e.message,true)}}}}
function showThumb(box,url,alt){box.replaceChildren();const img=el('img');img.src=url;img.alt=alt;box.append(img)}
function measurement(p){const m=p.measurement||{},box=$('#measurements');box.replaceChildren();if(m.rows){const table=el('table');for(const row of m.rows){const tr=el('tr');tr.append(el('td',row.name),el('td',Number(row.value).toFixed(2)+' cm'));table.append(tr)}box.append(table,el('p',m.note,'muted'))}else box.append(el('p',m.error||((m.status==='running')?'正在处理原始正面和左侧面照片…':'保存原图后点击预测13项尺寸。'),'muted'));}
async function loadProfile(id){const p=await api('profile/'+id);current=p;profileOwnerId=cloudUser?.id||null;photos={};dirty=false;closeOutfit();$('#name').value=p.name;$('#height').value=p.height_cm;$('#gender').value=p.gender;$('#notes').value=p.notes;uploadSlots();for(const [v,url]of Object.entries(p.photos))showThumb($('#photo-'+v).previousElementSibling,url,VIEWS[v]);$('#saved-profiles').value=id;localStorage.setItem('dollfit-active-profile',id);$('#profile-status').textContent='已保存 '+p.views.length+' 个角度 · 档案和设计记录保存在你的账户';measurement(p);renderDesigns(p.designs);updateButtons()}
async function bootstrap(){if(bootstrapRequest)return bootstrapRequest;bootstrapRequest=(async()=>{const b=await api('bootstrap');token=b.token;if(typeof accountState==='function')accountState(b);$('#tripo-base').value=b.tripo_base;const selector=$('#saved-profiles'),selected=current?.id;selector.replaceChildren(el('option','新建娃娃档案'));selector.firstChild.value='';for(const p of b.profiles){const option=el('option',p.name);option.value=p.id;selector.append(option)}if(selected)selector.value=selected;$('#api-status').textContent='合聚生图：'+(b.image_configured?'已配置':'尚未配置')+' · Tripo：'+(b.tripo_configured?'已配置':'尚未配置');return b})();try{return await bootstrapRequest}finally{bootstrapRequest=null}}
async function refresh(){if(!current)return;const id=current.id,p=await api('profile/'+id);if(current?.id!==id)return;current=p;measurement(p);renderDesigns(p.designs)}
uploadSlots();
$('#profile-form').addEventListener('input',e=>{if(e.target.type!=='file'){dirty=true;updateButtons()}});
function hasUnsavedDraft(){return dirty||Object.keys(photos).length>0||references.length>0||$('#prompt').value.trim().length>0||$('#outfit-name').value.trim().length>0}
async function saveProfile(){if(!cloudUser){pendingProfileSave=true;notify('请先登录，已选择的照片和填写内容会保留。');showAccount();return}await action(async()=>{if(!current&&(!photos.front||!photos.left))throw Error('请上传正面和左侧面原图。');let p;try{p=await api('profile',{source_id:current?.id,name:$('#name').value,height_cm:Number($('#height').value),gender:$('#gender').value,notes:$('#notes').value,views:photos})}catch(error){if(error.status===401)pendingProfileSave=true;throw error}pendingProfileSave=false;await bootstrap();await loadProfile(p.id);notify('娃娃档案已保存。')})}
$('#profile-form').onsubmit=e=>{e.preventDefault();saveProfile()};
$('#saved-profiles').onchange=()=>{if(!$('#saved-profiles').value)$('#new-profile').click();else action(()=>loadProfile($('#saved-profiles').value))};
$('#new-profile').onclick=()=>{current=null;profileOwnerId=null;pendingProfileSave=false;photos={};dirty=false;closeOutfit();localStorage.removeItem('dollfit-active-profile');$('#profile-form').reset();$('#saved-profiles').value='';uploadSlots();renderDesigns([]);$('#profile-status').textContent='正面和左侧面必需；完整四视图还需要背面与右侧面。';$('#measurements').replaceChildren();updateButtons()};
$('#references').onchange=async()=>{try{const files=[...$('#references').files];if(files.length>3)throw Error('最多上传3张服装参考图。');references=await Promise.all(files.map(readFile));$('#reference-preview').replaceChildren();for(const url of references){const img=el('img');img.src=url;img.alt='服装参考';$('#reference-preview').append(img)}}catch(e){references=[];$('#references').value='';$('#reference-preview').replaceChildren();notify(e.message,true)}};
$('#measure').onclick=()=>action(async()=>{await api('measure',{profile_id:current.id});notify('正在预测原始娃体的13项尺寸。');await refresh()});
function focusProfile() {
 $('#profile').scrollIntoView?.({block:'start'});
 $('#name').focus({preventScroll:true});
}
$('#design-open').onclick=()=>{
 if(!cloudUser){showAccount();return}
 if(!current||dirty){notify('请先保存娃娃档案，再设计它的衣服。');focusProfile();return}
 $('#design-doll').textContent=current.name+'的衣柜';
 const count=current.views.length;
 $('#design-angles').textContent=count===4?'将生成正面、左侧面、背面、右侧面，完成后自动收进衣柜。':
  '将为已上传的'+count+'个角度生成试穿图。做3D需要完整四视图。';
 $('#generate').textContent=count===4?'生成服装四视图':'生成已上传角度';
 $('#design-dialog [data-notice]').hidden=true;
 $('#design-dialog').showModal();
};
$('#design-close').onclick=()=>$('#design-dialog').close();

$('#design-form').onsubmit=e=>{
 e.preventDefault();
 action(async()=>{
  if(!current||dirty)throw Error('请先保存娃娃档案。');
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
  await refresh();
  openOutfit(job.id);
 });
};
$('#settings-link').onclick=e=>{e.preventDefault();$('#api-settings').showModal()};$('.dialog-close').onclick=()=>$('#api-settings').close();$('#settings-form').onsubmit=e=>e.preventDefault();
setInterval(()=>{if(!busy)refresh().catch(e=>notify('连接暂时中断：'+e.message,true))},5000);

$('#test-tripo').onclick=()=>action(async()=>{try{const d=await api('test-tripo',{probe_upload:true});const summary=d.provider==='seller'?'卖家服务鉴权成功 · 已使用 '+d.usage_count+' 次'+(d.expires_at?' · 有效期 '+d.expires_at:''):'Tripo官方鉴权成功 · 可用余额 '+d.balance;$('#api-status').textContent=summary;notify(summary+(d.input_source==='signed_links'?' · 四视图将通过短期授权链接交给3D服务':''))}catch(e){$('#api-status').textContent=e.message;throw e}});

$('#show-example').onclick=()=>action(async()=>{
 const box=$('#example-preview');
 if(!box.hidden){box.hidden=true;$('#show-example').textContent='查看3D实例';return}
 const sample=await api('example');
 const existing=document.getElementById('job-'+sample.id)?.querySelector('.model-box');
 if(existing){existing.scrollIntoView({behavior:'smooth',block:'center'});return}
 box.replaceChildren(modelViewer(sample));box.hidden=false;$('#show-example').textContent='收起3D实例';
 box.scrollIntoView?.({behavior:'smooth',block:'nearest'});
});

$('#import-open').onclick=()=>{
 if(!cloudUser){notify('请先登录并保存娃娃档案，再导入已有试穿图。');showAccount();return}
 if(!current||dirty){notify('请先保存当前娃娃档案，然后导入已完成的服装四视图。',true);return}
 $('#import-error').textContent='';$('#import-dialog').showModal();
};
$('#import-close').onclick=()=>$('#import-dialog').close();
$('#import-form').onsubmit=e=>{e.preventDefault();action(async()=>{
 try{
  if(!current||dirty)throw Error('请先保存娃娃档案。');
  const views={};for(const view of Object.keys(VIEWS)){const file=$('#import-'+view).files[0];if(!file)throw Error('请提供'+VIEWS[view]+'试穿图。');views[view]=await readFile(file)}
  const job=await api('import-design',{profile_id:current.id,views});
  await refresh();$('#import-dialog').close();$('#import-form').reset();
  notify('已导入4张试穿图，点击“用这4张试穿图生成3D”即可继续。');
  openOutfit(job.id);
 }catch(error){$('#import-error').textContent=error.message;throw error}
})};

let entryMode=new URLSearchParams(location.search).get('entry');
if(window.parent!==window){
 document.body.classList.add('embedded-workbench');
 window.addEventListener('message',event=>{
  if(event.origin!==location.origin||event.source!==window.parent||event.data?.type!=='dollfit:entry')return;
  if(event.data.entry==='profile'){
   entryMode='profile';
   if(!hasUnsavedDraft())$('#new-profile').click();
   focusProfile();
  }else if(event.data.entry==='studio'){
   entryMode='studio';
   $('#design').scrollIntoView?.({block:'start'});
  }
 });
 document.addEventListener('keydown',event=>{
  if(event.key==='Escape'&&!document.querySelector('dialog[open]')){
   window.parent.postMessage({type:'dollfit:close'},location.origin);
  }
 });
}
