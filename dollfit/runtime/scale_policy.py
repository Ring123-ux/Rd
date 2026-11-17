"""Reference-height scaling and guards shared by inference, UI and exports."""
from __future__ import annotations
import math

PIPELINE_VERSION='reference_height_scaling_v1'
MEASUREMENT_KEYS=('ankle','arm-length','bicep','calf','chest','forearm','hip',
                  'leg-length','shoulder-breadth','shoulder-to-crotch','thigh','waist','wrist')
LINEAR_LENGTHS={'arm-length':'臂长','leg-length':'腿长','shoulder-breadth':'肩宽','shoulder-to-crotch':'肩至裆长'}


def scale_context(height_cm,subject_type,info):
    height=float(height_cm)
    if not math.isfinite(height) or height<=0:raise ValueError('身高必须为大于零的有效数值。')
    if subject_type not in {'bjd','human'}:raise ValueError('不支持的对象类型。')
    lo,hi=map(float,info['metadata_ranges']['height_cm'])
    reference=float(info['height_mean']) if subject_type=='bjd' else height
    if not lo<=reference<=hi:
        raise ValueError(f'真人直接预测只支持训练身高范围{lo:.1f}–{hi:.1f}cm；人偶请使用等比例估算模式。')
    return {'reference_height_cm':reference,'scale_factor':height/reference,
            'height_post_scaling':subject_type=='bjd','training_height_range_cm':[lo,hi],
            'requested_height_outside_training_range':not lo<=height<=hi}


def validate_measurements(measurements,height_cm):
    height=float(height_cm)
    if not math.isfinite(height) or height<=0:raise ValueError('尺寸档案中的身高无效。')
    if set(measurements)!=set(MEASUREMENT_KEYS):raise ValueError('尺寸档案缺少完整的13项指标。')
    if any(not math.isfinite(float(v)) or float(v)<=0 for v in measurements.values()):
        raise ValueError('模型输出存在无效尺寸，未生成尺寸档案。')
    for key,name in LINEAR_LENGTHS.items():
        if float(measurements[key])>height:
            raise ValueError(f'模型结果不合理：{name}{float(measurements[key]):.2f}cm超过身高{height:g}cm，已阻止展示和导出。')


def convert_reference_measurements(reference_measurements,height_cm,context):
    validate_measurements(reference_measurements,context['reference_height_cm'])
    decimals=2 if context['height_post_scaling'] else 1
    measurements={key:round(float(reference_measurements[key])*context['scale_factor'],decimals)
                  for key in MEASUREMENT_KEYS}
    validate_measurements(measurements,height_cm)
    return measurements


def validate_result(result):
    if result.get('pipeline_version')!=PIPELINE_VERSION:
        raise ValueError('这份结果来自旧版预测流程，已停止展示和导出，请重新预测。')
    height=float(result['input_metadata']['height_cm'])
    validate_measurements(result['measurements_cm'],height)
    reference=float(result['reference_height_cm']);factor=float(result['scale_factor'])
    if not math.isfinite(reference) or reference<=0 or not math.isfinite(factor) or factor<=0:
        raise ValueError('尺寸换算参数无效。')
    if not math.isclose(factor,height/reference,rel_tol=1e-7):
        raise ValueError('尺寸档案中的缩放比例与身高不一致。')
    if result.get('subject_type')=='bjd' and result.get('height_post_scaling') is not True:
        raise ValueError('人偶结果未执行身高等比例换算，已停止导出。')
