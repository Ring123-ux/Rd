"""Adapter for the user's purchased service, verified with an actual four-view task."""
import json
import os
from pathlib import Path
import re
import requests
import time
from .wardrobe_settings import ROOT, _crypt, redact
from .wardrobe_api import _public_url

BASE='http://47.120.44.134'
SECRET=ROOT/'config'/'tripo_purchased_credentials.dpapi'
MAX_FACE_COUNT=1500000


class ProviderConnectionError(ValueError):
    def __init__(self, stage, cause):
        self.stage = stage
        self.error_kind = type(cause).__name__
        message = {'upload': '试穿图上传中断；尚未提交3D生成，可以继续传图。',
                   'submit': '3D提交响应中断，服务商可能已接收；请核对任务编号后恢复，未自动重提。',
                   'query': '3D任务查询连接中断，已有任务编号会保留。',
                   'preflight': '3D服务连接检查失败，请稍后重试。'}.get(stage, '3D服务连接中断。')
        super().__init__(message)


class ProviderRejected(ValueError):
    """An explicit client/quota/auth rejection, rather than an uncertain create response."""

def save_key(value):
    raise ValueError('请在 Render Environment 中修改 TRIPO_API_KEY。')


def load_key():
    key=os.environ.get('TRIPO_API_KEY','').strip()
    if not key: raise ValueError('管理员尚未配置 TRIPO_API_KEY。')
    return key


def error_text(error):
    text=redact(error)
    if SECRET.exists():
        try:text=text.replace(load_key(),'[密钥已隐藏]')
        except Exception:pass
    return text[:700]

def request(method,path,**kwargs):
    # This is the exact HTTP endpoint explicitly supplied/authorized by the user.
    with requests.Session() as client:
        client.trust_env=False
        stage = 'upload' if path == '/upload' else 'submit' if path == '/tripo3d/generate' else 'query' if path.startswith('/tripo3d/query/') else 'preflight'
        timeout = (25, 240 if stage == 'upload' else 300 if stage == 'submit' else 120)
        try:
            response=client.request(method,BASE+path,headers={'Authorization':load_key()},
                timeout=timeout,allow_redirects=False,**kwargs)
        except requests.RequestException as error:
            raise ProviderConnectionError(stage, error) from None
    if len(response.content)>5*1024*1024:raise ValueError('服务商响应过大。')
    try:body=response.json()
    except ValueError:raise ValueError(f'服务商返回HTTP {response.status_code}，响应不是JSON。') from None
    if not isinstance(body,dict):raise ValueError('服务商响应格式无效。')
    if response.status_code!=200 or body.get('success') is False:
        message=f'卖家接口HTTP {response.status_code}：'+error_text(body.get('detail') or body.get('message') or '请求失败')
        if response.status_code in (400,401,402,403,404,405,413,422,429):raise ProviderRejected(message)
        raise ValueError(message)
    return body

def preflight():
    # Documented by the running service: neither query increases usage_count.
    expiry=request('GET','/queryTokenExpiry')
    usage=request('GET','/queryTokenUsage')
    return {'connected':True,'provider':'seller','usage_count':usage.get('usage_count'),
            'expires_at':expiry.get('expires_at'),'quality':'最高质量 · 150万面'}

def upload(path):
    path=Path(path)
    if path.stat().st_size>20*1024*1024:raise ValueError('图片不能超过20MB。')
    # Retrying a temporary FILE upload does not repeat a paid model generation.
    for attempt in range(3):
        try:
            with path.open('rb') as file:
                body=request('POST','/upload',files={'file':(path.name,file,'image/png')})
            break
        except ProviderConnectionError:
            if attempt == 2:raise
            time.sleep(2 * (attempt + 1))
    url=body.get('url')
    if not isinstance(url,str):raise ValueError('卖家接口没有返回图片地址。')
    _public_url(url)
    return url

def create(urls):
    if set(urls)!={'front','left','back','right'}:raise ValueError('最高质量3D需要四张同款试穿图。')
    for url in urls.values():_public_url(url)
    order=['front','back','left','right']
    body=request('POST','/tripo3d/generate',json={
        'imageList':[urls[v] for v in order],
        'imageTagList':['frontView','rearView','leftView','rightView'],
        'faceCount':MAX_FACE_COUNT})
    task=body.get('creationsId') or body.get('data',{}).get('creationsId')
    if not isinstance(task,str) or not re.fullmatch(r'[A-Za-z0-9_-]{8,160}',task):
        raise ValueError('服务商未返回有效任务编号，请先核对生成记录，避免重复提交。')
    return task

def normalize_query(body):
    data=body.get('data',body)
    results=data.get('result') or []
    item=next((r for r in results if isinstance(r,dict)),{})
    status=str(data.get('status') or item.get('status') or 'unknown').lower()
    if status in ('wait','waiting','pending'):status='queued'
    elif status in ('processing','generating'):status='running'
    elif status in ('succeeded','completed','finished'):status='success'
    elif status in ('failure','error'):status='failed'
    progress=item.get('progress')
    if not isinstance(progress,(int,float)):progress=100 if status=='success' else 0
    output=item.get('urlResult') or {}
    url=output.get('textureGlb') or output.get('glb')
    if url is not None and not isinstance(url,str):url=None
    return {'status':status,'progress':progress,'output':{'model_url':url},
            'actual_model_version':data.get('model'),'face_count':data.get('faceCount'),
            'error_message':error_text(data.get('errorMsg') or item.get('errorMsg') or data.get('message') or '')}

def query(task):
    if not re.fullmatch(r'[A-Za-z0-9_-]{8,160}',task):raise ValueError('卖家任务编号无效。')
    return normalize_query(request('GET','/tripo3d/query/'+task))


def verify_own_task(task, uploaded):
    """Recover a lost create response only when the remote task uses this design's exact uploads."""
    if not re.fullmatch(r'[A-Za-z0-9_-]{8,160}', task) or set(uploaded) != {'front','left','back','right'}:
        raise ValueError('缺少可核对的原提交记录，请联系管理员。')
    body = request('GET', '/tripo3d/query/' + task)
    data = body.get('data', body)
    remote_images = data.get('imageList')
    if not isinstance(remote_images, list) or sorted(remote_images) != sorted(uploaded.values()):
        raise ValueError('这个任务编号的输入图片与当前设计不一致，未导入其他任务。')
    return normalize_query(body)
