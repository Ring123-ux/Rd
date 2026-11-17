import base64
import io
import json
import os
from pathlib import Path
import secrets
import tempfile

os.environ['APP_SECRET'] = secrets.token_hex(32)
os.environ['INVITE_CODE'] = secrets.token_hex(16)
os.environ['ADMIN_USERNAME'] = 'owner'
os.environ['ADMIN_PASSWORD'] = secrets.token_urlsafe(20)
os.environ['DATA_DIR'] = tempfile.mkdtemp(prefix='dollfit-cloud-tests-')
os.environ['DATA_EPHEMERAL'] = 'true'
os.environ.pop('RENDER', None)
os.environ.pop('APP_URL', None)

import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw
from runtime import cloud_app as cloud, auth, wardrobe_jobs as jobs, tripo_seller_api as seller


@pytest.fixture
def client():
    with TestClient(cloud.app) as connection:
        yield connection


def send(client, path, body, request_id=None):
    state = client.get('/api/bootstrap').json()
    return client.post('/api/' + path, json=body,
                       headers={'X-DollFit-Token': state['token'], 'Idempotency-Key': request_id or secrets.token_hex(16)})


def account(client):
    name = 'user_' + secrets.token_hex(5)
    response = send(client, 'auth/register', {'username': name, 'password': 'test-password-long', 'invite_code': os.environ['INVITE_CODE']})
    assert response.status_code == 200, response.text
    return response.json()['user']


def picture(side=False):
    image = Image.new('RGB', (200, 300), 'white')
    draw = ImageDraw.Draw(image)
    draw.ellipse((75, 10, 125, 60), fill='tan')
    draw.rectangle((85 if side else 65, 60, 115 if side else 135, 175), fill='tan')
    draw.rectangle((75, 175, 95, 290), fill='tan')
    draw.rectangle((108, 175, 128, 290), fill='tan')
    buffer = io.BytesIO()
    image.save(buffer, 'PNG')
    return 'data:image/png;base64,' + base64.b64encode(buffer.getvalue()).decode()


def profile(client, four=False):
    views = {'front': picture(), 'left': picture(True)}
    if four:
        # Different view bytes are a mandatory user-input contract.
        for name, shade in [('back', 'brown'), ('right', 'orange')]:
            im = Image.new('RGB', (200, 300), shade)
            out = io.BytesIO(); im.save(out, 'PNG')
            views[name] = 'data:image/png;base64,' + base64.b64encode(out.getvalue()).decode()
    response = send(client, 'profile', {'name': 'Test doll', 'height_cm': 17, 'gender': 'female', 'views': views})
    assert response.status_code == 200, response.text
    return response.json()


def test_public_example_is_actual_highest_and_supports_range(client):
    sample = client.get('/api/example').json()
    assert sample['tripo']['face_count'] == 1500000
    response = client.get(sample['tripo']['model_url'], headers={'Range': 'bytes=0-19'})
    assert response.status_code == 206
    assert response.content.startswith(b'glTF') and len(response.content) == 20


def test_static_never_exposes_backend_secrets_or_database(client):
    assert client.get('/').status_code == 200
    assert client.get('/workbench.html').status_code == 200
    for path in ['/runtime/auth.py', '/.env.example', '/requirements.txt', '/models/model_metadata.json', '/data/accounts.sqlite3']:
        assert client.get(path).status_code == 404


def test_invite_is_required_and_secret_values_never_echo(client):
    response = send(client, 'auth/register', {'username': 'nobody', 'password': 'a-long-password', 'invite_code': 'bad'})
    assert response.status_code == 400
    assert os.environ['INVITE_CODE'] not in response.text


def test_csrf_and_cross_origin_are_blocked(client):
    assert client.post('/api/profile', json={}).status_code == 403
    state = client.get('/api/bootstrap').json()
    assert client.post('/api/profile', json={}, headers={'X-DollFit-Token': state['token'], 'Origin': 'https://attacker.invalid'}).status_code == 403


def test_login_logout_and_session_revocation(client):
    user = account(client)
    token = client.cookies.get('dollfit_session')
    assert client.get('/api/bootstrap').json()['user']['id'] == user['id']
    assert send(client, 'auth/logout', {}).status_code == 200
    assert auth.user(token) is None
    assert client.get('/api/bootstrap').json()['user'] is None


def test_wrong_login_never_grants_session(client):
    assert send(client, 'auth/login', {'username': 'missing-user', 'password': 'incorrect'}).status_code == 400
    assert client.get('/api/bootstrap').json()['user'] is None


def test_profile_media_and_source_reuse_are_owner_scoped(client):
    account(client)
    p = profile(client)
    original = next(iter(p['photos'].values()))
    assert client.get(original).status_code == 200
    with TestClient(cloud.app) as second:
        account(second)
        assert second.get('/api/profile/' + p['id']).status_code == 404
        assert second.get(original).status_code == 404
        assert send(second, 'profile', {'source_id': p['id'], 'height_cm': 17, 'gender': 'female', 'views': {}}).status_code == 404
        other = profile(second)
        assert other['project_id'] != p['project_id']


