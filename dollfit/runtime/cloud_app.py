"""DollFit cloud workbench: same-origin UI, owned records, bounded jobs, no browser secrets."""
import base64
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
import hashlib
import hmac
import io
import json
import math
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time
from urllib.parse import urlsplit
import uuid

from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, JSONResponse, Response
from PIL import Image, ImageOps

from . import auth, tripo_api as tripo, wardrobe_jobs as wardrobe
from . import tripo_inputs
from .wardrobe_settings import APP_ROOT, ROOT, redact

PROFILES = ROOT / 'profiles'
PROFILES.mkdir(exist_ok=True)
LOCK = threading.RLock()
ACTIVE = set()
EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix='dollfit-job')
VIEWS = wardrobe.VIEWS
EXAMPLE = 'bd0228c40529495eaa48e3f614002e64'
SECURE_COOKIE = bool(os.environ.get('RENDER')) or os.environ.get('APP_URL', '').startswith('https://')
COOKIE = 'dollfit_session'
VERSION = '2026.11.19-model-preview'
MEASUREMENT_INPUTS = ('project_id', 'height_cm', 'gender')


def fail(message, status=400):
    return JSONResponse({'error': redact(message)}, status_code=status)


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r'[a-f0-9]{32}', value):
        raise ValueError('记录编号无效。')
    return value


def read_profile(pid, user):
    path = PROFILES / identifier(pid) / 'profile.json'
    profile = wardrobe.read_json(path)
    if profile.get('owner_id') != user['id']:
        raise FileNotFoundError()
    return profile


def write_profile(profile):
    wardrobe.write_json(PROFILES / profile['id'] / 'profile.json', profile)


def read_job(jid, user):
    job = wardrobe.read_job(identifier(jid))
    if job.get('owner_id') != user['id']:
        raise FileNotFoundError()
    return job


def job_view(job):
    jid = job['id']
    path = wardrobe.job_path(jid) / 'tripo.json'
    state = wardrobe.read_json(path) if path.exists() else {'status': 'idle'}
    safe = ('status', 'progress', 'task_id', 'message', 'model_url', 'preset', 'provider', 'face_count', 'requested_face_count',
            'actual_model_version', 'stage', 'input_source', 'error_kind')
    safe_state = {k: state[k] for k in safe if k in state}
    safe_state['submission_uncertain'] = bool(state.get('submission_started') and not state.get('task_id'))
    safe_state['uploaded_views'] = len(state.get('tokens', {}))
    if safe_state.get('model_url') and not path.with_name('tripo_model.glb').is_file():
        safe_state.pop('model_url')
        safe_state.update(status='needs_attention', message='已保存的模型文件找不到。可用原任务编号重新取回。')
    return {'id': jid, 'status': job['status'], 'prompt': job['user_prompt'], 'view_status': job['view_status'],
            'name': job.get('outfit_name', ''), 'quality': job.get('quality', 'high'),
            'created_at': job.get('created_at'),
            'cover_url': f'/media/design/{jid}/wardrobe_cover.jpg' if path.with_name('wardrobe_cover.jpg').is_file() else None,
            'errors': job['errors'], 'images': {v: f'/media/design/{jid}/{v}_dressed.png' for v in job['results']},
            'tripo': safe_state}


def profile_view(profile, user):
    output = dict(profile)
    output.pop('owner_id', None)
    output['photos'] = {v: f'/media/original/{profile["project_id"]}/{v}.png' for v in profile['views']}
    output['designs'] = [job_view(read_job(jid, user)) for jid in reversed(profile['jobs'])]
    return output


def example_view():
    return {'id': EXAMPLE, 'status': 'succeeded', 'prompt': '森系开衫与百褶裙 · 最高质量展示实例', 'errors': {},
            'view_status': {v: 'succeeded' for v in VIEWS},
            'images': {v: f'/media/example/{v}_dressed.png' for v in VIEWS},
            'tripo': {'status': 'succeeded', 'progress': 100, 'is_example': True, 'face_count': 1500000,
                      'actual_model_version': 'v3.0-20250812', 'preset': 'highest',
                      'message': '已实测生成的150万面PBR实例，可直接在当前页面旋转浏览。',
                      'model_url': '/media/example/model.glb'}}


