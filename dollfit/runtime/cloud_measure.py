"""CPU ONNX inference for the SAME trained floating-point height/gender network."""
import gc
import hashlib
import json
import os
from pathlib import Path
import sys

import numpy as np
from PIL import Image
from .scale_policy import scale_context, convert_reference_measurements, MEASUREMENT_KEYS

ROOT = Path(__file__).resolve().parents[1]


def options():
    import onnxruntime as ort
    opt = ort.SessionOptions()
    opt.intra_op_num_threads = int(os.environ.get('INFERENCE_THREADS', '1'))
    opt.inter_op_num_threads = 1
    opt.enable_cpu_mem_arena = False
    opt.enable_mem_pattern = False
    opt.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_BASIC
    return opt


def normalize_mask(image):
    array = np.asarray(image.convert('L')) > 127
    yy, xx = np.nonzero(array)
    if len(xx) < 20:
        raise ValueError('轮廓为空或太小，请检查照片。')
    cropped = Image.fromarray(array.astype(np.uint8) * 255).crop(
        (int(xx.min()), int(yy.min()), int(xx.max()) + 1, int(yy.max()) + 1))
    cropped.thumbnail((208, 208), Image.Resampling.NEAREST)
    out = Image.new('L', (224, 224), 0)
    out.paste(cropped, ((224 - cropped.width) // 2, (224 - cropped.height) // 2))
    return np.array(out, dtype=np.uint8)


def photo_masks(paths):
    import cv2
    import onnxruntime as ort
    session = None
    masks = []
    for path in paths:
        with Image.open(path) as source:
            rgba = np.array(source.convert('RGBA'))
        rgb = rgba[:, :, :3]
        border = np.concatenate((rgb[0], rgb[-1], rgb[:, 0], rgb[:, -1]))
        gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
        if np.any(rgba[:, :, 3] < 250):
            raw = rgba[:, :, 3] > 127
        elif np.isin(gray, [0, 255]).mean() > .995 and np.mean(border) < 40:
            raw = gray > 127
        elif np.mean(np.min(border, axis=1) > 245) > .98:
            raw = np.max(255 - rgb.astype(np.int16), axis=2) > 25
        else:
            if session is None:
                session = ort.InferenceSession(str(ROOT / 'models/u2netp.onnx'), options(), providers=['CPUExecutionProvider'])
            small = Image.fromarray(rgb).resize((320, 320), Image.Resampling.LANCZOS)
            values = np.asarray(small, dtype=np.float32)
            values /= max(float(np.max(values)), 1.)
            values = (values - np.array([.485, .456, .406], np.float32)) / np.array([.229, .224, .225], np.float32)
            tensor = values.transpose(2, 0, 1)[None].astype(np.float32)
            pred = session.run(None, {session.get_inputs()[0].name: tensor})[0][0, 0]
            pred = (pred - pred.min()) / max(float(pred.max() - pred.min()), 1e-8)
            alpha = Image.fromarray((pred * 255).astype('uint8')).resize((rgb.shape[1], rgb.shape[0]), Image.Resampling.LANCZOS)
            raw = np.asarray(alpha) > 127
        count, labels, stats, _ = cv2.connectedComponentsWithStats(raw.astype(np.uint8), connectivity=8)
        if count < 2:
            raise ValueError('未识别到娃体轮廓，请使用背景清晰、主体完整的照片。')
        index = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
        mask = (labels == index).astype('uint8') * 255
        if not .005 < float((mask > 0).mean()) < .95:
            raise ValueError('娃体分割异常，请调整背景后重拍。')
        masks.append(normalize_mask(Image.fromarray(mask)))
    del session
    gc.collect()
    if np.array_equal(*masks):
        raise ValueError('正面与左侧面轮廓相同，请提供不同视角。')
    return masks


def predict(front, side, height, gender):
    import onnxruntime as ort
    if gender not in ('female', 'male'):
        raise ValueError('模型性别分类无效。')
    info = json.loads((ROOT / 'models/model_metadata.json').read_text(encoding='utf-8'))
    context = scale_context(height, 'bjd', info)
    masks = photo_masks([front, side])
    mean = np.array([.485, .456, .406], np.float32)[None, :, None, None]
    std = np.array([.229, .224, .225], np.float32)[None, :, None, None]
    images = [(np.repeat(m[None, None], 3, axis=1).astype(np.float32) / 255. - mean) / std for m in masks]
    metadata = np.array([[(context['reference_height_cm'] - info['height_mean']) / info['height_std'], float(gender == 'female')]], np.float32)
    session = ort.InferenceSession(str(ROOT / 'models/bodym.onnx'), options(), providers=['CPUExecutionProvider'])
    output = session.run(None, {'front': images[0], 'side': images[1], 'metadata': metadata})[0][0]
    values = output * np.asarray(info['label_std']) + np.asarray(info['label_mean'])
    reference = dict(zip(MEASUREMENT_KEYS, map(float, values)))
    measured = convert_reference_measurements(reference, height, context)
    return {'status': 'succeeded', 'rows': [{'name': n, 'value': measured[k]} for k, n in zip(MEASUREMENT_KEYS, info['labels_zh'])],
            'measurements_cm': measured, 'reference_measurements_cm': reference, **context,
            'uses_weight': False, 'runtime': 'onnx-fp32-cpu', 'bjd_validated': False,
            'note': '同一人体神经网络的浮点ONNX推理，按输入身高等比例换算。BJD精度尚未验证，不能直接用于裁衣。'}


if __name__ == '__main__':
    config = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
    result = predict(config['front'], config['side'], config['height_cm'], config['gender'])
    Path(sys.argv[2]).write_text(json.dumps(result, ensure_ascii=False), encoding='utf-8')
