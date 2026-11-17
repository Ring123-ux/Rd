'use strict';
const $=s=>document.querySelector(s), VIEWS={front:'正面',left:'左侧面',back:'背面',right:'右侧面'};
var cloudUser=null;
let token='',current=null,photos={},references=[],dirty=false,busy=false,jobSignatures=new Map();
let pendingProfileSave=false,profileOwnerId=null,bootstrapRequest=null;
const label={pending:'等待生成',running:'正在生成',succeeded:'已完成',failed:'生成失败',queued:'排队中',partial_failure:'部分角度未完成',idle:'尚未开始',uploading:'上传图片',submitting:'提交任务',success:'生成成功',downloading:'保存模型',needs_attention:'需要处理',cancelled:'已取消'};
function el(tag,text,cls){const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n}
function notify(message,error=false){$('#notice').hidden=false;$('#notice').textContent=message;$('#notice').dataset.error=String(error)}
function requestId(){if(typeof crypto.randomUUID==='function')return crypto.randomUUID();if(typeof crypto.getRandomValues==='function')return Array.from(crypto.getRandomValues(new Uint8Array(16)),b=>b.toString(16).padStart(2,'0')).join('');return Date.now().toString(36)+'-'+Math.random().toString(36).slice(2)+'-'+Math.random().toString(36).slice(2)}
async function api(path,body){const response=await fetch('/api/'+path,{method:body===undefined?'GET':'POST',headers:body===undefined?{}:{'Content-Type':'application/json','X-DollFit-Token':token,'Idempotency-Key':requestId()},body:body===undefined?undefined:JSON.stringify(body)});let data;try{data=await response.json()}catch{throw Error('后台暂时无法连接，免费实例可能正在唤醒，请稍后刷新。')}if(!response.ok){const error=Error(data.error||'请求失败');error.status=response.status;if(response.status===401)window.dispatchEvent(new Event('dollfit-account-required'));throw error}return data}
function updateButtons(){const ready=cloudUser&&current&&!dirty&&!busy;$('#generate').disabled=!ready;$('#measure').disabled=!ready;const save=$('#save-profile');save.disabled=busy;save.textContent=busy?'正在处理，请稍候…':cloudUser?'保存娃娃档案':'登录后保存娃娃档案';$('#profile-account-hint').hidden=!!cloudUser;$('#new-profile').disabled=busy;$('#saved-profiles').disabled=busy;$('#import-open').disabled=busy;$('#import-submit').disabled=busy}
async function action(fn){if(busy)return;busy=true;updateButtons();try{await fn()}catch(e){notify(e.message,true)}finally{busy=false;updateButtons()}}
async function readFile(file){if(file.size>10*1024*1024)throw Error('每张图片不能超过10MB。');if(!['image/png','image/jpeg','image/webp'].includes(file.type))throw Error('请使用PNG、JPEG或WebP图片。');return new Promise((resolve,reject)=>{const r=new FileReader();r.onload=()=>resolve(r.result);r.onerror=()=>reject(Error('图片读取失败'));r.readAsDataURL(file)})}
function uploadSlots(){const grid=$('#upload-grid');grid.replaceChildren();for(const [v,name]of Object.entries(VIEWS)){const box=el('div',undefined,'photo-slot'),lab=el('label',name+' '),small=el('small',v==='front'||v==='left'?'必需':'3D需提供'),thumb=el('div','＋ 上传原图','thumb'),input=el('input');input.type='file';input.accept='image/png,image/jpeg,image/webp';input.id='photo-'+v;lab.htmlFor=input.id;lab.append(small);box.append(lab,thumb,input);grid.append(box);input.onchange=async()=>{try{if(!input.files[0])return;photos[v]=await readFile(input.files[0]);showThumb(thumb,photos[v],name);dirty=true;$('#profile-status').textContent='照片已更改，请保存为新档案。';updateButtons()}catch(e){input.value='';notify(e.message,true)}}}}
function showThumb(box,url,alt){box.replaceChildren();const img=el('img');img.src=url;img.alt=alt;box.append(img)}
function measurement(p){const m=p.measurement||{},box=$('#measurements');box.replaceChildren();if(m.rows){const table=el('table');for(const row of m.rows){const tr=el('tr');tr.append(el('td',row.name),el('td',Number(row.value).toFixed(2)+' cm'));table.append(tr)}box.append(table,el('p',m.note,'muted'))}else box.append(el('p',m.error||((m.status==='running')?'正在处理原始正面和左侧面照片…':'保存原图后点击预测13项尺寸。'),'muted'));}
async function loadProfile(id){const p=await api('profile/'+id);current=p;profileOwnerId=cloudUser?.id||null;photos={};dirty=false;jobSignatures.clear();$('#name').value=p.name;$('#height').value=p.height_cm;$('#gender').value=p.gender;$('#notes').value=p.notes;uploadSlots();for(const [v,url]of Object.entries(p.photos))showThumb($('#photo-'+v).previousElementSibling,url,VIEWS[v]);$('#saved-profiles').value=id;localStorage.setItem('dollfit-active-profile',id);$('#profile-status').textContent='已保存 '+p.views.length+' 个角度 · 档案和设计记录保存在你的账户';measurement(p);renderDesigns(p.designs);updateButtons()}
async function bootstrap(){if(bootstrapRequest)return bootstrapRequest;bootstrapRequest=(async()=>{const b=await api('bootstrap');token=b.token;if(typeof accountState==='function')accountState(b);$('#tripo-base').value=b.tripo_base;$('#quality-label').textContent=b.quality_label;const selector=$('#saved-profiles'),selected=current?.id;selector.replaceChildren(el('option','新建娃娃档案'));selector.firstChild.value='';for(const p of b.profiles){const option=el('option',p.name);option.value=p.id;selector.append(option)}if(selected)selector.value=selected;$('#api-status').textContent='合聚生图：'+(b.image_configured?'已配置':'尚未配置')+' · Tripo：'+(b.tripo_configured?'已配置':'尚未配置');return b})();try{return await bootstrapRequest}finally{bootstrapRequest=null}}
function modelPanel(job){
 const state=job.tripo||{status:'idle'},box=el('div',undefined,'model-box');
 const complete=Object.keys(job.images).length===4;
 box.append(el('strong','03 / 用四视图制作360°模型'));
 box.append(el('p',state.message||(complete?'四张试穿图已就绪。确认款式后，点击下方按钮生成最高质量3D。':'先完成或导入同一套服装的正、左、背、右四张试穿图。'),'muted'));
 if(state.status!=='idle'){
  box.append(el('p',(label[state.status]||state.status)+' · '+(state.progress||0)+'%','muted'));
  const progress=el('div',undefined,'progress'),bar=el('span');bar.style.width=Math.min(100,Math.max(0,state.progress||0))+'%';progress.append(bar);box.append(progress);
 }
 if(state.model_url){const viewer=el('model-viewer');viewer.src=state.model_url;viewer.setAttribute('camera-controls','');viewer.setAttribute('auto-rotate','');viewer.setAttribute('shadow-intensity','1');viewer.setAttribute('alt','穿着新衣服的娃娃3D模型');box.append(viewer);viewer.setAttribute('camera-orbit','0deg 75deg 110%');if(state.is_example)box.append(el('p',(state.face_count>=1500000?'最高质量实例 · 150万面':'已生成实例 · '+((state.face_count||50000)/10000)+'万面')+'；后续新任务统一使用最高质量。','muted'));const status=el('p','正在加载3D浏览组件…','muted');box.append(status);viewer.addEventListener('load',()=>status.textContent='拖动旋转 · 滚轮缩放 · 双指移动');viewer.addEventListener('error',()=>status.textContent='模型加载失败，可下载GLB后在本地3D软件中打开。');setTimeout(()=>{if(!customElements.get('model-viewer'))status.textContent='3D浏览组件未加载，请检查网络后刷新。GLB仍可下载。'},15000);const actions=el('div',undefined,'model-actions'),spin=el('button','暂停旋转','secondary'),reset=el('button','重置视角','secondary'),download=el('a','下载 GLB 模型');download.href=state.model_url;download.download='DollFit-'+job.id+'.glb';spin.onclick=()=>{viewer.toggleAttribute('auto-rotate');spin.textContent=viewer.hasAttribute('auto-rotate')?'暂停旋转':'自动旋转'};reset.onclick=()=>{viewer.cameraOrbit='0deg 75deg 105%';viewer.cameraTarget='auto auto auto';viewer.jumpCameraToGoal?.()};actions.append(spin,reset,download);box.append(actions)}
 else{
  if(complete){
   const inputs=el('div',undefined,'tripo-input-preview');
   for(const [view,name]of Object.entries(VIEWS)){const item=el('figure'),img=el('img');img.src=job.images[view];img.alt=name+'：将交给3D服务的试穿图';item.append(img,el('figcaption',name));inputs.append(item)}
   box.append(inputs,el('p','使用上面这4张已完成的试穿图，不会重新生成衣服。3D固定最高质量150万面。','muted'));
  }
  const active=['uploading','submitting','queued','running','downloading'].includes(state.status);
  const uncertain=state.submission_uncertain===true;
  const title=state.task_id?'恢复查询 / 下载（不重新生成）':uncertain?'恢复已提交的3D任务':'用这4张试穿图生成3D';
  const button=el('button',title,'primary wide');button.type='button';button.id='generate-3d-'+job.id;button.disabled=!complete||active;
  const task=el('input');task.className='restore-task';task.placeholder='仅提交响应丢失时，填写服务商任务编号';task.setAttribute('aria-label','Tripo任务编号');
  if(uncertain)box.append(el('p','生成请求可能已被接收。请先核对服务商记录，填写已有任务编号恢复，避免重复生成。','error-note'),task);
  button.onclick=()=>action(async()=>{
   if(uncertain&&!task.value.trim())throw Error('请先填写服务商已有任务编号；不会重新创建不确定的任务。');
   await api('tripo',{job_id:job.id,task_id:uncertain?task.value.trim():'',preset:'highest'});
   notify(state.task_id?'正在恢复已有任务的查询和下载。':'已把本次4张试穿图交给3D服务，进度会自动更新。');await refresh();
  });
  box.append(button);
  if(state.task_id)box.append(el('p','任务编号：'+state.task_id,'muted'));
  if(!complete)box.append(el('p','需要正、左、背、右四张同款试穿图；也可以导入之前保存的四视图。','muted'));
 }
 return box;
}
function renderDesigns(jobs){const container=$('#designs');if(!jobs?.length){if(container.querySelector('.design-entry'))container.replaceChildren(el('p','保存照片后，写下你的服装灵感。','muted'));$('#design-summary').textContent='你的新衣服，会出现在这里。';return}$('#design-summary').textContent=jobs.length+' 份设计记录';container.querySelector('.empty-design')?.remove();for(const job of jobs){const signature=JSON.stringify(job);if(jobSignatures.get(job.id)===signature)continue;jobSignatures.set(job.id,signature);const old=document.getElementById('job-'+job.id),article=el('article',undefined,'design-entry');article.id='job-'+job.id;article.append(el('div',job.prompt,'prompt-bubble'),el('p',label[job.status]||job.status,'muted'));const grid=el('div',undefined,'result-grid');for(const [v,name]of Object.entries(VIEWS)){const card=el('div',undefined,'result-view');card.append(el('strong',name));if(job.images[v]){const img=el('img');img.src=job.images[v];img.alt=name+'服装效果图';const a=el('a','下载图片');a.href=job.images[v];a.download=name+'.png';card.append(img,a)}else card.append(el('div',job.view_status[v]?(label[job.view_status[v]]||job.view_status[v]):'未提供原图','result-placeholder'));if(job.errors[v])card.append(el('p',job.errors[v],'error-note'));grid.append(card)}article.append(grid);if(['partial_failure','failed'].includes(job.status)){const retry=el('button','重试未完成角度','secondary');retry.onclick=()=>action(async()=>{if(!window.confirm('请先核对供应商记录。重试未完成角度可能产生额外生图费用，是否继续？'))return;await api('retry-design',{job_id:job.id,confirmed:true});notify('已重试未完成角度。');await refresh()});article.append(retry)}article.append(modelPanel(job));if(old)old.replaceWith(article);else container.append(article)}}
async function refresh(){if(!current)return;const id=current.id,p=await api('profile/'+id);if(current?.id!==id)return;current=p;measurement(p);renderDesigns(p.designs)}
uploadSlots();
$('#profile-form').addEventListener('input',e=>{if(e.target.type!=='file'){dirty=true;updateButtons()}});
function hasUnsavedDraft(){return dirty||Object.keys(photos).length>0||references.length>0||$('#prompt').value.trim().length>0}
async function saveProfile(){if(!cloudUser){pendingProfileSave=true;notify('请先登录，已选择的照片和填写内容会保留。');showAccount();return}await action(async()=>{if(!current&&(!photos.front||!photos.left))throw Error('请上传正面和左侧面原图。');let p;try{p=await api('profile',{source_id:current?.id,name:$('#name').value,height_cm:Number($('#height').value),gender:$('#gender').value,notes:$('#notes').value,views:photos})}catch(error){if(error.status===401)pendingProfileSave=true;throw error}pendingProfileSave=false;await bootstrap();await loadProfile(p.id);notify('娃娃档案已保存。')})}
$('#profile-form').onsubmit=e=>{e.preventDefault();saveProfile()};
$('#saved-profiles').onchange=()=>{if(!$('#saved-profiles').value)$('#new-profile').click();else action(()=>loadProfile($('#saved-profiles').value))};
$('#new-profile').onclick=()=>{current=null;profileOwnerId=null;pendingProfileSave=false;photos={};dirty=false;jobSignatures.clear();localStorage.removeItem('dollfit-active-profile');$('#profile-form').reset();$('#saved-profiles').value='';uploadSlots();$('#designs').replaceChildren(el('p','先保存新的娃娃照片。','muted'));$('#measurements').replaceChildren();updateButtons()};
$('#references').onchange=async()=>{try{const files=[...$('#references').files];if(files.length>3)throw Error('最多上传3张服装参考图。');references=await Promise.all(files.map(readFile));$('#reference-preview').replaceChildren();for(const url of references){const img=el('img');img.src=url;img.alt='服装参考';$('#reference-preview').append(img)}}catch(e){references=[];$('#references').value='';$('#reference-preview').replaceChildren();notify(e.message,true)}};
$('#measure').onclick=()=>action(async()=>{await api('measure',{profile_id:current.id});notify('正在预测原始娃体的13项尺寸。');await refresh()});
$('#design-form').onsubmit=e=>{e.preventDefault();action(async()=>{if(!current||dirty)throw Error('请先保存娃娃档案。');const auto=$('#auto-3d').checked;if(auto&&current.views.length!==4)throw Error('自动生成3D需要四个角度。请补齐四视图，或取消自动生成3D后先试穿。');await api('design',{profile_id:current.id,prompt:$('#prompt').value,references,auto_3d:auto,preset:$('#model-preset').value});$('#prompt').value='';notify(auto?'服装设计已开始，四视图完成后会自动提交Tripo生成3D。':'服装设计已开始，可在下方查看每个角度的进度。');await refresh()})};
$('#settings-link').onclick=e=>{e.preventDefault();$('#api-settings').showModal()};$('.dialog-close').onclick=()=>$('#api-settings').close();$('#settings-form').onsubmit=e=>e.preventDefault();
setInterval(()=>{if(!busy)refresh().catch(e=>notify('连接暂时中断：'+e.message,true))},5000);