def image(value):
    if not isinstance(value, str) or not value.startswith('data:image/') or len(value) > 14 * 1024 * 1024:
        raise ValueError('请上传10MB以内的PNG、JPEG或WebP照片。')
    try:
        raw = base64.b64decode(value.split(',', 1)[1], validate=True)
        if len(raw) > 10 * 1024 * 1024:
            raise ValueError()
        with Image.open(io.BytesIO(raw)) as source:
            if source.format not in ('PNG', 'JPEG', 'WEBP') or source.width * source.height > 12_000_000:
                raise ValueError()
            source.load()
            result = ImageOps.exif_transpose(source).convert('RGBA')
            result.thumbnail((2000, 2000))
            return result
    except Exception:
        raise ValueError('图片无法读取或分辨率超过1200万像素，请缩小后上传。') from None


def queue(key, callback):
    with LOCK:
        if key in ACTIVE:
            return False
        if len(ACTIVE) >= 20:
            raise ValueError('当前排队任务较多，请稍后再试。')
        ACTIVE.add(key)
    def work():
        try:
            callback()
        finally:
            with LOCK:
                ACTIVE.discard(key)
    try:
        EXECUTOR.submit(work)
    except Exception:
        ACTIVE.discard(key)
        raise
    return True


def measure(pid, owner):
    user = {'id': owner}
    profile = read_profile(pid, user)
    destination = PROFILES / pid
    config = {'front': str(wardrobe.PROJECTS / profile['project_id'] / 'front.png'),
              'side': str(wardrobe.PROJECTS / profile['project_id'] / 'left.png'),
              'height_cm': profile['height_cm'], 'gender': profile['gender']}
    source = destination / 'inference_input.json'
    output = destination / 'inference_output.json'
    wardrobe.write_json(source, config)
    try:
        # Provider tokens and account secrets are not needed by a neural inference child.
        environment = dict(os.environ)
        for key in ('HEJU_API_KEY', 'TRIPO_API_KEY', 'APP_SECRET', 'INVITE_CODE', 'ADMIN_PASSWORD'):
            environment.pop(key, None)
        process = subprocess.run([sys.executable, '-m', 'runtime.cloud_measure', str(source), str(output)],
                                 cwd=APP_ROOT, env=environment, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=240)
        if process.returncode:
            detail = process.stderr.strip().splitlines()[-1] if process.stderr.strip() else '推理进程未正常结束。'
            raise ValueError('尺寸预测未完成：' + detail + ' 免费实例可能内存不足，请升级后再试。')
        result = wardrobe.read_json(output)
    except Exception as error:
        result = {'status': 'failed', 'error': redact(error)}
    finally:
        source.unlink(missing_ok=True)
    with LOCK:
        latest = read_profile(pid, user)
        if all(latest[key] == profile[key] for key in MEASUREMENT_INPUTS):
            latest['measurement'] = result
            write_profile(latest)


