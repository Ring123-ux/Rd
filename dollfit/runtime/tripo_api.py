"""Tripo v3 client. Credentials stay in Windows DPAPI; paid POSTs never retry."""
import json
import os
import re
import struct
from urllib.parse import urljoin
import requests
from .wardrobe_settings import ROOT, _crypt, redact
from .wardrobe_api import _public_url
from . import tripo_seller_api as seller

SECRET = ROOT / 'config' / 'tripo_credentials.dpapi'
CONFIG = ROOT / 'config' / 'tripo.local.json'
BASE = 'https://openapi.tripo3d.com/v3'
MODEL = 'v3.1-20260211'
PRESETS={
    'highest':{'geometry_quality':'detailed','texture_quality':'extreme','face_limit':2000000},
    'balanced':{'geometry_quality':'standard','texture_quality':'detailed','face_limit':50000},
    'detail':{'geometry_quality':'detailed','texture_quality':'detailed','face_limit':100000},
    'high':{'geometry_quality':'detailed','texture_quality':'extreme','face_limit':300000},
}

def provider_name():
    provider=os.environ.get('TRIPO_PROVIDER','seller')
    if provider not in ('seller','official'):raise ValueError('TRIPO_PROVIDER 必须是 seller 或 official。')
    return provider


def configured():return bool(os.environ.get('TRIPO_API_KEY','').strip())


def preflight(provider=None,require_balance=True):
    if (provider or provider_name())=='seller':return seller.preflight()
    account=request('GET','/account/balance')
    if require_balance and float(account.get('balance',0))<=0:
        raise ValueError('Tripo官方可用余额为0，请充值或选择已购买的服务。')
    return {'connected':True,'provider':'official',**account,'quality':'最高质量 · 超清几何 / 8K贴图'}

def session():
    client=requests.Session()
    client.trust_env=False  # This machine's inherited proxy breaks TLS to the China endpoint.
    return client

def base_url():
    if provider_name()=='seller':return seller.BASE+'/tripo3d'
    value=os.environ.get('TRIPO_BASE_URL',BASE)
    if value not in ('https://openapi.tripo3d.ai/v3',BASE):raise ValueError('Tripo 官方域名无效。')
    return value


def save_base(url):raise ValueError('请在 Render Environment 中修改接口配置。')
def save_key(key):raise ValueError('请在 Render Environment 中修改 TRIPO_API_KEY。')
def load_key(provider=None):return seller.load_key()


def safe_error(error):
    message = seller.error_text(error)
    if SECRET.exists():
        try: message = message.replace(load_key('official'), '[密钥已隐藏]')
        except Exception: pass
    return re.sub(r'tsk_[A-Za-z0-9_-]+', '[密钥已隐藏]', message)[:700]

def request(method, path, **kwargs):
    try:
        with session() as client:
            endpoint=base_url() if provider_name()=='official' else BASE
            response = client.request(method, endpoint+path,
            headers={'Authorization': 'Bearer '+load_key('official')},
            timeout=(20, 120), allow_redirects=False, **kwargs)
    except requests.RequestException:
        message='Tripo连接失败，请检查网络和所选官方域名。' if method=='GET' else 'Tripo连接中断。创建任务可能已被受理，未自动重复扣费；请在Tripo控制台查询任务编号并恢复查询。'
        raise ValueError(message) from None
    if len(response.content)>4*1024*1024:
        raise ValueError('Tripo响应过大。')
    try: body = response.json()
    except ValueError: raise ValueError(f'Tripo未返回JSON（HTTP {response.status_code}）。') from None
    if response.status_code!=200 or body.get('code')!=0:
        raise ValueError(f'Tripo HTTP {response.status_code} / {body.get("code")}：'+safe_error(body.get('message', '请求失败')))
    return body['data']

def upload(path,provider=None):
    if (provider or provider_name())=='seller':return seller.upload(path)
    if path.stat().st_size>20*1024*1024: raise ValueError('Tripo图片不能超过20MB。')
    with path.open('rb') as file:
        result=request('POST', '/files', files={'file':(path.name,file,'image/png')})
    return result['file_token']

def create(tokens,preset='highest',provider=None,*,face_count=None):
    if (provider or provider_name())=='seller':
        return seller.create(tokens, seller.MAX_FACE_COUNT if face_count is None else face_count)
    if set(tokens)!={'front','left','back','right'}:
        raise ValueError('请先完成同一套服装的四视图，再生成3D。')
    if preset not in PRESETS: raise ValueError('请选择有效的3D质量档位。')
    return request('POST','/generation/multiview-to-model',json={
        'inputs':[{view:tokens[view]} for view in ['front','left','back','right']],
        'model':MODEL,'texture':True,'pbr':True,'texture_alignment':'original_image',
        'auto_size':False,'quad':False,'generate_parts':False,**PRESETS[preset]})['task_id']

def query(task_id,provider=None):
    if (provider or provider_name())=='seller':return seller.query(task_id)
    if not re.fullmatch(r'[A-Za-z0-9_-]{8,160}', task_id): raise ValueError('任务编号无效。')
    return request('GET','/tasks/'+task_id)

def validate_glb(path):
    with path.open('rb') as file:
        header=file.read(20)
        if len(header)!=20: raise ValueError('模型文件不完整。')
        magic,version,length,n,kind=struct.unpack('<5I',header)
        if magic!=0x46546c67 or version!=2 or length!=path.stat().st_size or kind!=0x4e4f534a or n>8*1024*1024:
            raise ValueError('服务未返回有效的GLB模型。')
        doc=json.loads(file.read(n))
        if any(x.get('uri') and not x['uri'].startswith('data:') for x in doc.get('buffers',[])+doc.get('images',[])):
            raise ValueError('模型依赖外部贴图，请在Tripo导出为单文件GLB。')

def download(url, destination):
    # Untrusted output URLs never receive the API authorization header.
    temporary=destination.with_suffix('.download')
    for _ in range(4):
        _public_url(url)
        with session() as client, client.get(url,timeout=(20,180),stream=True,allow_redirects=False) as response:
            if response.is_redirect:
                url=urljoin(url,response.headers.get('Location','')); continue
            response.raise_for_status()
            size=0
            with temporary.open('wb') as file:
                for chunk in response.iter_content(65536):
                    size+=len(chunk)
                    if size>150*1024*1024: raise ValueError('模型超过150MB下载限制。')
                    file.write(chunk)
        validate_glb(temporary)
        temporary.replace(destination)
        return
    raise ValueError('模型下载重定向过多。')
