"""Time-limited, image-scoped links for the user's explicitly requested 3D submission."""
import hashlib
import hmac
import os
import re
import time
from urllib.parse import urlencode, urlsplit


TTL = 7200


def public_base():
    base = (os.environ.get('APP_URL') or os.environ.get('RENDER_EXTERNAL_URL') or '').rstrip('/')
    if not base:
        return None
    parts = urlsplit(base)
    if parts.scheme != 'https' or not parts.hostname or parts.username or parts.password or parts.query or parts.fragment or parts.path:
        raise ValueError('公开图片地址必须是HTTPS网站根地址，请检查 APP_URL。')
    return base


def mode(provider):
    preference = os.environ.get('TRIPO_IMAGE_SOURCE', 'auto')
    if preference not in ('auto', 'signed', 'upload'):
        raise ValueError('TRIPO_IMAGE_SOURCE 只能填 auto、signed 或 upload。')
    if provider == 'seller' and preference != 'upload':
        if public_base():
            return 'signed_links'
        if preference == 'signed':
            raise ValueError('短期图片链接需要 APP_URL 或 Render 自动提供的公开网址。')
    return 'upload'


def signature(job_id, view, expires):
    secret = os.environ.get('APP_SECRET', '')
    if len(secret) < 32:
        raise ValueError('图片链接签名尚未配置。')
    message = f'tripo-input-v1:{job_id}:{view}:{expires}'.encode()
    return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


def create(job_id, view):
    if not re.fullmatch(r'[a-f0-9]{32}', job_id) or view not in ('front', 'left', 'back', 'right'):
        raise ValueError('3D输入图片编号无效。')
    base = public_base()
    if not base:
        raise ValueError('未配置公开访问网址。')
    expires = int(time.time()) + TTL
    return f'{base}/tripo-input/{job_id}/{view}.png?' + urlencode({'expires': expires, 'signature': signature(job_id, view, expires)})


def valid(job_id, view, expires, supplied):
    try:
        if not re.fullmatch(r'[a-f0-9]{32}', job_id) or view not in ('front', 'left', 'back', 'right'):
            return False
        expires = int(expires)
        now = int(time.time())
        if not now < expires <= now + TTL + 5 or not re.fullmatch(r'[a-f0-9]{64}', supplied):
            return False
        return hmac.compare_digest(signature(job_id, view, expires), supplied)
    except (ValueError, TypeError):
        return False