def run_tripo(jid):
    path = wardrobe.job_path(jid) / 'tripo.json'
    state = wardrobe.read_json(path)
    provider = state['provider']
    def save(**values):
        state.update(values)
        wardrobe.write_json(path, state)
    try:
        job = wardrobe.read_job(jid)
        if not state.get('task_id'):
            if state.get('submission_started'):
                raise ValueError('上次提交结果不确定，请先核对服务商记录并填写任务编号恢复，避免重复扣费。')
            source = tripo_inputs.mode(provider)
            if source == 'signed_links':
                save(status='uploading', stage='prepare_inputs', input_source=source, message='为本次正、左、背、右试穿图准备短期访问链接')
                for view in VIEWS:
                    if not (wardrobe.job_path(jid) / job['results'][view]['file']).is_file():
                        raise ValueError('本次设计的' + VIEWS[view] + '试穿图文件缺失，请导入已保存四视图。')
                uploaded = {view: tripo_inputs.create(jid, view) for view in VIEWS}
                save(tokens=uploaded, uploaded_at=time.time())
            else:
                uploaded = state.get('tokens', {}) if state.get('input_source', 'upload') == 'upload' else {}
                if provider == 'seller' and time.time() - state.get('uploaded_at', 0) > 25 * 60:
                    uploaded = {}
                for view in VIEWS:
                    if view not in uploaded:
                        save(status='uploading', stage='upload', input_source=source, message='上传' + VIEWS[view] + '试穿图（' + str(len(uploaded)) + '/4）')
                        uploaded[view] = tripo.upload(wardrobe.job_path(jid) / job['results'][view]['file'], provider)
                        save(tokens=uploaded, uploaded_at=time.time())
            face_option = {'face_count': state['requested_face_count']} if provider == 'seller' and 'requested_face_count' in state else {}
            save(status='submitting', stage='submit', submission_started=True, message='四张试穿图已准备好，正在提交3D任务。')
            task_id = tripo.create(uploaded, 'highest', provider, **face_option)
            save(task_id=task_id, status='queued', stage='query')
        deadline = time.monotonic() + 1800
        save(stage='query')
        errors = 0
        while time.monotonic() < deadline:
            try:
                remote = tripo.query(state['task_id'], provider)
                errors = 0
            except Exception:
                errors += 1
                if errors >= 5:
                    raise ValueError('任务查询暂时不可用，编号已保存，可恢复查询。')
                time.sleep(8)
                continue
            status = remote.get('status', 'unknown')
            save(status=status, progress=remote.get('progress', 0), message='正在生成3D模型',
                 face_count=remote.get('face_count'), actual_model_version=remote.get('actual_model_version'))
            if status == 'success':
                url = remote.get('output', {}).get('model_url')
                if not url:
                    raise ValueError('任务已完成但未返回模型地址。')
                save(status='downloading', stage='download', message='任务成功，正在保存带贴图模型')
                tripo.download(url, wardrobe.job_path(jid) / 'tripo_model.glb')
                save(status='succeeded', progress=100, model_url=f'/media/design/{jid}/tripo_model.glb', message='模型已完成，可在当前页面旋转浏览。')
                return
            if status in ('failed', 'cancelled', 'banned', 'expired'):
                raise ValueError('3D任务已结束：' + str(remote.get('error_message') or status))
            time.sleep(6)
        raise ValueError('查询达到30分钟上限，任务编号已保存，可继续恢复查询。')
    except Exception as error:
        stage = state.get('stage', 'prepare_inputs')
        if stage == 'submit' and isinstance(error, tripo.seller.ProviderRejected):
            state['submission_started'] = False
        if stage == 'download':
            message = '模型下载暂时中断，任务编号已保存。点击恢复下载，无需重新生成。'
        else:
            message = tripo.safe_error(error)
        save(status='needs_attention', message=message, stage=stage, error_kind=type(error).__name__)
        print(json.dumps({'event': 'tripo_needs_attention', 'job': jid, 'stage': stage,
                          'error_kind': type(error).__name__, 'has_task_id': bool(state.get('task_id'))}), flush=True)


def run_design(jid):
    try:
        wardrobe.run(jid)
        job = wardrobe.read_job(jid)
        auto = wardrobe.job_path(jid) / 'tripo.json'
        if set(job['results']) == set(VIEWS) and auto.exists() and wardrobe.read_json(auto).get('auto_requested'):
            run_tripo(jid)
    except Exception as error:
        job = wardrobe.read_job(jid)
        job['status'] = 'partial_failure' if job['results'] else 'failed'
        for view in job['views']:
            if view not in job['results']:
                job['view_status'][view] = 'failed'
                job['errors'][view] = redact(error)
        wardrobe.write_json(wardrobe.job_path(jid) / 'job.json', job)
    finally:
        wardrobe.RUNNING.discard(jid)


def startup():
    auth.init()
    for path in wardrobe.JOBS.glob('*/job.json'):
        job = wardrobe.read_json(path)
        if job.get('status') in ('queued', 'running'):
            job['status'] = 'partial_failure' if job['results'] else 'failed'
            for view in job['views']:
                if view not in job['results']:
                    job['view_status'][view] = 'failed'
                    job['errors'][view] = '服务曾重启，未自动重复生图。请核对供应商记录后手动重试。'
            wardrobe.write_json(path, job)
            (path.parent / 'worker.lock').unlink(missing_ok=True)
        state_path = path.parent / 'tripo.json'
        if state_path.exists():
            state = wardrobe.read_json(state_path)
            if state.get('task_id') and state.get('status') not in ('succeeded', 'failed', 'cancelled', 'expired', 'banned'):
                queue('tripo:' + job['id'], lambda jid=job['id']: run_tripo(jid))
            elif state.get('status') != 'succeeded' and not state.get('task_id'):
                state.update(status='needs_attention', message='服务曾重启，请核对供应商记录后继续；未自动创建付费任务。')
                wardrobe.write_json(state_path, state)
    for path in PROFILES.glob('*/profile.json'):
        profile = wardrobe.read_json(path)
        if profile.get('measurement', {}).get('status') == 'running':
            profile['measurement'] = {'status': 'failed', 'error': '服务曾重启，请重新预测。'}
            write_profile(profile)