$('#test-tripo').onclick=()=>action(async()=>{try{const d=await api('test-tripo',{probe_upload:true});const summary=d.provider==='seller'?'卖家服务鉴权成功 · 已使用 '+d.usage_count+' 次'+(d.expires_at?' · 有效期 '+d.expires_at:''):'Tripo官方鉴权成功 · 可用余额 '+d.balance;$('#api-status').textContent=summary;notify(summary+(d.input_source==='signed_links'?' · 四视图将通过短期授权链接交给3D服务':''))}catch(e){$('#api-status').textContent=e.message;throw e}});

$('#show-example').onclick=()=>action(async()=>{
 const box=$('#example-preview');
 if(!box.hidden){box.hidden=true;$('#show-example').textContent='查看3D实例';return}
 const sample=await api('example');
 const existing=document.getElementById('job-'+sample.id)?.querySelector('.model-box');
 if(existing){existing.scrollIntoView({behavior:'smooth',block:'center'});return}
 box.replaceChildren(modelPanel(sample));box.hidden=false;$('#show-example').textContent='收起3D实例';
 box.scrollIntoView({behavior:'smooth',block:'start'});
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
  document.getElementById('job-'+job.id)?.scrollIntoView?.({behavior:'smooth',block:'center'});
 }catch(error){$('#import-error').textContent=error.message;throw error}
})};
