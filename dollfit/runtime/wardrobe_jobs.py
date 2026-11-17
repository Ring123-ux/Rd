"""Durable sequential view jobs. The front image anchors clothing across angles."""
from __future__ import annotations
import argparse
import ctypes
import hashlib
import io
import json
import os
import shutil
from pathlib import Path
import subprocess
import sys
import time
import uuid
import zipfile
from PIL import Image
from .wardrobe_api import edit_images
from .wardrobe_settings import ROOT,redact

VIEWS={'front':'正面','left':'左侧面','back':'背面','right':'右侧面'}
PROMPT_VERSION='pose-lock-garment-reference-v2'
PROJECTS=ROOT/'reports'/'wardrobe'/'projects'
JOBS=ROOT/'reports'/'wardrobe'/'jobs'


def write_json(path,data):
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix('.tmp');temp.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8');temp.replace(path)


def read_json(path):return json.loads(path.read_text(encoding='utf-8'))


def png_bytes(image):
    out=io.BytesIO();image.convert('RGBA').save(out,format='PNG');return out.getvalue()


def validate_views(views):
    if views.get('front') is None or views.get('left') is None:raise ValueError('服装设计必须上传正面和左侧面原图；背面、右侧面可选。')
    def digest(im):return hashlib.sha256(str(im.size).encode()+im.convert('RGBA').tobytes()).hexdigest()
    seen={}
    for key in VIEWS:
        if views.get(key) is None:continue
        value=digest(views[key])
        if value in seen:raise ValueError(VIEWS[seen[value]]+'和'+VIEWS[key]+'不能使用同一张图片。')
        seen[value]=key


def ensure_project(views,namespace=""):
    validate_views(views)
    digest=hashlib.sha256(b'bjd-wardrobe-originals-v1'+namespace.encode())
    for key in VIEWS:
        digest.update(key.encode())
        if views.get(key) is not None:digest.update(png_bytes(views[key]))
    project_id=digest.hexdigest()[:32];path=PROJECTS/project_id
    if not (path/'project.json').exists():
        path.mkdir(parents=True,exist_ok=True)
        for key,image in views.items():
            if key in VIEWS and image is not None:image.save(path/(key+'.png'))
        write_json(path/'project.json',{'id':project_id,'views':[key for key in VIEWS if views.get(key) is not None],'jobs':[]})
    return read_json(path/'project.json')


def job_path(job_id):
    if len(job_id)!=32 or any(c not in '0123456789abcdef' for c in job_id):raise ValueError('任务编号无效。')
    return JOBS/job_id


def read_job(job_id):return read_json(job_path(job_id)/'job.json')


def create_job(project_id,prompt,height_cm=None,quality='medium',size='1024x1024',garment_references=None,view_directions=None):
    prompt=prompt.strip()
    if not prompt or len(prompt)>5000:raise ValueError('请输入1至5000字的服装描述。')
    if len(project_id)!=32 or any(c not in '0123456789abcdef' for c in project_id):raise ValueError('原图项目编号无效。')
    project=read_json(PROJECTS/project_id/'project.json')
    references=list(garment_references or [])
    if len(references)>3:raise ValueError('最多上传3张服装参考图。')
    directions={'left':'left','right':'right',**(view_directions or {})}
    if any(directions.get(key) not in {'left','right'} for key in ['left','right']):raise ValueError('侧面朝向设置无效。')
    previous=[read_job(key) for key in project['jobs']]
    if any(job['status'] in {'queued','running'} and worker_alive(job) for job in previous):
        raise ValueError('当前图片还有设计任务正在处理，请完成后再继续修改。')
    reference_payloads=[png_bytes(image) for image in references]
    hashes=[hashlib.sha256(payload).hexdigest() for payload in reference_payloads]
    prior=next((job for job in reversed(previous) if job['results'].get('front') and
                (not references or [item['sha256'] for item in job.get('garment_references',[])]==hashes)),None)
    prior_hashes=[item['sha256'] for item in previous[-1].get('garment_references',[])] if previous else []
    new_style=bool(references) and hashes!=prior_hashes
    instructions=(previous[-1].get('instructions',[previous[-1]['user_prompt']])[-7:] if previous and not new_style else [])+[prompt]
    job_id=uuid.uuid4().hex;path=job_path(job_id)
    job={'id':job_id,'project_id':project_id,'user_prompt':prompt,'instructions':instructions,
         'prior_job_id':prior['id'] if prior and not new_style else None,'views':project['views'],
         'prompt_version':PROMPT_VERSION,'view_directions':directions,'garment_references':[],
         'quality':'high','size':'1024x1536','height_cm':height_cm,'created_at':time.time(),
         'status':'queued','view_status':{key:'pending' for key in project['views']},
         'results':{},'errors':{},'worker_pid':None}
    path.mkdir(parents=True,exist_ok=True)
    for index,payload in enumerate(reference_payloads,1):
        filename=f'garment_reference_{index}.png';(path/filename).write_bytes(payload)
        job['garment_references'].append({'file':filename,'sha256':hashlib.sha256(payload).hexdigest()})
    write_json(path/'job.json',job)
    project['jobs'].append(job_id);write_json(PROJECTS/project_id/'project.json',project)
    return job