@asynccontextmanager
async def lifespan(app):
    startup()
    yield


app = FastAPI(title='DollFit', docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)


@app.middleware('http')
async def security(request, call_next):
    if request.method == 'POST':
        origin = request.headers.get('origin')
        allowed = {os.environ.get('APP_URL', '').rstrip('/'), os.environ.get('RENDER_EXTERNAL_URL', '').rstrip('/')}
        same_host = origin and urlsplit(origin).netloc == request.headers.get('host')
        if origin and not same_host and origin.rstrip('/') not in allowed:
            return fail('不允许跨站调用。', 403)
        try:
            if int(request.headers.get('content-length', '0')) > 32 * 1024 * 1024:
                return fail('单次上传不能超过32MB，请缩小照片。', 413)
        except ValueError:
            return fail('请求长度无效。')
    response = await call_next(request)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    # The homepage opens the real workbench in a same-origin dialog.
    if request.url.path == '/workbench.html':
        response.headers['X-Frame-Options'] = 'SAMEORIGIN'
        response.headers['Content-Security-Policy'] = "frame-ancestors 'self'"
    else:
        response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Referrer-Policy'] = 'same-origin'
    if request.url.path.startswith(('/api/', '/media/original/', '/media/design/')):
        if 'Cache-Control' not in response.headers or response.status_code not in (200, 206, 304):
            response.headers['Cache-Control'] = 'no-store'
    return response


@app.get('/healthz')
def health():
    return {'status': 'ok', 'version': VERSION, 'measurement_model': (APP_ROOT / 'models/bodym.onnx').is_file()}


@app.get('/api/bootstrap')
def bootstrap(request: Request):
    session = request.cookies.get(COOKIE, '')
    user = auth.user(session)
    guest = auth.guest(request.cookies.get('dollfit_guest'))
    profiles = []
    if user:
        for path in PROFILES.glob('*/profile.json'):
            record = wardrobe.read_json(path)
            if record.get('owner_id') == user['id']:
                profiles.append({'id': record['id'], 'name': record['name'], 'created_at': record['created_at']})
    is_ephemeral = str(ROOT).replace('\\', '/').startswith('/tmp/') or os.environ.get('DATA_EPHEMERAL') == 'true'
    response = JSONResponse({'token': auth.csrf(session if user else guest), 'user': user,
        'profiles': sorted(profiles, key=lambda p: p['created_at'], reverse=True),
        'image_configured': bool(os.environ.get('HEJU_API_KEY')), 'tripo_configured': tripo.configured(),
        'tripo_base': tripo.base_url(), 'tripo_provider': tripo.provider_name(), 'quality': 'highest',
        'tripo_face_counts': tripo.seller.FACE_COUNTS if tripo.provider_name() == 'seller' else [],
        'quality_label': '最高质量 · 150万面' if tripo.provider_name() == 'seller' else '最高质量 · 官方超清档',
        'ephemeral_storage': is_ephemeral, 'invitation_required': True, 'cloud': True, 'version': VERSION})
    if request.cookies.get('dollfit_guest') != guest:
        response.set_cookie('dollfit_guest', guest, httponly=True, secure=SECURE_COOKIE, samesite='lax', max_age=14 * 86400)
    return response


@app.get('/api/example')
def example():
    return example_view()


@app.get('/api/profile/{pid}')
def get_profile(pid: str, request: Request):
    user = auth.user(request.cookies.get(COOKIE))
    if not user:
        return fail('请先登录。', 401)
    try:
        return profile_view(read_profile(pid, user), user)
    except (ValueError, FileNotFoundError, KeyError):
        return fail('档案不存在。', 404)


@app.get('/api/job/{jid}')
def get_job(jid: str, request: Request):
    user = auth.user(request.cookies.get(COOKIE))
    if not user:
        return fail('请先登录。', 401)
    try:
        return job_view(read_job(jid, user))
    except (ValueError, FileNotFoundError):
        return fail('设计不存在。', 404)


