'use strict';

const atelierDialog = document.getElementById('panel');
const atelierFrame = document.getElementById('atelier-frame');

function openPanel(entry) {
  const profile = entry === 'profile';
  document.getElementById('home-atelier-title').textContent = profile ? '新建娃娃档案' : '娃娃衣柜';
  if (atelierFrame.getAttribute('src')) {
    atelierFrame.contentWindow.postMessage({type: 'dollfit:entry', entry}, location.origin);
  } else {
    atelierFrame.src = 'workbench.html?entry=' + (profile ? 'profile' : 'studio');
  }
  if (!atelierDialog.open) atelierDialog.showModal();
}

atelierDialog.querySelector('.close').onclick = () => atelierDialog.close();
window.addEventListener('message', event => {
  if (event.origin === location.origin && event.source === atelierFrame.contentWindow &&
      event.data?.type === 'dollfit:close') atelierDialog.close();
});
