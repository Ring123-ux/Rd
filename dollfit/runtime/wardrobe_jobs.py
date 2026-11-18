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
from PIL import Image, ImageOps
from .wardrobe_api import IMAGE_QUALITIES, edit_images
from .wardrobe_settings import ROOT,redact

VIEWS={'front':'正面','left':'左侧面','back':'背面','right':'右侧面'}
PROMPT_VERSION='doll-outfit-geometry-v3'
PROJECTS=ROOT/'reports'/'wardrobe'/'projects'
JOBS=ROOT/'reports'/'wardrobe'/'jobs'


def write_json(path,data):
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix('.tmp');temp.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8');temp.replace(path)


def read_json(path):return json.loads(path.read_text(encoding='utf-8'))


def png_bytes(image):
    out=io.BytesIO();image.convert('RGBA').save(out,format='PNG');return out.getvalue()


def save_cover(front_path):
    """Create a small upper-body preview from the front result."""
    with Image.open(front_path) as front:
        portrait = front.crop((0, 0, front.width, max(1, round(front.height * 0.57))))
        portrait = ImageOps.fit(portrait.convert('RGB'), (360, 320), centering=(0.5, 0.0))
        temporary = front_path.with_name('wardrobe_cover.tmp')
        portrait.save(temporary, 'JPEG', quality=86)
        temporary.replace(front_path.with_name('wardrobe_cover.jpg'))


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


def create_job(project_id,prompt,height_cm=None,quality='high',size='1024x1536',garment_references=None,view_directions=None,*,new_outfit=False,outfit_name=''):
    prompt=prompt.strip()
    if not prompt or len(prompt)>5000:raise ValueError('请输入1至5000字的服装描述。')
    if quality not in IMAGE_QUALITIES:raise ValueError('请选择快速、均衡或精细画质。')
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
    new_style=new_outfit or (bool(references) and hashes!=prior_hashes)
    instructions=(previous[-1].get('instructions',[previous[-1]['user_prompt']])[-7:] if previous and not new_style else [])+[prompt]
    job_id=uuid.uuid4().hex;path=job_path(job_id)
    job={'id':job_id,'project_id':project_id,'user_prompt':prompt,'instructions':instructions,
         'prior_job_id':prior['id'] if prior and not new_style else None,'views':project['views'],
         'prompt_version':PROMPT_VERSION,'view_directions':directions,'garment_references':[],
         'quality':quality,'size':size,'outfit_name':outfit_name,'height_cm':height_cm,'created_at':time.time(),
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
        roles.append(f'图{len(images)}：只作为同款服装的参考。保持面料、颜色、领型、袖口、花纹、配饰及衣长一致；绝不采用此图的身体、手脚、姿势、构图或视角。实际遮挡关系以图1为准。')
    elif job.get('prior_job_id'):
        prior=read_job(job['prior_job_id'])
        source=prior['results'].get(view) or prior['results'].get('front')
        if source:
            images.append(job_path(prior['id'])/source['file'])
            roles.append(f'图{len(images)}：上一轮服装设计参考；按本轮最新要求修改，其余已确认服装细节尽量保持。')
    history='\n'.join(f'{i+1}. {text if i==len(job["instructions"])-1 else text[:1800]}' for i,text in enumerate(job['instructions']))
    height=f"人偶真实身高约{job['height_cm']:g}厘米，服装应表现为微型娃衣。" if job.get('height_cm') else '服装为微型BJD娃衣。'
    if view in {'left','right'}:
        pose=f'{VIEWS[view]}：鼻尖、脚尖和可见一侧必须与图1相同。禁止镜像或复制另一个侧面。'
    elif view=='back':pose='严格背面视图，展示头后部、背部和衣服背面结构，保持图1站姿和相机方向，不能转成正面或侧面。'
    else:pose='保持图1中的正面或近正面视角与站姿，不要转成侧面或背面。'
    prompt=f'''Use case: identity-preserve / BJD clothing design preview.
对象是树脂球形关节人偶，不是真人。{height}
根据以下服装需求，编辑图1，让原人偶穿上同一套可辨认的衣服。输出且仅输出一张完整的{VIEWS[view]}效果图，不要拼图、不要其他角度、不要文字标注。
输入图片角色：
{chr(10).join(roles)}
视角约束：{pose}
服装设计要求（仅决定衣服和配饰）：
{history}
以下约束优先于所有款式和参考图。编辑范围限于服装覆盖的区域与用户指定的配饰。
保持图1的头脸、发型、肤色、头身比、四肢长度、肩宽、关节位置、站姿和相机视角。保留整个人偶和画面中的头顶、脚底。服装可以增加合理的体积，身体比例和姿势保持原样。
图1决定每只手、每只脚的位置、方向、形状、可见性和遮挡顺序。保留玩偶原有的指形和脚型。禁止增加、删除或复制手、指、脚或四肢。图1中被身体遮住的手脚不要补画到另一侧。鞋袜覆盖原脚，鞋尖方向跟随原脚。
遵循实际前后关系：袖管沿着原手臂，手从相应袖口自然伸出。手在布料前方则遮住布料，在布料后方则被遮住。禁止手穿过袖壁、掌心穿入衣身、手指与布料相熔、其他角度的肢体重影。布料应有合理的厚度、重力下垂、接触阴影和褶皱。
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
                payload,meta=edit_images(images,prompt,job.get('quality','high'),job.get('size','1024x1536'))
                filename=view+'_dressed.png';(path/filename).write_bytes(payload)
                if view=='front':
                    try:save_cover(path/filename)
                    except OSError:pass  # Keep the front result available if the thumbnail cannot be saved.
                job['results'][view]={'file':filename,'prompt_version':PROMPT_VERSION,
                    **meta};job['view_status'][view]='succeeded'
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