def post(path, body, user, request_id):
    with LOCK:
        if path == 'settings':
            raise ValueError('云端密钥只允许管理员在 Render Environment 中配置，网页不会保存或回显密钥。')
        if path == 'test-tripo':
            if not user['admin']:
                return fail('仅管理员可以测试服务连接。', 403)
            result = tripo.preflight(require_balance=False)
            result['input_source'] = tripo_inputs.mode(tripo.provider_name())
            if body.get('probe_upload'):
                before = result.get('usage_count')
                tripo.upload(APP_ROOT / 'examples/front_dressed.png', tripo.provider_name())
                after = tripo.preflight(require_balance=False)
                result['upload_probe'] = {'passed': True, 'generation_created': False,
                                          'usage_before': before, 'usage_after': after.get('usage_count')}
            return result
        if path == 'profile':
            height = float(body.get('height_cm', 0))
            if not math.isfinite(height) or not 0 < height <= 300 or body.get('gender') not in ('female', 'male'):
                raise ValueError('请填写有效身高和模型性别分类。')
            editing = body.get('profile_id')
            source = editing or body.get('source_id')
            previous = read_profile(source, user) if source else None
            if not editing and sum(1 for x in PROFILES.glob('*/profile.json') if wardrobe.read_json(x).get('owner_id') == user['id']) >= 50:
                raise ValueError('每个账户最多保存50份档案。')
            pictures = {view: image(value) for view, value in body.get('views', {}).items() if view in VIEWS and value}
            if previous and not pictures:
                project_id, views = previous['project_id'], previous['views']
            else:
                if previous:
                    for view in previous['views']:
                        if view not in pictures:
                            with Image.open(wardrobe.PROJECTS / previous['project_id'] / (view + '.png')) as original:
                                pictures[view] = original.copy()
                project = wardrobe.ensure_project(pictures, user['id'])
                project['owner_id'] = user['id']
                project_id, views = project['id'], project['views']
                wardrobe.write_json(wardrobe.PROJECTS / project_id / 'project.json', project)
            profile = dict(previous) if editing else {
                'id': uuid.uuid4().hex, 'owner_id': user['id'], 'created_at': time.time(),
                'jobs': [], 'measurement': {'status': 'idle'},
            }
            profile.update(name=str(body.get('name', '我的娃娃')).strip()[:40] or '我的娃娃',
                           height_cm=height, gender=body['gender'], notes=str(body.get('notes', ''))[:1000],
                           project_id=project_id, views=views)
            if editing and any(profile[key] != previous[key] for key in MEASUREMENT_INPUTS):
                profile['measurement'] = {'status': 'idle'}
            write_profile(profile)
            return profile_view(profile, user)
        if path == 'measure':
            profile = read_profile(body.get('profile_id'), user)
            if queue('measure:' + profile['id'], lambda: measure(profile['id'], user['id'])):
                profile['measurement'] = {'status': 'running'}
                write_profile(profile)
            return {'started': True}
        if path == 'import-design':
            profile = read_profile(body.get('profile_id'), user)
            if len(profile['jobs']) >= 50:
                raise ValueError('每份档案最多保存50条设计，请先保存所需结果。')
            supplied = body.get('views', {})
            if not isinstance(supplied, dict) or set(supplied) != set(VIEWS):
                raise ValueError('请为正面、左侧面、背面、右侧面分别提供一张已完成的试穿图。')
            pictures = {view: image(supplied[view]) for view in VIEWS}
            digests = [hashlib.sha256(wardrobe.png_bytes(pictures[view])).hexdigest() for view in VIEWS]
            if len(set(digests)) != 4:
                raise ValueError('四个角度不能使用同一张图片。')
            jid = hashlib.sha256((user['id'] + profile['id'] + ''.join(digests)).encode()).hexdigest()[:32]
            if (wardrobe.job_path(jid) / 'job.json').exists():
                return job_view(read_job(jid, user))
            folder = wardrobe.job_path(jid);folder.mkdir(parents=True)
            for view in VIEWS:pictures[view].save(folder / (view + '_dressed.png'))
            try:
                wardrobe.save_cover(folder / 'front_dressed.png')
            except OSError:
                pass  # Imported full-size images are still available as the cover fallback.
            prompt = '导入已有服装四视图，可直接用于3D生成'
            job = {'id': jid, 'project_id': profile['project_id'], 'owner_id': user['id'], 'views': list(VIEWS),
                   'status': 'succeeded', 'user_prompt': prompt, 'instructions': [prompt], 'created_at': time.time(),
                   'quality': 'imported-original', 'size': 'original', 'height_cm': profile['height_cm'],
                   'view_status': {view: 'succeeded' for view in VIEWS}, 'errors': {}, 'garment_references': [],
                   'results': {view: {'file': view + '_dressed.png'} for view in VIEWS},
                   'view_directions': {'left': 'left', 'right': 'right'}, 'imported': True}
            wardrobe.write_json(folder / 'job.json', job)
            project = wardrobe.read_json(wardrobe.PROJECTS / profile['project_id'] / 'project.json')
            project['jobs'].append(jid);wardrobe.write_json(wardrobe.PROJECTS / profile['project_id'] / 'project.json', project)
            profile['jobs'].append(jid);write_profile(profile)
            return job_view(job)
        if path == 'design':
            previous = auth.receipt(user['id'], 'design', request_id)
            if previous:
                return job_view(read_job(previous, user))
            profile = read_profile(body.get('profile_id'), user)
            if not os.environ.get('HEJU_API_KEY'):
                raise ValueError('管理员尚未配置生图接口。')
            if len(ACTIVE) >= 20:
                raise ValueError('任务队列已满，请稍后再试。')
            auto = bool(body.get('auto_3d'))
            if auto and set(profile['views']) != set(VIEWS):
                raise ValueError('自动3D需要四个角度原图。')
            if auto:
                tripo.preflight()
            quality = body.get('quality', 'high')
            if quality not in wardrobe.IMAGE_QUALITIES:
                raise ValueError('请选择快速、均衡或精细画质。')
            outfit_name = body.get('outfit_name', '')
            if not isinstance(outfit_name, str) or len(outfit_name.strip()) > 60:
                raise ValueError('衣服名字最多60字。')
            references = body.get('references', [])
            if not isinstance(references, list) or len(references) > 3:
                raise ValueError('最多提供3张服装参考图。')
            references = [image(value) for value in references]
            job = wardrobe.create_job(profile['project_id'], str(body.get('prompt', '')), profile['height_cm'],
                                      quality, '1024x1536', references,
                                      new_outfit=body.get('new_outfit') is True, outfit_name=outfit_name.strip())
            jid = job['id']
            reservations = [('design', request_id, jid)]
            if auto:
                reservations.append(('3d', request_id + '_auto', jid))
            try:
                auth.reserve_many(user['id'], reservations)
            except Exception:
                project = wardrobe.read_json(wardrobe.PROJECTS / job['project_id'] / 'project.json')
                project['jobs'].remove(jid)
                wardrobe.write_json(wardrobe.PROJECTS / job['project_id'] / 'project.json', project)
                # jid is generated by create_job, validated, and resides only under the cloud DATA_DIR.
                cleanup = wardrobe.job_path(identifier(jid)).resolve()
                if not cleanup.is_relative_to(wardrobe.JOBS.resolve()):
                    raise RuntimeError('Invalid job cleanup path')
                shutil.rmtree(cleanup)
                raise
            job['owner_id'] = user['id']
            wardrobe.write_json(wardrobe.job_path(jid) / 'job.json', job)
            profile['jobs'].append(jid)
            write_profile(profile)
            if auto:
                wardrobe.write_json(wardrobe.job_path(jid) / 'tripo.json', {'status': 'queued', 'preset': 'highest',
                    'provider': tripo.provider_name(), 'auto_requested': True, 'quota_reserved': True, 'progress': 0,
                    'message': '四视图完成后自动生成最高质量3D。'})
            wardrobe.RUNNING.add(jid)
            queue('design:' + jid, lambda: run_design(jid))
            return job_view(job)
        if path == 'retry-design':
            job = read_job(body.get('job_id'), user)
            jid = job['id']
            if jid in wardrobe.RUNNING:
                return job_view(job)
            if body.get('confirmed') is not True:
                raise ValueError('请先核对供应商记录，确认重试可能产生额外费用。')
            if len(ACTIVE) >= 20:
                raise ValueError('任务队列已满，请稍后再试。')
            previous = auth.receipt(user['id'], 'design', request_id)
            if previous:
                return job_view(job)
            auth.reserve(user['id'], 'design', request_id, jid)
            (wardrobe.job_path(jid) / 'worker.lock').unlink(missing_ok=True)
            job['status'] = 'queued'
            wardrobe.write_json(wardrobe.job_path(jid) / 'job.json', job)
            wardrobe.RUNNING.add(jid)
            queue('design:' + jid, lambda: run_design(jid))
            return job_view(job)
        if path == 'tripo':
            job = read_job(body.get('job_id'), user)
            jid = job['id']
            if set(job['results']) != set(VIEWS):
                raise ValueError('生成3D需要四张同款服装试穿图。')
            state_path = wardrobe.job_path(jid) / 'tripo.json'
            state = wardrobe.read_json(state_path) if state_path.exists() else {'preset': 'highest', 'provider': tripo.provider_name(), 'progress': 0}
            model_saved = state.get('status') == 'succeeded' and state_path.with_name('tripo_model.glb').is_file()
            if model_saved or 'tripo:' + jid in ACTIVE or 'design:' + jid in ACTIVE:
                return job_view(job)['tripo']
            if len(ACTIVE) >= 20:
                raise ValueError('任务队列已满，请稍后再试。')
            if body.get('task_id'):
                # Do not accept another customer's task identifier: only the owner/admin may recover an uncertain own submission.
                if not state.get('submission_started'):
                    raise ValueError('此设计没有待恢复的提交记录，不能导入其他任务。')
                task_id = str(body['task_id']).strip()
                if not state.get('task_id') and not user['admin']:
                    if state['provider'] != 'seller':
                        raise ValueError('请联系管理员核对服务商记录并恢复编号；未重新创建付费任务。')
                    tripo.seller.verify_own_task(task_id, state.get('tokens', {}))
                if state.get('task_id') and task_id != state['task_id']:
                    raise ValueError('任务编号与本设计已保存的编号不一致。')
                tripo.query(task_id, state['provider'])
                state['task_id'] = task_id
            if not state.get('task_id'):
                if state.get('submission_started'):
                    raise ValueError('提交结果不确定，请从服务商记录找回任务编号，避免重复扣费。')
                if state['provider'] == 'seller':
                    previous_count = state.get('requested_face_count', tripo.seller.MAX_FACE_COUNT)
                    state['requested_face_count'] = tripo.seller.validate_face_count(body.get('face_count', previous_count))
                elif 'face_count' in body:
                    raise ValueError('当前3D接口没有开启面数选择。')
                tripo.preflight()
                if not state.get('quota_reserved'):
                    auth.reserve(user['id'], '3d', request_id, jid)
                    state['quota_reserved'] = True
            state.update(status='queued', preset='highest', auto_requested=False)
            if not model_saved:
                state.pop('model_url', None)
            wardrobe.write_json(state_path, state)
            queue('tripo:' + jid, lambda: run_tripo(jid))
            return job_view(job)['tripo']
        raise ValueError('接口不存在。')


