const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const {JSDOM}=require('jsdom');
const root=path.resolve(__dirname,'..');
const USER={id:'a'.repeat(32),name:'alice',admin:false};
const OTHER={id:'b'.repeat(32),name:'bob',admin:false};

async function until(predicate){for(let i=0;i<200;i++){if(predicate())return;await new Promise(r=>setTimeout(r,5))}throw Error('UI condition did not complete')}
function deferred(){let resolve;const promise=new Promise(r=>resolve=r);return {promise,resolve}}
function makeProfile(id='c'.repeat(32),name='已有娃娃'){
 return {id,name,height_cm:17,gender:'female',notes:'原档案备注',views:['front','left'],photos:{front:'/old-front.png',left:'/old-left.png'},designs:[],measurement:{status:'idle'}};
}
function makeJob(tripo){
 const id='e'.repeat(32),images=Object.fromEntries(['front','left','back','right'].map(v=>[v,'/media/design/'+id+'/'+v+'_dressed.png']));
 return {id,prompt:'测试服装',status:'succeeded',images,view_status:{},errors:{},tripo:tripo||{status:'idle'}};
}
async function page(options={}){
 const dom=new JSDOM(fs.readFileSync(path.join(root,'workbench.html'),'utf8'),{url:'https://dollfit.test/workbench.html',runScripts:'outside-only'});
 const w=dom.window, calls=[],state={user:options.user||null,loginUser:options.loginUser||USER,profiles:options.profiles||[],saved:0,bootstrapCount:0};
 w.setInterval=()=>0;
 w.HTMLDialogElement.prototype.showModal=function(){this.open=true};
 w.HTMLDialogElement.prototype.close=function(){this.open=false};
 if(options.noRandomUUID)Object.defineProperty(w.crypto,'randomUUID',{value:undefined,configurable:true});
 function bootstrap(){return {token:'test-csrf',user:state.user,profiles:state.user?state.profiles.map(p=>({id:p.id,name:p.name})):[],tripo_base:'http://47.120.44.134/tripo3d',quality_label:'最高质量 · 150万面',image_configured:true,tripo_configured:true,ephemeral_storage:false}}
 w.fetch=async (url,init={})=>{
  const endpoint=url.replace('/api/',''),body=init.body?JSON.parse(init.body):undefined;
  calls.push({endpoint,body,headers:init.headers});let status=200,data;
  if(endpoint==='bootstrap'){
   state.bootstrapCount++;
   if(options.bootstrapGate&&state.bootstrapCount===1)await options.bootstrapGate.promise;
   if(options.bootstrapFails)throw Error('network unavailable');
   data=bootstrap();
  }else if(endpoint==='auth/login'||endpoint==='auth/register'){
   if(options.badLogin){status=400;data={error:'用户名或密码不正确。'}}else{state.user=state.loginUser;data={user:state.user}}
  }else if(endpoint==='auth/logout'){state.user=null;data={logged_out:true}}
  else if(endpoint==='profile'){
   if(!state.user){status=401;data={error:'请先登录。'}}else{
    if(options.saveGate)await options.saveGate.promise;
    data=makeProfile('d'.repeat(32),body.name);Object.assign(data,{height_cm:body.height_cm,gender:body.gender,notes:body.notes});state.profiles=[data];state.saved++;
   }
  }else if(endpoint.startsWith('profile/')){
   data=state.profiles.find(p=>p.id===endpoint.slice(8));if(!data){status=404;data={error:'档案不存在'}}
  }else if(endpoint==='tripo'){
   const job=state.profiles.flatMap(p=>p.designs).find(j=>j.id===body.job_id);
   if(!job)throw Error('Wrong design sent to 3D');
   job.tripo={status:'queued',progress:0};data=job.tripo;
  }else if(endpoint==='import-design'){
   const profile=state.profiles.find(p=>p.id===body.profile_id);
   data=makeJob();profile.designs.push(data);
  }else throw Error('Unexpected API '+endpoint);
  return {status,ok:status>=200&&status<300,json:async()=>JSON.parse(JSON.stringify(data))};
 };
 vm.runInContext(fs.readFileSync(path.join(root,'workbench.js'),'utf8'),dom.getInternalVMContext());
 vm.runInContext(fs.readFileSync(path.join(root,'auth.js'),'utf8'),dom.getInternalVMContext());
 if(!options.bootstrapGate){await new Promise(r=>setTimeout(r,0));await until(()=>state.bootstrapCount>0&&w.document.querySelector('#account-link').textContent.includes(state.user?state.user.name:'登录'))}
 const result={dom,w,state,calls,$:s=>w.document.querySelector(s)};
 result.draft=async()=>{
  for(const [view,i]of [['front',1],['left',2]]){
   const input=result.$('#photo-'+view);
   Object.defineProperty(input,'files',{configurable:true,value:[new w.File([new Uint8Array([1,2,3,i])],view+'.png',{type:'image/png'})]});
   await input.onchange();
  }
  for(const [id,value]of [['name','我的兔兔'],['height','40'],['notes','40CM 测试备注'],['prompt','绿色毛衣']]){
   result.$('#'+id).value=value;result.$('#'+id).dispatchEvent(new w.Event('input',{bubbles:true}));
  }
 };
 result.login=async()=>{result.$('#account-username').value='alice';result.$('#account-password').value='local-test-password';result.$('#account-form').requestSubmit();await until(()=>!result.$('#account-submit').disabled)};
 return result;
}