RUNNING=set()


def worker_alive(job):return job['id'] in RUNNING


def launch(job_id):
    raise ValueError('云端任务必须由统一队列启动。')


def prompt_and_images(job,view):
    originals=PROJECTS/job['project_id']
    images=[originals/(view+'.png')]
    roles=[f'图1：必须编辑的{VIEWS[view]}原图，保留该图的人偶、姿势、相机角度、构图和背景。']
    # Opposite-side source images compete with pose conditioning. The target alone defines its camera.
    for reference in job.get('garment_references',[]):
        images.append(job_path(job['id'])/reference['file'])
        roles.append(f'图{len(images)}：服装款式参考。只提取衣服、帽子、鞋袜等可穿戴服饰的款式、材质、颜色、图案与工艺，不复制参考人物的脸、头发、身体、姿势、相机角度或背景。拼图中的各角度仅用于理解服装结构。')
    if view!='front' and job['results'].get('front'):
        images.append(job_path(job['id'])/job['results']['front']['file'])
        roles.append(f'图{len(images)}：本轮已经确定的正面穿衣设计，服装颜色、面料、领型、袖型、花纹、配饰和长度必须与它一致。只转为目标视角。')
    elif job.get('prior_job_id'):
        prior=read_job(job['prior_job_id'])
        source=prior['results'].get(view) or prior['results'].get('front')
        if source:
            images.append(job_path(prior['id'])/source['file'])
            roles.append(f'图{len(images)}：上一轮服装设计参考；按本轮最新要求修改，其余已确认服装细节尽量保持。')
    history='\n'.join(f'{i+1}. {text if i==len(job["instructions"])-1 else text[:1800]}' for i,text in enumerate(job['instructions']))
    height=f"人偶真实身高约{job['height_cm']:g}厘米，服装应表现为微型娃衣。" if job.get('height_cm') else '服装为微型BJD娃衣。'
    direction=job.get('view_directions',{}).get(view,'left' if view=='left' else 'right')
    if view in {'left','right'}:
        screen='右' if direction=='right' else '左';english='RIGHT' if direction=='right' else 'LEFT'
        pose=f'严格纯侧面：鼻尖、脸部正面、胸部前侧与脚尖均朝向输出画面的{screen}边。SCREEN-{english}-FACING PROFILE. Nose and toes point to the {english} edge of the image. Preserve the exact pose and orientation of Image 1. 所有服装参考只决定服装，不决定视角，不能把另一个侧面复制过来。'
    elif view=='back':pose='严格背面视图，展示头后部、背部和衣服背面结构，保持图1站姿和相机方向，不能转成正面或侧面。'
    else:pose='保持图1中的正面或近正面视角与站姿，不要转成侧面或背面。'
    prompt=f'''Use case: identity-preserve / BJD clothing design preview.
对象是树脂球形关节人偶，不是真人。{height}
根据以下服装需求，编辑图1，让原人偶穿上同一套可辨认的衣服。输出且仅输出一张完整的{VIEWS[view]}效果图，不要拼图、不要其他角度、不要文字标注。
输入图片角色：
{chr(10).join(roles)}
视角硬性约束（最高优先级）：{pose}
按时间顺序的用户要求（最后一条优先，未修改的要求继续有效）：
{history}
硬性保留：图1中的脸、头部、眼睛、发型、树脂肤色、娃体比例、手脚、姿势、关节位置、相机视角和背景。不要美化成真人，不要改变肢体长度，不要增加肢体。
只围绕服装和用户明确提出的配饰修改。衣服自然包裹原娃体，保留原有轮廓和身体姿态。服装参考不能改变图1的拍摄角度。保持整个人偶完整入镜，可在需要时留白。
多角度保持同款，尤其是领型、袖口、裙长、布料、颜色和图案。未指定的细节采用简洁且与同款结构一致的设计。本图只作服装外观预览，不显示尺寸文字或裁剪纸样。'''
    return prompt,images


