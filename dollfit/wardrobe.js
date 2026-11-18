'use strict';

const qualityNames = {low: '快速', medium: '均衡', high: '精细'};
let wardrobeSignature = '';
let openedOutfitId = null;
let selectedOutfitView = 'front';
let stageSignature = '';
let detailSignature = '';

function outfitName(job) {
  const description = job.prompt?.trim().split(/[\n。；，]/u)[0] || '未命名娃衣';
  return job.name || (description.length > 24 ? description.slice(0, 24) + '…' : description);
}

function wardrobeCard(job) {
  const button = el('button', undefined, 'wardrobe-item');
  button.id = 'job-' + job.id;
  button.type = 'button';
  button.onclick = () => openOutfit(job.id);

  const cover = el('span', undefined, 'wardrobe-cover');
  if (job.cover_url || job.images.front) {
    const image = el('img');
    image.src = job.cover_url || job.images.front;
    image.alt = '';
    image.loading = 'lazy';
    if (!job.cover_url) image.className = 'full-photo-cover';
    cover.append(image);
  } else {
    cover.append(el('span', label[job.status] || '等待正面试穿图'));
  }

  const title = el('strong', outfitName(job));
  const count = Object.keys(job.images).length;
  const state = job.tripo?.model_url ? '3D 已保存' :
    job.status === 'succeeded' ? count + ' 张试穿图' : (label[job.status] || job.status);
  button.append(cover, title, el('span', state, 'wardrobe-item-state'));
  return button;
}

function renderDesigns(jobs = []) {
  const displayState = JSON.stringify(jobs.map(job => [
    job.id, job.name, job.status, job.cover_url, job.images, job.tripo?.model_url
  ]));
  if (wardrobeSignature !== displayState) {
    wardrobeSignature = displayState;
    const grid = $('#designs');
    const focused = document.activeElement?.closest('.wardrobe-item')?.id;
    grid.replaceChildren(...jobs.map(wardrobeCard));
    if (focused) document.getElementById(focused)?.focus();
    if (!jobs.length) {
      grid.append(el('p', current ? '这只娃娃的衣柜还是空的，点「开始设计」做一套新衣。' :
        '先保存娃娃档案，再为它设计第一套衣服。', 'wardrobe-empty'));
    }
  }
  $('#wardrobe-title').textContent = current ? current.name + '的衣柜' : '我的娃娃衣柜';
  $('#design-summary').textContent = current ? '共 ' + jobs.length + ' 套衣服' :
    '每只娃娃都有自己的衣柜。';

  if (openedOutfitId) {
    const job = jobs.find(item => item.id === openedOutfitId);
    if (job) renderOutfit(job);
    else closeOutfit();
  }
}

function openOutfit(id) {
  const job = current?.designs.find(item => item.id === id);
  if (!job) return;
  openedOutfitId = id;
  selectedOutfitView = 'front';
  detailSignature = stageSignature = '';
  $('#outfit-dialog [data-notice]').hidden = true;
  renderOutfit(job);
  if (!$('#outfit-dialog').open) $('#outfit-dialog').showModal();
}

function clearOutfit() {
  openedOutfitId = null;
  detailSignature = stageSignature = '';
  $('#outfit-stage').replaceChildren();
  $('#outfit-details').replaceChildren();
}

function closeOutfit() {
  if ($('#outfit-dialog').open) $('#outfit-dialog').close();
  clearOutfit();
  wardrobeSignature = '';
}

$('#outfit-close').onclick = () => $('#outfit-dialog').close();
$('#outfit-dialog').addEventListener('close', () => {
  if ($('#outfit-dialog').open) return;
  const target = openedOutfitId && document.getElementById('job-' + openedOutfitId);
  clearOutfit();
  if (target) target.focus({preventScroll:true});
});

function modelViewer(job) {
  const box = el('div', undefined, 'outfit-model');
  const viewer = el('model-viewer');
  viewer.setAttribute('src', job.tripo.model_url);
  viewer.setAttribute('camera-controls', '');
  viewer.setAttribute('shadow-intensity', '1');
  viewer.setAttribute('alt', '穿着这套衣服的娃娃3D模型');
  viewer.setAttribute('camera-orbit', '0deg 75deg 110%');
  if (!window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) viewer.setAttribute('auto-rotate', '');

  const status = el('p', '正在加载3D模型…', 'muted');
  viewer.addEventListener('load', () => {status.textContent = '拖动旋转，滚轮或双指缩放。'});
  viewer.addEventListener('error', () => {
    status.textContent = '模型加载失败。可下载 GLB 后用本地软件打开。';
  });
  setTimeout(() => {
    if (viewer.isConnected && !customElements.get('model-viewer')) {
      status.textContent = '3D浏览组件未加载，请检查网络后刷新。';
    }
  }, 15000);

  const controls = el('div', undefined, 'model-actions');
  const spin = el('button', viewer.hasAttribute('auto-rotate') ? '暂停旋转' : '自动旋转', 'secondary');
  spin.onclick = () => {
    viewer.toggleAttribute('auto-rotate');
    spin.textContent = viewer.hasAttribute('auto-rotate') ? '暂停旋转' : '自动旋转';
  };
  const reset = el('button', '重置视角', 'secondary');
  reset.onclick = () => {
    viewer.cameraOrbit = '0deg 75deg 110%';
    viewer.cameraTarget = 'auto auto auto';
    viewer.jumpCameraToGoal?.();
  };
  const download = el('a', '下载 GLB');
  download.href = job.tripo.model_url;
  download.download = 'DollFit-' + job.id + '.glb';
  controls.append(spin, reset, download);
  box.append(viewer, status, controls);
  return box;
}