test('guest can click Save and sees login, not a disabled unexplained button',async()=>{
 const p=await page();try{
  assert.equal(p.$('#save-profile').disabled,false);
  assert.match(p.$('#save-profile').textContent,/登录/);
  assert.equal(p.$('#profile-account-hint').hidden,false);
  p.$('#profile-form').requestSubmit();
  assert.equal(p.$('#account-dialog').open,true);
  assert.equal(p.calls.filter(c=>c.endpoint==='profile').length,0);
 }finally{p.dom.window.close()}
});

test('photos and form survive login and the requested save resumes exactly once',async()=>{
 const p=await page();try{
  await p.draft();p.$('#profile-form').requestSubmit();await p.login();await until(()=>p.state.saved===1&&!p.$('#save-profile').disabled);
  const saves=p.calls.filter(c=>c.endpoint==='profile');assert.equal(saves.length,1);
  assert.equal(saves[0].body.name,'我的兔兔');assert.equal(saves[0].body.height_cm,40);assert.equal(saves[0].body.notes,'40CM 测试备注');
  assert.deepEqual(Object.keys(saves[0].body.views).sort(),['front','left']);
  assert.match(saves[0].body.views.front,/^data:image\/png;base64,/);
  assert.equal(p.$('#prompt').value,'绿色毛衣');assert.equal(p.$('#account-dialog').open,false);
 }finally{p.dom.window.close()}
});

test('header login preserves a new draft even if the account already has saved profiles',async()=>{
 const p=await page({profiles:[makeProfile()]});try{
  await p.draft();p.$('#account-link').click();await p.login();
  assert.equal(p.$('#name').value,'我的兔兔');assert.equal(p.$('#height').value,'40');
  assert.equal(p.$('#prompt').value,'绿色毛衣');assert.equal(p.state.saved,0);
  assert.ok(p.$('#photo-front').previousElementSibling.querySelector('img'));
 }finally{p.dom.window.close()}
});

test('slow initial bootstrap does not replace photos entered while connecting',async()=>{
 const gate=deferred(),p=await page({user:USER,profiles:[makeProfile()],bootstrapGate:gate});try{
  await p.draft();gate.resolve();await until(()=>p.$('#account-link').textContent.includes('alice'));
  await new Promise(r=>setTimeout(r,20));assert.equal(p.$('#name').value,'我的兔兔');assert.equal(p.$('#height').value,'40');
  assert.ok(p.$('#photo-front').previousElementSibling.querySelector('img'));
 }finally{p.dom.window.close()}
});

