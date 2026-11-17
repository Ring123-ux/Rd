"""OpenAI-compatible image editing against the user's explicitly chosen provider."""
from __future__ import annotations
import base64
import io
import ipaddress
import json
import socket
from urllib.parse import urlsplit,urljoin
import requests
from PIL import Image
from .wardrobe_settings import load_settings,load_key,redact

MAX_IMAGE_BYTES=40*1024*1024

def _network_options():
    # Per-provider routing; do not change the user's system proxy settings.
    return {'proxies':{'http':None,'https':None,'all':None}} if load_settings().get('direct_network') else {}


def _error(response):
    try:
        body=response.json();error=body.get('error',body.get('message',''))
        if isinstance(error,dict):error=error.get('message',str(error))
    except ValueError:error=response.text[:400]
    message=redact(error)[:600]
    if response.status_code in (401,403):return '生图接口鉴权失败，请检查密钥和令牌分组。'+message
    if response.status_code in (402,429):return '生图账户额度不足或请求受限，请检查合聚API账户。'+message
    return f'生图接口返回HTTP {response.status_code}：{message}'


def probe():
    settings=load_settings()
    try:
        response=requests.get(settings['base_url']+'/models',headers={'Authorization':'Bearer '+load_key()},
                              timeout=(15,30),allow_redirects=False,**_network_options())
    except requests.RequestException as error:raise ValueError('无法连接生图接口：'+redact(error)) from None
    if response.status_code!=200:raise ValueError(_error(response))
    try:models=[item['id'] for item in response.json().get('data',[]) if isinstance(item,dict) and 'id' in item]
    except (ValueError,TypeError):raise ValueError('生图接口未返回可识别的模型列表。') from None
    if settings['model'] not in models:raise ValueError('当前密钥的模型列表中没有gpt-image-2，请检查令牌分组。')
    return {'connected':True,'provider':settings['provider'],'model':settings['model']}


def _public_url(url):
    parts=urlsplit(url)
    if parts.scheme!='https' or not parts.hostname or parts.username or parts.password or parts.port not in (None,443):
        raise ValueError('图片下载地址无效。')
    try:addresses=socket.getaddrinfo(parts.hostname,443,type=socket.SOCK_STREAM)
    except socket.gaierror:raise ValueError('无法解析生成图片的下载地址。') from None
    if not addresses or any(not ipaddress.ip_address(item[4][0]).is_global for item in addresses):
        raise ValueError('生图接口返回了非公网图片地址，已阻止下载。')
    return url


def _download(url):
    # Never send the provider token to a returned image URL or a redirect.
    for _ in range(4):
        _public_url(url)
        try:
            with requests.get(url,timeout=(15,90),stream=True,allow_redirects=False,**_network_options()) as response:
                if response.is_redirect:
                    url=urljoin(url,response.headers.get('Location',''));continue
                if response.status_code!=200:raise ValueError('生成图片下载失败，请检查任务记录后重试下载。')
                chunks=[];size=0
                for chunk in response.iter_content(65536):
                    size+=len(chunk)
                    if size>MAX_IMAGE_BYTES:raise ValueError('生成图片过大，未保存。')
                    chunks.append(chunk)
                return b''.join(chunks)
        except requests.RequestException:raise ValueError('生成图片下载中断；请先检查供应商生成记录，避免重复生图。') from None
    raise ValueError('生成图片下载地址重定向过多。')


def decode_output(body):
    data=body.get('data')
    if not isinstance(data,list) or not data or not isinstance(data[0],dict):
        raise ValueError('接口未返回可识别的图片，未生成虚假的预览。')
    item=data[0]
    if item.get('b64_json'):
        try:payload=base64.b64decode(item['b64_json'],validate=True)
        except (ValueError,TypeError):raise ValueError('接口返回的图片编码无效。') from None
    elif item.get('url'):payload=_download(item['url'])
    else:raise ValueError('接口未返回图片内容或下载地址。')
    if len(payload)>MAX_IMAGE_BYTES:raise ValueError('生成图片超过大小限制。')
    try:
        with Image.open(io.BytesIO(payload)) as image:
            image.load();out=io.BytesIO();image.convert('RGB').save(out,format='PNG')
    except Exception:raise ValueError('接口返回内容不是有效图片。') from None
    return out.getvalue()


def edit_images(image_paths,prompt,quality='medium',size='1024x1024'):
    settings=load_settings()
    if not image_paths or len(image_paths)>8:raise ValueError('请提供1至8张有效参考图片。')
    if quality not in {'medium','high'} or size not in {'1024x1024','1024x1536'}:raise ValueError('不支持的生图规格。')
    files=[]
    for index,path in enumerate(image_paths,1):
        with Image.open(path) as image:
            image=image.convert('RGB');image.thumbnail((1600,1600))
            buffer=io.BytesIO();image.save(buffer,format='PNG')
        files.append((settings.get('multipart_image_field','image[]'),(f'reference_{index}.png',buffer.getvalue(),'image/png')))
    try:
        response=requests.post(settings['base_url']+'/images/edits',
            headers={'Authorization':'Bearer '+load_key()},
            data={'model':settings['model'],'prompt':prompt,'n':'1','quality':quality,'size':size},
            files=files,timeout=(20,int(settings.get('read_timeout_seconds',600))),allow_redirects=False,**_network_options())
    except requests.Timeout:
        raise ValueError('生图请求超时，供应商可能仍在处理；未自动重复提交。请先核对合聚API生成记录，再决定重试。') from None
    except requests.RequestException as error:
        raise ValueError('生图连接中断，未自动重复提交：'+redact(error)) from None
    if response.status_code!=200:raise ValueError(_error(response))
    if len(response.content)>60*1024*1024:raise ValueError('生图接口响应过大。')
    try:body=response.json()
    except ValueError:raise ValueError('生图接口未返回JSON数据。') from None
    payload=decode_output(body)
    # Save only non-secret, useful billing metadata, never the raw response or headers.
    usage=body.get('usage') if isinstance(body.get('usage'),dict) else {}
    safe_usage={key:usage[key] for key in ['input_tokens','output_tokens','total_tokens','prompt_tokens','completion_tokens']
                if isinstance(usage.get(key),(int,float)) and not isinstance(usage.get(key),bool)}
    return payload,{'model':settings['model'],'usage':safe_usage,'provider':settings['provider']}
