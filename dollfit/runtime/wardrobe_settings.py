"""Cloud settings. Provider credentials are read only from server environment variables."""
import os
import re
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1]
ROOT = Path(os.environ.get('DATA_DIR', '/tmp/dollfit-data' if os.environ.get('RENDER') else str(APP_ROOT / 'data'))).resolve()
ROOT.mkdir(parents=True, exist_ok=True)
CONFIG = ROOT / 'unused-settings.json'
SECRET = ROOT / 'unused-credentials.dpapi'


def load_key():
    value = os.environ.get('HEJU_API_KEY', '').strip()
    if not value:
        raise ValueError('管理员尚未配置 HEJU_API_KEY。')
    return value


def load_settings():
    return {'base_url': 'https://www.hejuapi.com/v1', 'model': 'gpt-image-2',
            'provider': '合聚API', 'direct_network': True,
            'multipart_image_field': 'image[]', 'read_timeout_seconds': 600}


def save_key(value):
    raise ValueError('云端密钥请在 Render 的 Environment 中修改。')


def _crypt(payload, protect):
    raise ValueError('云端不读取 Windows 本机加密文件，请配置服务器环境变量。')


def redact(value):
    text = str(value)
    for name in ('HEJU_API_KEY', 'TRIPO_API_KEY', 'APP_SECRET', 'INVITE_CODE', 'ADMIN_PASSWORD'):
        secret = os.environ.get(name, '')
        if secret:
            text = text.replace(secret, '[已隐藏]')
    return re.sub(r'(?:sk-|tsk_)[A-Za-z0-9_-]{10,}', '[密钥已隐藏]', text)[:900]