test('expired session can reauthenticate the same owner and resume the edited profile',async()=>{
 const old=makeProfile(),p=await page({user:USER,profiles:[old]});try{
  await until(()=>p.$('#name').value===old.name);await p.draft();p.state.user=null;
  p.$('#profile-form').requestSubmit();await until(()=>p.$('#account-dialog').open);await p.login();
  await until(()=>p.state.saved===1);
  const saves=p.calls.filter(c=>c.endpoint==='profile');assert.equal(saves.length,2);assert.equal(saves[1].body.source_id,old.id);assert.equal(saves[1].body.height_cm,40);
 }finally{p.dom.window.close()}
});

test('switching account clears the previous owners private draft and does not save it',async()=>{
 const old=makeProfile(),p=await page({user:USER,profiles:[old],loginUser:OTHER});try{
  await until(()=>p.$('#name').value===old.name);await p.draft();p.state.user=null;
  p.$('#profile-form').requestSubmit();await until(()=>p.$('#account-dialog').open);
  p.state.profiles=[];await p.login();
  assert.equal(p.state.saved,0);assert.equal(p.$('#name').value,'我的BJD');assert.equal(p.$('#notes').value,'');assert.equal(p.$('#prompt').value,'');
  assert.equal(p.$('#photo-front').previousElementSibling.querySelector('img'),null);
 }finally{p.dom.window.close()}
});

test('failed login keeps selected pictures and the save can be resumed after correction',async()=>{
 const config={badLogin:true},p=await page(config);try{
  await p.draft();p.$('#profile-form').requestSubmit();await p.login();
  assert.match(p.$('#account-error').textContent,/密码/);assert.equal(p.$('#name').value,'我的兔兔');assert.equal(p.state.saved,0);
  config.badLogin=false;await p.login();await until(()=>p.state.saved===1);
 }finally{p.dom.window.close()}
});

test('older WebViews without randomUUID can still log in and save',async()=>{
 const p=await page({noRandomUUID:true});try{
  await p.draft();p.$('#profile-form').requestSubmit();await p.login();await until(()=>p.state.saved===1);
  for(const call of p.calls.filter(c=>c.body))assert.match(call.headers['Idempotency-Key'],/^[A-Za-z0-9_-]{8,80}$/);
 }finally{p.dom.window.close()}
});

test('Save remains disabled during a real pending save and reenables on completion',async()=>{
 const gate=deferred(),p=await page({user:USER,saveGate:gate});try{
  await p.draft();p.$('#profile-form').requestSubmit();await until(()=>p.calls.some(c=>c.endpoint==='profile'));
  assert.equal(p.$('#save-profile').disabled,true);assert.match(p.$('#save-profile').textContent,/处理/);
  gate.resolve();await until(()=>p.state.saved===1&&!p.$('#save-profile').disabled);
 }finally{p.dom.window.close()}
});

test('connection failures do not silently lock Save and are shown inside login',async()=>{
 const p=await page({bootstrapFails:true});try{
  await p.draft();p.$('#profile-form').requestSubmit();assert.equal(p.$('#account-dialog').open,true);
  await p.login();assert.ok(p.$('#account-error').textContent);assert.equal(p.$('#save-profile').disabled,false);
 }finally{p.dom.window.close()}
});

test('four dressed views wait for an explicit click and use their own job at maximum quality',async()=>{
 const job=makeJob(),profile=makeProfile();profile.designs=[job];
 const p=await page({user:USER,profiles:[profile]});try{
  await until(()=>p.$('#generate-3d-'+job.id));
  assert.equal(p.$('#auto-3d').checked,false);
  assert.equal(p.calls.filter(c=>c.endpoint==='tripo').length,0);
  const previews=[...p.w.document.querySelectorAll('.tripo-input-preview img')];
  assert.deepEqual(previews.map(img=>img.getAttribute('src')),Object.values(job.images));
  const button=p.$('#generate-3d-'+job.id);assert.equal(button.disabled,false);
  button.click();button.click();
  await until(()=>p.$('#generate-3d-'+job.id).disabled);
  const submissions=p.calls.filter(c=>c.endpoint==='tripo');assert.equal(submissions.length,1);
  assert.equal(submissions[0].body.job_id,job.id);assert.equal(submissions[0].body.preset,'highest');
  assert.equal(p.calls.filter(c=>c.endpoint==='design').length,0);
 }finally{p.dom.window.close()}
});