function generateModelPanel(job) {
  const state = job.tripo || {status: 'idle'};
  const panel = el('section', undefined, 'wardrobe-3d');
  panel.append(el('h3', '3D 展示'));
  if (state.model_url) {
    const button = el('button', '查看已保存的3D', 'primary wide');
    button.onclick = () => selectMedia(job.id, 'model');
    panel.append(button);
    return panel;
  }

  const complete = Object.keys(VIEWS).every(view => job.images[view]);
  const active = ['uploading', 'submitting', 'queued', 'running', 'downloading'].includes(state.status);
  const uncertain = state.submission_uncertain === true;
  const title = state.task_id ? '恢复查询 / 下载' : uncertain ? '恢复已提交的3D任务' : '用这4张试穿图生成3D';
  panel.append(el('p', state.message || (complete ?
    '使用这套衣服的四张试穿图生成可旋转模型。' : '正面、左侧面、背面、右侧面齐全后可生成3D。'), 'muted'));

  if (active) {
    const progress = el('progress');
    progress.max = 100;
    progress.setAttribute('aria-label', '3D生成进度');
    if (state.progress > 0) progress.value = Math.min(100, state.progress);
    panel.append(progress);
  }
  const task = el('input');
  task.className = 'restore-task';
  task.placeholder = '服务商已有任务编号';
  task.setAttribute('aria-label', '3D任务编号');
  if (uncertain) panel.append(el('p', '提交结果未知。请核对服务商记录并填写任务编号，避免重复生成。', 'error-note'), task);
  if (state.task_id) panel.append(el('p', '任务编号 ' + state.task_id, 'muted'));

  const button = el('button', active ? (label[state.status] || '正在处理') : title, 'primary wide');
  button.id = 'generate-3d-' + job.id;
  button.disabled = !complete || active;
  button.onclick = () => action(async () => {
    if (uncertain && !task.value.trim()) throw Error('请填写已有任务编号后恢复。');
    const response = await api('tripo', {job_id: job.id, task_id: uncertain ? task.value.trim() : '', preset: 'highest'});
    notify(state.task_id || uncertain ? '正在恢复已有3D任务。' : '已加入3D队列，进度会自动更新。');
    const latest = current?.designs.find(item => item.id === job.id);
    if (latest && response.status) {
      latest.tripo = response;
      renderDesigns(current.designs);
    }
    await refresh();
  });
  panel.append(button);
  return panel;
}

function selectMedia(id, view) {
  const job = current?.designs.find(item => item.id === id);
  if (!job || openedOutfitId !== id) return;
  selectedOutfitView = view;
  renderOutfit(job);
  if (view === 'model') $('#outfit-stage').scrollIntoView?.({block:'nearest'});
}

function renderOutfit(job) {
  $('#outfit-title').textContent = outfitName(job);
  $('#outfit-doll').textContent = current.name + '的衣柜';
  const stage = $('#outfit-stage');
  const isModel = selectedOutfitView === 'model' && job.tripo?.model_url;
  const view = isModel ? 'model' : (VIEWS[selectedOutfitView] ? selectedOutfitView : 'front');
  const nextStage = JSON.stringify([job.id, view, isModel || job.images[view], job.view_status[view], job.errors[view]]);

  if (stageSignature !== nextStage) {
    stageSignature = nextStage;
    if (isModel) {
      stage.replaceChildren(modelViewer(job));
    } else if (job.images[view]) {
      const photo = el('img', undefined, 'outfit-photo');
      photo.src = job.images[view];
      photo.alt = VIEWS[view] + '试穿全身图';
      const download = el('a', '下载' + VIEWS[view] + '试穿图');
      download.href = job.images[view];
      download.download = VIEWS[view] + '.png';
      stage.replaceChildren(photo, download);
    } else {
      const message = job.errors[view] || label[job.view_status[view]] || '未提供此角度的原图';
      stage.replaceChildren(el('p', VIEWS[view] + ' · ' + message, 'stage-empty'));
    }
  }

  const nextDetail = JSON.stringify([selectedOutfitView, job]);
  if (nextDetail === detailSignature) return;
  detailSignature = nextDetail;
  const details = $('#outfit-details');
  const date = job.created_at ? new Date(job.created_at * 1000).toLocaleDateString('zh-CN') : '';
  const metadata = [label[job.status], qualityNames[job.quality], date].filter(Boolean).join(' · ');
  const angles = el('div', undefined, 'outfit-angles');
  for (const [key, name] of Object.entries(VIEWS)) {
    const button = el('button');
    button.setAttribute('aria-pressed', String(!isModel && view === key));
    if (job.images[key]) {
      const image = el('img');
      image.src = job.images[key];
      image.alt = '';
      button.append(image);
    }
    button.append(el('span', name));
    button.onclick = () => selectMedia(job.id, key);
    angles.append(button);
  }
  details.replaceChildren(el('p', metadata, 'muted'), el('p', job.prompt, 'outfit-description'),
    el('h3', '试穿四视图'), angles);
  if (['partial_failure', 'failed'].includes(job.status)) {
    const retry = el('button', '重试未完成角度', 'secondary');
    retry.onclick = () => action(async () => {
      if (!window.confirm('请先核对供应商记录。重试未完成角度可能产生额外生图费用，是否继续？')) return;
      await api('retry-design', {job_id: job.id, confirmed: true});
      await refresh();
    });
    details.append(retry);
  }
  details.append(generateModelPanel(job));
}

renderDesigns([]);