def test_required_angles_and_height_are_validated(client):
    account(client)
    assert send(client, 'profile', {'height_cm': 17, 'gender': 'female', 'views': {'front': picture()}}).status_code == 400
    assert send(client, 'profile', {'height_cm': -17, 'gender': 'female', 'views': {}}).status_code == 400


def test_cloud_settings_are_not_mutable_by_visitors(client):
    account(client)
    assert send(client, 'settings', {'tripo_key': 'must-not-save'}).status_code == 400
    assert send(client, 'test-tripo', {}).status_code == 403


def test_design_enforces_quality_and_idempotency(client, monkeypatch):
    account(client)
    p = profile(client)
    monkeypatch.setenv('HEJU_API_KEY', 'fake-test-key')
    monkeypatch.setattr(cloud, 'queue', lambda *args: True)
    rid = secrets.token_hex(16)
    body = {'profile_id': p['id'], 'prompt': '绿色开衫', 'auto_3d': False, 'preset': 'balanced', 'quality': 'low'}
    first = send(client, 'design', body, rid)
    assert first.status_code == 200, first.text
    second = send(client, 'design', body, rid)
    assert first.json()['id'] == second.json()['id']
    job = jobs.read_job(first.json()['id'])
    assert job['quality'] == 'high' and job['size'] == '1024x1536'
    jobs.RUNNING.discard(job['id'])


def test_auto_3d_requires_four_real_angles(client, monkeypatch):
    account(client)
    p = profile(client)
    monkeypatch.setenv('HEJU_API_KEY', 'fake-test-key')
    response = send(client, 'design', {'profile_id': p['id'], 'prompt': '连衣裙', 'auto_3d': True})
    assert response.status_code == 400
    assert '四个角度' in response.json()['error']


def test_quotas_are_atomic_and_duplicate_requests_do_not_spend_twice(monkeypatch):
    user = secrets.token_hex(16)
    monkeypatch.setenv('USER_DAILY_DESIGNS', '2')
    monkeypatch.setenv('USER_DAILY_3D', '0')
    with pytest.raises(ValueError):
        auth.reserve_many(user, [('design', 'test-atomic-1', 'resource-1'), ('3d', 'test-atomic-2', 'resource-1')])
    assert auth.receipt(user, 'design', 'test-atomic-1') is None
    auth.reserve(user, 'design', 'test-idempotent-1', 'resource-2')
    auth.reserve(user, 'design', 'test-idempotent-1', 'resource-2')
    auth.reserve(user, 'design', 'test-idempotent-2', 'resource-3')
    with pytest.raises(ValueError):
        auth.reserve(user, 'design', 'test-idempotent-3', 'resource-4')


def test_seller_payload_has_correct_angles_and_maximum_faces(monkeypatch):
    calls = []
    monkeypatch.setattr(seller, '_public_url', lambda x: x)
    monkeypatch.setattr(seller, 'request', lambda *args, **kwargs: calls.append((args, kwargs)) or {'creationsId': 'task-valid-12345'})
    seller.create({v: 'https://example.com/' + v for v in cloud.VIEWS})
    body = calls[0][1]['json']
    assert body['faceCount'] == 1500000
    assert body['imageTagList'] == ['frontView', 'rearView', 'leftView', 'rightView']
    assert [url.rsplit('/', 1)[1] for url in body['imageList']] == ['front', 'back', 'left', 'right']


def test_normalizer_uses_textured_mesh_and_preserves_wait():
    waiting = seller.normalize_query({'status': 'wait', 'result': []})
    assert waiting['status'] == 'queued'
    ready = seller.normalize_query({'status': 'success', 'result': [{'urlResult': {'textureGlb': 'https://example.com/color.glb', 'geometryGlb': 'https://example.com/plain.glb'}}]})
    assert ready['output']['model_url'].endswith('color.glb')
    assert ready['progress'] == 100


def test_restart_never_repeats_uncertain_paid_image_posts(client, monkeypatch):
    user = account(client)
    p = profile(client)
    monkeypatch.setenv('HEJU_API_KEY', 'fake-test-key')
    monkeypatch.setattr(cloud, 'queue', lambda *args: True)
    response = send(client, 'design', {'profile_id': p['id'], 'prompt': '重启测试', 'auto_3d': False})
    jid = response.json()['id']
    jobs.RUNNING.discard(jid)
    cloud.startup()
    saved = jobs.read_job(jid)
    assert saved['status'] == 'failed'
    assert '未自动重复生图' in saved['errors']['front']