@app.post('/api/{path:path}')
async def api_post(path: str, request: Request):
    try:
        buffer = bytearray()
        async for chunk in request.stream():
            if len(buffer) + len(chunk) > 32 * 1024 * 1024:
                return fail('单次上传不能超过32MB，请缩小照片。', 413)
            buffer.extend(chunk)
        body = json.loads(buffer)
        if not isinstance(body, dict):
            raise ValueError('请求内容无效。')
        session = request.cookies.get(COOKIE, '')
        user = auth.user(session)
        guest = auth.guest(request.cookies.get('dollfit_guest'))
        expected = auth.csrf(session if user else guest)
        if not hmac.compare_digest(request.headers.get('X-DollFit-Token', ''), expected):
            return fail('页面验证已失效，请刷新后重试。', 403)
        if path in ('auth/login', 'auth/register'):
            auth.rate_limit(request.client.host if request.client else 'unknown')
            name, password = body.get('username', ''), body.get('password', '')
            if not isinstance(name, str) or not isinstance(password, str) or len(password) > 128:
                raise ValueError('用户名或密码无效。')
            if path == 'auth/register':
                user = await run_in_threadpool(auth.register, name, password, str(body.get('invite_code', '')))
            else:
                user = await run_in_threadpool(auth.login, name, password)
            response = JSONResponse({'user': user})
            response.set_cookie(COOKIE, auth.new_session(user), httponly=True, secure=SECURE_COOKIE, samesite='lax', max_age=14 * 86400)
            return response
        if not user:
            return fail('请先登录后保存档案或生成设计。', 401)
        if path == 'auth/logout':
            auth.logout(session)
            response = JSONResponse({'logged_out': True})
            response.delete_cookie(COOKIE, secure=SECURE_COOKIE, httponly=True, samesite='lax')
            return response
        request_id = request.headers.get('Idempotency-Key', '')
        if path in ('design', 'tripo', 'retry-design') and not re.fullmatch(r'[A-Za-z0-9_-]{8,80}', request_id):
            raise ValueError('请求编号缺失，请刷新后重试。')
        return await run_in_threadpool(post, path, body, user, request_id)
    except (FileNotFoundError, KeyError):
        return fail('记录不存在。', 404)
    except Exception as error:
        return fail(error)


