'use strict';

const qualityNames = {low: '快速', medium: '均衡', high: '精细'};
let wardrobeSignature = '';
let wardrobePage = 0;
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

const mediumWardrobe = window.matchMedia?.('(min-width: 621px)');
const wideWardrobe = window.matchMedia?.('(min-width: 961px)');
function wardrobePageSize() {
  return wideWardrobe?.matches ? 4 : mediumWardrobe?.matches ? 3 : 2;
}

function recordOutfit(job) {
  if (!current) return;
  const previousIndex = current.designs.findIndex(item => item.id === job.id);
  const designs = [...current.designs];
  if (previousIndex < 0) designs.unshift(job);
  else designs[previousIndex] = job;
  wardrobePage = Math.floor(Math.max(previousIndex, 0) / wardrobePageSize());
  current = {...current, designs};
  renderDesigns(designs);
}

function renderDesigns(jobs = []) {
  const size = wardrobePageSize();
  const pages = Math.max(1, Math.ceil(jobs.length / size));
  wardrobePage = Math.max(0, Math.min(wardrobePage, pages - 1));
  const visible = jobs.slice(wardrobePage * size, (wardrobePage + 1) * size);
  const displayState = JSON.stringify(visible.map(job => [
    job.id, job.name, job.status, job.cover_url, job.images, job.tripo?.model_url
  ]));
  if (wardrobeSignature !== displayState) {
    wardrobeSignature = displayState;
    const grid = $('#designs');
    const focused = document.activeElement?.closest('.wardrobe-item')?.id;
    grid.replaceChildren(...visible.map(wardrobeCard));
    if (focused) document.getElementById(focused)?.focus({preventScroll:true});
    if (!jobs.length) {
      grid.append(el('p', current ? '这只娃娃的衣柜还是空的，点「开始设计」做一套新衣。' :
        '先保存娃娃档案，再为它设计第一套衣服。', 'wardrobe-empty'));
    }
  }
  $('#wardrobe-title').textContent = current ? current.name + '的衣柜' : '我的娃娃衣柜';
  $('#design-summary').textContent = current ? '共 ' + jobs.length + ' 套衣服' :
    '选择或新建娃娃档案';
  $('#wardrobe-pages').hidden = pages <= 1;
  const pageLabel = (wardrobePage + 1) + ' / ' + pages;
  if ($('#wardrobe-page').textContent !== pageLabel) $('#wardrobe-page').textContent = pageLabel;
  $('#wardrobe-prev').disabled = wardrobePage === 0;
  $('#wardrobe-next').disabled = wardrobePage + 1 >= pages;

  if (openedOutfitId) {
    const job = jobs.find(item => item.id === openedOutfitId);
    if (job) renderOutfit(job);
    else closeOutfit();
  }
}

$('#wardrobe-prev').onclick = () => {wardrobePage--; renderDesigns(current?.designs)};
$('#wardrobe-next').onclick = () => {wardrobePage++; renderDesigns(current?.designs)};
for (const layout of [mediumWardrobe, wideWardrobe]) {
  layout?.addEventListener?.('change', () => renderDesigns(current?.designs));
}

function outfitPage(page) {
  selectDialogPage('outfit', page);
  $('.outfit-layout').dataset.page = page;
}

for (const button of document.querySelectorAll('[data-outfit-page]')) {
  button.onclick = () => outfitPage(button.dataset.outfitPage);
}

function openOutfit(id) {
  const job = current?.designs.find(item => item.id === id);
  if (!job) return;
  openedOutfitId = id;
  selectedOutfitView = 'front';
  outfitPage('preview');
  detailSignature = stageSignature = '';
  $('#outfit-dialog [data-notice]').hidden = true;
  renderOutfit(job);
  if (!$('#outfit-dialog').open) $('#outfit-dialog').showModal();
}

function clearOutfit() {
  openedOutfitId = null;
  detailSignature = stageSignature = '';
  clearModelPreview($('#outfit-stage'));
  $('#outfit-details').replaceChildren();
  $('#outfit-angle-picker').replaceChildren();
}

function clearModelPreview(container) {
  container.querySelector('.outfit-model')?.disposePreview?.();
  container.replaceChildren();
}

const MODEL_PART_SIZE = 4 * 1024 * 1024;
const MAX_MODEL_SIZE = 150 * 1024 * 1024;