test('an upload failure can continue without asking for a non-existent model task number',async()=>{
 const job=makeJob({status:'needs_attention',stage:'upload',submission_uncertain:false,message:'试穿图上传中断'}),profile=makeProfile();profile.designs=[job];
 const p=await page({user:USER,profiles:[profile]});try{
  await until(()=>p.$('#generate-3d-'+job.id));
  assert.equal(p.$('.restore-task'),null);p.$('#generate-3d-'+job.id).click();
  await until(()=>p.calls.some(c=>c.endpoint==='tripo'));
  assert.equal(p.calls.find(c=>c.endpoint==='tripo').body.task_id,'');
 }finally{p.dom.window.close()}
});

test('uncertain paid submissions require the saved provider ID and never silently generate again',async()=>{
 const job=makeJob({status:'needs_attention',stage:'submit',submission_uncertain:true}),profile=makeProfile();profile.designs=[job];
 const p=await page({user:USER,profiles:[profile]});try{
  await until(()=>p.$('.restore-task'));p.$('#generate-3d-'+job.id).click();
  await until(()=>p.$('#notice').textContent.includes('任务编号'));
  assert.equal(p.calls.filter(c=>c.endpoint==='tripo').length,0);
  p.$('.restore-task').value='provider-task-123456';p.$('#generate-3d-'+job.id).click();
  await until(()=>p.calls.some(c=>c.endpoint==='tripo'));
  assert.equal(p.calls.find(c=>c.endpoint==='tripo').body.task_id,'provider-task-123456');
 }finally{p.dom.window.close()}
});

test('partial dressed views cannot be sent to 3D',async()=>{
 const job=makeJob(),profile=makeProfile();delete job.images.back;profile.designs=[job];
 const p=await page({user:USER,profiles:[profile]});try{
  await until(()=>p.$('#generate-3d-'+job.id));assert.equal(p.$('#generate-3d-'+job.id).disabled,true);
  p.$('#generate-3d-'+job.id).click();assert.equal(p.calls.filter(c=>c.endpoint==='tripo').length,0);
 }finally{p.dom.window.close()}
});

test('importing four saved dressed views does not call either paid generation API',async()=>{
 const profile=makeProfile(),p=await page({user:USER,profiles:[profile]});try{
  await until(()=>p.$('#name').value===profile.name);p.$('#import-open').click();
  assert.equal(p.$('#import-dialog').open,true);
  for(const [i,v]of ['front','left','back','right'].entries()){
   Object.defineProperty(p.$('#import-'+v),'files',{configurable:true,value:[new p.w.File([new Uint8Array([1,2,3,i])],v+'.png',{type:'image/png'})]});
  }
  // jsdom's synthetic files do not populate native FileList validity; the handler also validates all four files.
  p.$('#import-form').dispatchEvent(new p.w.Event('submit',{cancelable:true}));await until(()=>!p.$('#import-dialog').open);
  const imports=p.calls.filter(c=>c.endpoint==='import-design');assert.equal(imports.length,1);
  assert.equal(imports[0].body.profile_id,profile.id);assert.deepEqual(Object.keys(imports[0].body.views),['front','left','back','right']);
  assert.equal(p.calls.filter(c=>['design','tripo'].includes(c.endpoint)).length,0);
  assert.ok(p.$('#generate-3d-'+makeJob().id));
 }finally{p.dom.window.close()}
});