def test_api_secret_is_redacted_from_provider_failures(monkeypatch):
    secret = secrets.token_urlsafe(25)
    monkeypatch.setenv('TRIPO_API_KEY', secret)
    assert secret not in seller.error_text('authorization failed: ' + secret)


def test_full_design_to_3d_chain_uses_real_files_and_no_extra_paid_post(client, monkeypatch):
    account(client)
    p = profile(client, four=True)
    monkeypatch.setenv('HEJU_API_KEY', 'fake-test-key')
    monkeypatch.setenv('TRIPO_API_KEY', 'fake-3d-key')
    monkeypatch.setattr(cloud, 'queue', lambda *args: True)
    monkeypatch.setattr(cloud.tripo, 'preflight', lambda **kwargs: {'connected': True})
    image_calls, model_calls = [], []
    def edit(paths, prompt, quality, size):
        image_calls.append((paths, prompt, quality, size))
        return Path(paths[0]).read_bytes(), {'model': 'fake-image-model', 'provider': 'test'}
    monkeypatch.setattr(jobs, 'edit_images', edit)
    monkeypatch.setattr(cloud.tripo, 'upload', lambda path, provider: 'https://example.com/' + path.name)
    def create(tokens, quality, provider):
        model_calls.append((tokens, quality, provider))
        return 'task-test-123456789'
    monkeypatch.setattr(cloud.tripo, 'create', create)
    monkeypatch.setattr(cloud.tripo, 'query', lambda *args: {'status': 'success', 'progress': 100, 'face_count': 1500000,
                                                           'output': {'model_url': 'https://example.com/model.glb'}})
    monkeypatch.setattr(cloud.tripo, 'download', lambda url, dest: dest.write_bytes(b'fake-test-glb'))
    response = send(client, 'design', {'profile_id': p['id'], 'prompt': '灰绿开衫与粉色百褶裙', 'auto_3d': True})
    assert response.status_code == 200, response.text
    jid = response.json()['id']
    cloud.run_design(jid)
    result = client.get('/api/job/' + jid).json()
    assert result['status'] == 'succeeded' and len(result['images']) == 4
    assert result['tripo']['status'] == 'succeeded'
    assert result['tripo']['face_count'] == 1500000
    assert len(image_calls) == 4 and len(model_calls) == 1
    assert all(call[2:] == ('high', '1024x1536') for call in image_calls)
    assert model_calls[0][1] == 'highest'
    assert 'SCREEN-LEFT-FACING' in image_calls[1][1] and 'SCREEN-RIGHT-FACING' in image_calls[3][1]
    assert send(client, 'tripo', {'job_id': jid}).status_code == 200
    assert len(model_calls) == 1
    with TestClient(cloud.app) as another:
        account(another)
        assert another.get('/api/job/' + jid).status_code == 404
        assert another.get(result['tripo']['model_url']).status_code == 404


def test_real_measurement_subprocess_returns_all_13_and_scales_with_height(client):
    account(client)
    p = profile(client)
    cloud.measure(p['id'], client.get('/api/bootstrap').json()['user']['id'])
    measurement = client.get('/api/profile/' + p['id']).json()['measurement']
    assert measurement['status'] == 'succeeded', measurement
    assert len(measurement['rows']) == 13 and measurement['uses_weight'] is False
    assert measurement['runtime'] == 'onnx-fp32-cpu'
    assert measurement['measurements_cm']['shoulder-breadth'] < 17


def test_asset_restore_rejects_tampered_parts(tmp_path):
    from deployment.assets import restore
    import hashlib
    directory = tmp_path / 'bundled'; directory.mkdir()
    part = b'example part'
    (directory / 'test.part01').write_bytes(part)
    manifest = {'assets': [{'target': 'models/test.bin', 'bytes': len(part), 'sha256': hashlib.sha256(part).hexdigest(),
                           'parts': [{'file': 'test.part01', 'sha256': hashlib.sha256(part).hexdigest()}]}]}
    (directory / 'manifest.json').write_text(json.dumps(manifest))
    restore(tmp_path)
    assert (tmp_path / 'models/test.bin').read_bytes() == part
    (tmp_path / 'models/test.bin').unlink()
    (directory / 'test.part01').write_bytes(b'tampered')
    with pytest.raises(ValueError):
        restore(tmp_path)


def test_recovery_rejects_another_designs_task(monkeypatch):
    uploaded = {v: 'https://example.com/own-' + v for v in cloud.VIEWS}
    monkeypatch.setattr(seller, 'request', lambda *args, **kwargs: {'status': 'wait', 'imageList': list(uploaded.values())})
    assert seller.verify_own_task('task-valid-123456', uploaded)['status'] == 'queued'
    monkeypatch.setattr(seller, 'request', lambda *args, **kwargs: {'status': 'success', 'imageList': ['https://example.com/someone-else']})
    with pytest.raises(ValueError, match='不一致'):
        seller.verify_own_task('task-other-123456', uploaded)