def run(job_id):
    path=job_path(job_id);lock=path/'worker.lock'
    try:fd=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY)
    except FileExistsError:raise ValueError('任务已有工作进程，请勿重复提交。') from None
    os.close(fd)
    try:
        job=read_job(job_id);job['worker_pid']=os.getpid();job['status']='running';write_json(path/'job.json',job)
        for view in job['views']:
            if job['results'].get(view):continue
            job['view_status'][view]='running';job['errors'].pop(view,None);write_json(path/'job.json',job)
            prompt,images=prompt_and_images(job,view)
            (path/(view+'_prompt.txt')).write_text(prompt,encoding='utf-8')
            try:
                payload,meta=edit_images(images,prompt,'high','1024x1536')
                filename=view+'_dressed.png';(path/filename).write_bytes(payload)
                job['results'][view]={'file':filename,'prompt_version':PROMPT_VERSION,
                    'expected_screen_direction':job.get('view_directions',{}).get(view) if view in {'left','right'} else None,**meta};job['view_status'][view]='succeeded'
            except Exception as error:
                job['errors'][view]=redact(error)[:900];job['view_status'][view]='failed'
            write_json(path/'job.json',job)
            if view=='front' and not job['results'].get('front'):break
        job['status']='succeeded' if len(job['results'])==len(job['views']) else ('partial_failure' if job['results'] else 'failed')
        job['finished_at']=time.time();write_json(path/'job.json',job)
    finally:lock.unlink(missing_ok=True)


def retry(job_id):
    job=read_job(job_id)
    if worker_alive(job):raise ValueError('任务仍在处理中，未重复提交。')
    (job_path(job_id)/'worker.lock').unlink(missing_ok=True)
    return launch(job_id)


def redraw_direction(job_id,view):
    if view not in {'left','right'}:raise ValueError('仅侧面视图支持朝向纠正。')
    job=read_job(job_id)
    if worker_alive(job):raise ValueError('当前任务仍在生成，请完成后再纠正朝向。')
    if view not in job['views']:raise ValueError('该角度没有上传原图。')
    path=job_path(job_id);old=job['results'].get(view)
    if old:
        archive=path/'revisions';archive.mkdir(exist_ok=True)
        tag=str(time.time_ns());shutil.copy2(path/old['file'],archive/(view+'_'+tag+'.png'))
        write_json(archive/(view+'_'+tag+'.json'),old)
    job['results'].pop(view,None);job['view_status'][view]='pending';job['errors'].pop(view,None)
    job['view_directions']={'left':'left','right':'right',**job.get('view_directions',{})}
    job['prompt_version']=PROMPT_VERSION;job['status']='queued';write_json(path/'job.json',job)
    return launch(job_id)


def seller_zip(job,measurement=None):
    out=io.BytesIO()
    with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as archive:
        for view,result in job['results'].items():archive.write(job_path(job['id'])/result['file'],f'{VIEWS[view]}_服装效果.png')
        brief={'服装需求记录':job['instructions'],'已提供视图':[VIEWS[key] for key in job['views']],
               '未提供视图':[VIEWS[key] for key in VIEWS if key not in job['views']],
               '说明':'图片为AI服装设计预览。合身与工艺需卖家结合实物或厂家尺寸核验。未提供角度未生成。',
               '尺寸来源':'原始正面、左侧面照片的神经网络等比例估测；不从穿衣生成图测量。',
               '服装参考图数量':len(job.get('garment_references',[])),'侧面预期画面朝向':job.get('view_directions',{})}
        for index,reference in enumerate(job.get('garment_references',[]),1):
            archive.write(job_path(job['id'])/reference['file'],f'服装参考图_{index}.png')
        archive.writestr('服装设计说明.json',json.dumps(brief,ensure_ascii=False,indent=2))
        if measurement:archive.writestr('原娃体估测尺寸.json',json.dumps(measurement,ensure_ascii=False,indent=2))
    return out.getvalue()


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('command',choices=['run']);parser.add_argument('--job-id',required=True)
    args=parser.parse_args();run(args.job_id)
