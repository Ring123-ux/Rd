"""Restore checked model assets from GitHub-web-upload-sized parts."""
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    result = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def restore(root=ROOT):
    root = Path(root).resolve()
    manifest = json.loads((root / 'bundled' / 'manifest.json').read_text(encoding='utf-8'))
    for asset in manifest['assets']:
        target = (root / asset['target']).resolve()
        if not target.is_relative_to(root):
            raise ValueError('Invalid asset path')
        if target.is_file() and target.stat().st_size == asset['bytes'] and digest(target) == asset['sha256']:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(target.suffix + '.assembling')
        with temporary.open('wb') as output:
            for part in asset['parts']:
                source = (root / 'bundled' / part['file']).resolve()
                if not source.is_relative_to(root / 'bundled') or digest(source) != part['sha256']:
                    raise ValueError('模型分片缺失/损坏，请重新上传 bundled 文件夹。')
                with source.open('rb') as stream:
                    for block in iter(lambda: stream.read(1024 * 1024), b''):
                        output.write(block)
        if temporary.stat().st_size != asset['bytes'] or digest(temporary) != asset['sha256']:
            temporary.unlink(missing_ok=True)
            raise ValueError('Asset integrity check failed')
        temporary.replace(target)
    return manifest


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] != 'restore':
        raise SystemExit('Usage: python -m deployment.assets restore')
    result = restore()
    print('Verified and restored', len(result['assets']), 'assets.')
