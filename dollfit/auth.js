'use strict';
cloudUser=null;
const authDialog=document.getElementById('account-dialog');
const authButton=document.getElementById('account-link');
const logoutButton=document.getElementById('logout-button');
function showAccount(){authDialog.showModal()}
function resetWorkbench(){
 current=null;photos={};references=[];dirty=false;jobSignatures.clear();
 localStorage.removeItem('dollfit-active-profile');
 $('#designs').replaceChildren(el('p','保存娃娃档案后开始设计。','muted'));
 $('#profile-form').reset();uploadSlots();$('#measurements').replaceChildren();
 $('#reference-preview').replaceChildren();$('#references').value='';
}
function accountState(b){
 cloudUser=b.user||null;
 authButton.textContent=cloudUser?'你好，'+cloudUser.name:'登录 / 注册';
 logoutButton.hidden=!cloudUser;
 $('#test-tripo').hidden=!cloudUser?.admin;
 $('#storage-note').hidden=!b.ephemeral_storage;
 updateButtons();
}
authButton.onclick=e=>{e.preventDefault();if(cloudUser)notify('当前账户：'+cloudUser.name);else showAccount()};
$('#account-close').onclick=()=>authDialog.close();
$('#account-mode').onchange=()=>{
 const registering=$('#account-mode').value==='register';
 $('#invite-label').hidden=!registering;$('#invite-code').required=registering;
 $('#account-submit').textContent=registering?'创建我的工作台':'登录';
 $('#account-password').autocomplete=registering?'new-password':'current-password';
 $('#account-password').minLength=registering?10:1;
};
$('#account-form').onsubmit=async e=>{
 e.preventDefault();const button=$('#account-submit');button.disabled=true;$('#account-error').textContent='';
 try{
  await bootstrap();
  await api('auth/'+$('#account-mode').value,{username:$('#account-username').value,password:$('#account-password').value,invite_code:$('#invite-code').value});
  $('#account-password').value='';$('#invite-code').value='';resetWorkbench();
  const b=await bootstrap();if(b.profiles[0])await loadProfile(b.profiles[0].id);
  authDialog.close();notify('已进入你的设计工作台。');
 }catch(error){$('#account-error').textContent=error.message}finally{button.disabled=false}
};
logoutButton.onclick=()=>action(async()=>{await api('auth/logout',{});resetWorkbench();await bootstrap();notify('已退出登录。')});
window.addEventListener('dollfit-account-required',showAccount);

(async()=>{try{const b=await bootstrap(),id=localStorage.getItem('dollfit-active-profile');if(id&&b.profiles.some(p=>p.id===id))await loadProfile(id);else if(b.profiles[0])await loadProfile(b.profiles[0].id)}catch(e){notify(e.message,true)}})();