async function readModelPart(url, start, end, signal) {
  let lastError;
  for (let attempt = 0; attempt < 3; attempt++) {
    if (signal.aborted) throw signal.reason;
    const request = new AbortController();
    const cancel = () => request.abort(signal.reason);
    signal.addEventListener('abort', cancel, {once: true});
    const timeout = setTimeout(() => request.abort(), 120000);
    try {
      const response = await fetch(url, {
        headers: {Range: 'bytes=' + start + '-' + end},
        signal: request.signal,
        cache: 'no-store',
      });
      if (response.status !== 206) {
        await response.body?.cancel();
        return {status: response.status};
      }
      const range = /^bytes (\d+)-(\d+)\/(\d+)$/.exec(response.headers.get('Content-Range') || '');
      if (!range) {
        await response.body?.cancel();
        return {status: 206};
      }
      const blob = await response.blob();
      if (blob.size !== Number(range[2]) - Number(range[1]) + 1) {
        throw Error('分段下载不完整');
      }
      return {status: 206, start: Number(range[1]), end: Number(range[2]), total: Number(range[3]),
              etag: response.headers.get('ETag'), blob};
    } catch (error) {
      if (signal.aborted) throw signal.reason;
      lastError = error;
    } finally {
      clearTimeout(timeout);
      signal.removeEventListener('abort', cancel);
    }
  }
  throw lastError;
}

async function loadModelInParts(url, signal, onProgress) {
  const parts = [];
  let offset = 0;
  let total;
  let etag;
  while (total === undefined || offset < total) {
    const end = Math.min(offset + MODEL_PART_SIZE, total ?? MODEL_PART_SIZE) - 1;
    const part = await readModelPart(url, offset, end, signal);
    if (part.status === 401 || part.status === 403) throw Error('登录状态已失效或无法访问此模型，请重新登录。');
    if (part.status === 404) throw Error('找不到模型文件。重新打开这套衣服可查看恢复选项。');
    if (part.status !== 206) throw Error('暂时无法分段读取模型（HTTP ' + part.status + '）。仍可下载 GLB。');
    if (part.start !== offset || part.total < 20 || part.total > MAX_MODEL_SIZE ||
        part.end !== Math.min(end, part.total - 1) ||
        (total !== undefined && (part.total !== total || part.etag !== etag))) {
      throw Error('模型文件在读取期间发生变化或未完整返回。请重新打开这套衣服。');
    }
    if (offset === 0) {
      const header = new DataView(await part.blob.slice(0, 20).arrayBuffer());
      if (header.byteLength < 20 || header.getUint32(0, true) !== 0x46546c67 ||
          header.getUint32(4, true) !== 2 || header.getUint32(8, true) !== part.total) {
        throw Error('服务器返回的 GLB 文件不完整或格式不正确。');
      }
      total = part.total;
      etag = part.etag;
    }
    parts.push(part.blob);
    offset = part.end + 1;
    onProgress(offset, total);
  }
  return new Blob(parts, {type: 'model/gltf-binary'});
}

async function modelLoadMessage(url) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 8000);
  try {
    const response = await fetch(url, {headers: {Range: 'bytes=0-19'}, cache: 'no-store', signal: controller.signal});
    if (response.status === 401 || response.status === 403) return '登录状态已失效或无法访问此模型。请重新登录后打开这套衣服。';
    if (response.status === 404) return '服务器上找不到这份模型文件。重新打开这套衣服，可查看原任务的恢复选项。';
    if (!response.ok) return '模型文件请求失败（HTTP ' + response.status + '）。可以重试预览。';
    if (response.status === 206) {
      const data = new DataView(await response.arrayBuffer());
      const size = Number(response.headers.get('Content-Range')?.split('/').at(-1));
      if (data.byteLength < 20 || data.getUint32(0,true) !== 0x46546c67 ||
          data.getUint32(4,true) !== 2 || (size && data.getUint32(8,true) !== size)) {
        return '服务器返回的 GLB 文件不完整或格式不正确。';
      }
    } else {
      await response.body?.cancel();
    }
    return '模型文件可以访问，但浏览器没能加载完整模型。请重试预览，或下载 GLB 在本地打开。';
  } catch {
    return '模型文件连接中断或超时。可以重试预览。';
  } finally {
    clearTimeout(timeout);
  }
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