@app.get('/media/example/{name}')
def example_file(name: str):
    if name not in ['model.glb'] + [v + '_dressed.png' for v in VIEWS]:
        return fail('文件不存在。', 404)
    return FileResponse(APP_ROOT / 'examples' / name, media_type='model/gltf-binary' if name.endswith('.glb') else 'image/png',
                        headers={'Cache-Control': 'public, max-age=86400'})


@app.get('/tripo-input/{jid}/{view}.png')
def provider_input(jid: str, view: str, request: Request):
    if not tripo_inputs.valid(jid, view, request.query_params.get('expires'), request.query_params.get('signature', '')):
        return fail('图片链接无效或已过期。', 403)
    try:
        job = wardrobe.read_job(identifier(jid))
        if view not in job.get('results', {}):raise FileNotFoundError()
        file = wardrobe.job_path(jid) / (view + '_dressed.png')
        if not file.is_file():raise FileNotFoundError()
        return FileResponse(file, media_type='image/png', headers={'Cache-Control': 'private, no-store'})
    except (ValueError, FileNotFoundError):
        return fail('试穿图不存在。', 404)


@app.get('/media/{kind}/{record}/{name}')
def media_file(kind: str, record: str, name: str, request: Request):
    user = auth.user(request.cookies.get(COOKIE))
    if not user:
        return fail('请先登录。', 401)
    try:
        identifier(record)
        if kind == 'design':
            read_job(record, user)
            if name not in [v + '_dressed.png' for v in VIEWS] + ['tripo_model.glb', 'wardrobe_cover.jpg']:
                raise FileNotFoundError()
            file = wardrobe.job_path(record) / name
        elif kind == 'original':
            project = wardrobe.read_json(wardrobe.PROJECTS / record / 'project.json')
            if project.get('owner_id') != user['id'] or name not in [v + '.png' for v in VIEWS]:
                raise FileNotFoundError()
            file = wardrobe.PROJECTS / record / name
        else:
            raise FileNotFoundError()
        if not file.is_file():
            raise FileNotFoundError()
        media_type = {'.glb': 'model/gltf-binary', '.jpg': 'image/jpeg'}.get(file.suffix, 'image/png')
        if kind == 'design':
            # Every cache revalidation goes through the account and job ownership checks above.
            stat = file.stat()
            headers = {'Cache-Control': 'private, no-cache, must-revalidate', 'Vary': 'Cookie'}
            if file.suffix == '.glb':
                headers['X-File-Size'] = str(stat.st_size)
            file_response = FileResponse(file, media_type=media_type, stat_result=stat, headers=headers)
            cached_tags = request.headers.get('If-None-Match', '').split(',')
            if any(tag.strip().removeprefix('W/') in ('*', file_response.headers['etag']) for tag in cached_tags):
                return Response(status_code=304, headers={key: file_response.headers[key]
                    for key in ('ETag', 'Cache-Control', 'Vary')})
            return file_response
        return FileResponse(file, media_type=media_type)
    except (ValueError, FileNotFoundError):
        return fail('文件不存在。', 404)


@app.get('/{path:path}')
def static_file(path: str):
    target = (APP_ROOT / (path or 'index.html')).resolve()
    if not target.is_relative_to(APP_ROOT) or target.suffix.lower() not in ('.html', '.css', '.js', '.png', '.jpg', '.webp', '.svg', '.ttf', '.woff2', '.wasm'):
        return fail('页面不存在。', 404)
    # Only web roots and public assets, never deployment code, records, or hidden files.
    if len(target.relative_to(APP_ROOT).parts) > 1 and target.relative_to(APP_ROOT).parts[0] != 'assets':
        return fail('页面不存在。', 404)
    if not target.is_file():
        return fail('页面不存在。', 404)
    return FileResponse(target, media_type='application/wasm' if target.suffix == '.wasm' else None)