function modelViewer(job, useParts=false) {
  const box = el('div', undefined, 'outfit-model');
  const viewer = el('model-viewer');
  const transfer = new AbortController();
  let objectUrl;
  let retryInParts = true;
  let failed = false;
  box.disposePreview = () => {
    transfer.abort();
    if (objectUrl) URL.revokeObjectURL(objectUrl);
  };
  viewer.setAttribute('camera-controls', '');
  viewer.setAttribute('touch-action', 'pan-y');
  viewer.setAttribute('shadow-intensity', '1');
  viewer.setAttribute('alt', '穿着这套衣服的娃娃3D模型');
  viewer.setAttribute('camera-orbit', '0deg 75deg 110%');
  if (job.images?.front) viewer.setAttribute('poster', job.images.front);
  if (!window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) viewer.setAttribute('auto-rotate', '');

  const status = el('p', '正在加载3D模型…', 'muted');
  status.setAttribute('role', 'status');
  setTimeout(() => {
    if (viewer.isConnected && !customElements.get('model-viewer')) {
      status.textContent = '3D浏览组件未加载，请检查网络后刷新。';
    }
  }, 15000);

  const controls = el('div', undefined, 'model-actions');
  const spin = el('button', viewer.hasAttribute('auto-rotate') ? '暂停旋转' : '自动旋转', 'secondary');
  spin.disabled = true;
  spin.onclick = () => {
    viewer.toggleAttribute('auto-rotate');
    spin.textContent = viewer.hasAttribute('auto-rotate') ? '暂停旋转' : '自动旋转';
  };
  const reset = el('button', '重置视角', 'secondary');
  reset.disabled = true;
  reset.onclick = () => {
    viewer.cameraOrbit = '0deg 75deg 110%';
    viewer.cameraTarget = 'auto auto auto';
    viewer.jumpCameraToGoal?.();
  };
  const download = el('a', '下载 GLB');
  download.href = job.tripo.model_url;
  download.download = 'DollFit-' + job.id + '.glb';
  const retry = el('button', '重试预览', 'secondary');
  retry.hidden = true;
  retry.onclick = () => {
    box.disposePreview();
    box.replaceWith(modelViewer(job, retryInParts));
  };
  viewer.addEventListener('progress', event => {
    const progress = event.detail?.totalProgress;
    if (!useParts && !failed && !viewer.loaded && progress > 0 && progress < 1) {
      status.textContent = '正在加载3D模型… ' + Math.floor(progress * 100) + '%';
    }
  });
  viewer.addEventListener('load', () => {
    status.textContent = '拖动旋转，滚轮或双指缩放。';
    spin.disabled = reset.disabled = false;
    retry.hidden = true;
  });
  viewer.addEventListener('error', async event => {
    failed = true;
    spin.disabled = reset.disabled = true;
    retry.hidden = false;
    if (event.detail?.type === 'webglcontextlost') {
      retryInParts = false;
      status.textContent = '浏览器的3D渲染已中断。请关闭同一浏览器里的其他3D页面后重试。';
      return;
    }
    if (useParts && objectUrl) {
      status.textContent = '完整模型已下载，但浏览器没能解析或渲染。可以下载 GLB 在本地打开。';
      return;
    }
    status.textContent = '模型未能显示，正在检查文件…';
    const message = await modelLoadMessage(job.tripo.model_url);
    if (box.isConnected && !viewer.loaded) status.textContent = message;
  });
  controls.append(spin, reset, retry, download);
  box.append(viewer, status, controls);
  if (useParts) {
    status.textContent = '正在分段读取已保存的模型…';
    loadModelInParts(job.tripo.model_url, transfer.signal, (received,total) => {
      status.textContent = '正在分段读取模型… ' + Math.floor(received / total * 100) + '%';
    }).then(blob => {
      if (transfer.signal.aborted || !box.isConnected) return;
      objectUrl = URL.createObjectURL(blob);
      status.textContent = '文件已下载，正在准备3D画面…';
      viewer.setAttribute('src', objectUrl);
    }).catch(error => {
      if (transfer.signal.aborted || !box.isConnected) return;
      status.textContent = error.name === 'AbortError' || error instanceof TypeError ?
        '模型分段读取中断。可以重试预览，或下载 GLB。' : error.message;
      retry.hidden = false;
    });
  } else {
    viewer.setAttribute('src', job.tripo.model_url);
  }
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

  let faceCount;
  if (complete && !active && !uncertain && !state.task_id && state.provider !== 'official' && tripoFaceCounts.length) {
    const field = el('label', '3D 画质');
    faceCount = el('select');
    faceCount.setAttribute('aria-label', '3D 画质');
    const captions = {500000:'快速', 1000000:'均衡', 1500000:'精细'};
    for (const value of tripoFaceCounts) {
      const option = el('option', captions[value]);
      option.value = value;
      faceCount.append(option);
    }
    faceCount.value = state.requested_face_count || Math.max(...tripoFaceCounts);
    field.append(faceCount);
    panel.append(field);
  }

  const button = el('button', active ? (label[state.status] || '正在处理') : title, 'primary wide');
  button.id = 'generate-3d-' + job.id;
  button.disabled = !complete || active;
  button.onclick = () => action(async () => {
    if (uncertain && !task.value.trim()) throw Error('请填写已有任务编号后恢复。');
    const request = {job_id: job.id, task_id: uncertain ? task.value.trim() : '', preset: 'highest'};
    if (faceCount) request.face_count = Number(faceCount.value);
    const response = await api('tripo', request);
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
  outfitPage('preview');
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
    clearModelPreview(stage);
    if (isModel) {
      stage.append(modelViewer(job));
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
  angles.setAttribute('role', 'group');
  angles.setAttribute('aria-label', '试穿四视图');
  $('#outfit-angle-picker').replaceChildren(angles);
  details.replaceChildren(el('p', metadata, 'muted'), el('p', job.prompt, 'outfit-description'));
  if (job.prompt.length > 52) {
    const description = el('a', '下载完整描述', 'outfit-description-download');
    description.href = 'data:text/plain;charset=utf-8,' + encodeURIComponent(job.prompt);
    description.download = 'dollfit-design.txt';
    details.append(description);
  }
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
