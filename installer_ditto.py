"""Isolated, pinned Windows Ditto installation policy."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import uuid
import shutil
import os


def ditto_torch_install_plan() -> tuple[tuple[str, ...], str, str]:
    return (('torch==2.7.1', 'torchvision==0.22.1'),
            'https://download.pytorch.org/whl/cu128',
            'Ditto uses pinned PyTorch 2.7.1 / CUDA 12.8 for standard RTX and Blackwell GPUs.')


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda: handle.read(8 * 1024**2), b''):
            digest.update(block)
    return digest.hexdigest()


def _contained(root: Path, name: str) -> Path:
    relative = PurePosixPath(name)
    if not name or relative.is_absolute() or '\\' in name or ':' in name or '..' in relative.parts:
        raise ValueError(f'Invalid Ditto inventory path: {name}')
    path = (root / name).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError(f'Ditto inventory escaped its root: {name}')
    return path


def verify_ditto_runtime_bundle(root: Path) -> None:
    """Check the bundled source inventory without preparing an environment."""
    root = Path(root).resolve()
    inventory = json.loads((root / 'runtime-manifest.json').read_text(encoding='utf-8'))
    if not isinstance(inventory, dict) or not isinstance(inventory.get('files'), dict):
        raise ValueError('Ditto runtime inventory must contain a files object.')
    for name, checksum in inventory['files'].items():
        path = _contained(root, name)
        if not path.is_file() or _sha256(path) != checksum:
            raise ValueError(f'Ditto runtime bundle is missing or modified: {name}. Repair the source bundle.')


def ensure_ditto_models(root: Path, *, download_file) -> dict:
    root = Path(root).resolve()
    manifest = json.loads((root / 'model-manifest.json').read_text(encoding='utf-8'))
    revision = manifest.get('revision', '')
    if manifest.get('schema_version') != 1 or not re.fullmatch('[0-9a-f]{40}', revision):
        raise ValueError('Ditto model inventory needs an immutable repository revision.')
    if manifest.get('repository') != 'digital-avatar/ditto-talkinghead':
        raise ValueError('Unexpected Ditto checkpoint repository.')
    entries = []
    for item in manifest['files']:
        name = item['path']
        path = _contained(root / 'checkpoints', name)
        if type(item['size']) is not int or item['size'] <= 0 or not re.fullmatch('[0-9a-f]{64}', item['sha256']):
            raise ValueError(f'Invalid Ditto model size/checksum: {name}')
        entries.append((item, path))
    report = {'reused': 0, 'downloaded': 0, 'revision': revision}
    for item, path in entries:
        if path.is_file() and path.stat().st_size == item['size'] and _sha256(path) == item['sha256']:
            report['reused'] += 1
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + '.download-' + uuid.uuid4().hex)
        try:
            url = f'https://huggingface.co/{manifest["repository"]}/resolve/{revision}/{item["path"]}'
            download_file(url, temporary)
            if temporary.stat().st_size != item['size'] or _sha256(temporary) != item['sha256']:
                raise ValueError(f'Ditto checkpoint checksum mismatch: {item["path"]}; previous file preserved.')
            temporary.replace(path)
            report['downloaded'] += 1
        finally:
            temporary.unlink(missing_ok=True)
    return report


VERIFY_CODE = r'''
import importlib.metadata as metadata
import json, sys, tempfile
from pathlib import Path
if sys.version_info[:2] != (3, 11):
    raise RuntimeError('Ditto installer requires Python 3.11')
for package, wanted in {'torch':'2.7.1','torchvision':'0.22.1','numpy':'1.26.4',
                         'onnxruntime-gpu':'1.22.0','mediapipe':'0.10.21'}.items():
    actual = metadata.version(package).split('+')[0]
    if actual != wanted:
        raise RuntimeError(f'Ditto dependency mismatch: {package} {actual}, expected {wanted}')
import numpy as np
from ditto_blend import blend_images_cy
import torch
if torch.version.cuda != '12.8' or not torch.cuda.is_available():
    raise RuntimeError('Ditto CUDA 12.8 cannot execute. Check the NVIDIA GPU/driver; CPU fallback is disabled.')
x = torch.ones((64,64), device='cuda')
y = x @ x
torch.cuda.synchronize()
if not torch.isfinite(y).all().item() or y[0,0].item() != 64:
    raise RuntimeError('Ditto CUDA execution verification failed')
import onnx, onnxruntime as ort
ort.preload_dlls()
if 'CUDAExecutionProvider' not in ort.get_available_providers():
    raise RuntimeError('ONNX Runtime CUDA provider is unavailable')
from onnx import helper, TensorProto
graph = helper.make_graph([helper.make_node('MatMul',['a','b'],['c'])], 'ditto_cuda_check',
    [helper.make_tensor_value_info(n,TensorProto.FLOAT,[64,64]) for n in ('a','b')],
    [helper.make_tensor_value_info('c',TensorProto.FLOAT,[64,64])])
model = helper.make_model(graph,opset_imports=[helper.make_opsetid('',17)])
model.ir_version = 9
with tempfile.TemporaryDirectory(prefix='ditto-cuda-check-') as folder:
    options = ort.SessionOptions()
    options.enable_profiling = True
    options.profile_file_prefix = str(Path(folder)/'ort-profile')
    session = ort.InferenceSession(model.SerializeToString(),sess_options=options,
                                  providers=['CUDAExecutionProvider'])
    session.disable_fallback()
    out = session.run(None,dict(a=np.ones((64,64),np.float32),b=np.ones((64,64),np.float32)))[0]
    profile = json.loads(Path(session.end_profiling()).read_text(encoding='utf-8'))
    if not np.allclose(out,64) or not any(e.get('args',{}).get('provider')=='CUDAExecutionProvider'
                                        and e.get('args',{}).get('op_name')=='MatMul' for e in profile):
        raise RuntimeError('ONNX MatMul did not execute on CUDA; CPU fallback is disabled')
    del session
import mediapipe, cv2, librosa
print('DITTO_VERIFY='+json.dumps(dict(python=sys.version.split()[0],torch=torch.__version__,
    cuda=torch.version.cuda,gpu=torch.cuda.get_device_name(),
    onnxruntime=ort.__version__,onnx_cuda_executed=True,native_blender=True)))
'''


def verify_ditto_runtime(python: Path, root: Path, *, run_command) -> dict:
    run_command([str(python), '-m', 'pip', 'check'], cwd=root)
    result = run_command([str(python), '-c', VERIFY_CODE], cwd=root, capture=True)
    records = [line.removeprefix('DITTO_VERIFY=') for line in result.stdout.splitlines()
               if line.startswith('DITTO_VERIFY=')]
    if not records:
        raise RuntimeError('Ditto runtime verification returned no success evidence.')
    return json.loads(records[-1])


def ensure_ditto_ffmpeg(installer, python: Path) -> None:
    scripts = Path(python).parent
    names = ('ffmpeg','ffprobe')
    def works(path):
        # An executable copied from Conda may depend on DLLs outside this venv.
        # Verify with only the runtime and Windows system folders in PATH.
        env = {**os.environ,'PATH':os.pathsep.join((str(scripts),str(Path(os.environ.get('WINDIR','C:/Windows'))/'System32')))}
        try:
            result = subprocess.run([str(path),'-version'],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                timeout=15,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            return result.returncode == 0
        except (OSError,subprocess.TimeoutExpired):
            return False
    def copy_tool(name):
        destination = scripts/(name+'.exe')
        source = installer.resolve_ffmpeg_binary(name)
        if source is None or not Path(source).is_file():
            raise ValueError(f'Ditto requires {name}; bundled FFmpeg setup did not provide it.')
        pending = destination.with_name(destination.name+'.install-'+uuid.uuid4().hex)
        try:
            shutil.copyfile(source,pending)
            pending.replace(destination)
        finally:
            pending.unlink(missing_ok=True)
    for name in names:
        if not (scripts/(name+'.exe')).is_file():
            copy_tool(name)
    broken = [name for name in names if not works(scripts/(name+'.exe'))]
    if broken:
        installer.ensure_ffmpeg(force=True)
        for name in broken:
            copy_tool(name)
            if not works(scripts/(name+'.exe')):
                raise ValueError(f'Ditto {name} cannot run independently in its environment.')


def install_ditto(installer, *, root: Path) -> None:
    from install_neural_companion import get_python_minor_version, headline, note, ok, run_command
    root = Path(root).resolve()
    wheels = list((root / 'wheels').glob('ditto_native_blend-*-cp311-cp311-win_amd64.whl'))
    if len(wheels) != 1:
        raise ValueError('Ditto requires its bundled Windows x64 Python 3.11 native wheel. Repair the source bundle.')
    verify_ditto_runtime_bundle(root)
    headline('Installing Ditto')
    note(ditto_torch_install_plan()[2])
    venv = root / '.venv'
    existing_python = venv / 'Scripts/python.exe'
    if existing_python.is_file() and get_python_minor_version([str(existing_python)]) != '3.11':
        raise ValueError('Existing Ditto environment is not Python 3.11; it was preserved. Rename it before installing a fresh environment.')
    python = installer.ensure_venv(venv, 'Ditto')
    note('Upgrading Ditto pip/setuptools/wheel...')
    # Python 3.11's bundled pip can reject normalized wheel metadata names.
    # Bootstrap from PyPI before switching to the CUDA-specific torch index.
    installer.pip_install(python, 'install', '--upgrade', 'pip', 'setuptools<81', 'wheel',
                          '--index-url', 'https://pypi.org/simple')
    packages, index, _ = ditto_torch_install_plan()
    installer.pip_install(python, 'install', *packages, '--index-url', index)
    installer.pip_install(python, 'install', '-r', str(root / 'requirements-windows-py311.lock'), str(wheels[0]))
    installer.ensure_ffmpeg()
    ensure_ditto_ffmpeg(installer,python)
    models = ensure_ditto_models(root, download_file=installer.download_file)
    note(f'Ditto checkpoints: {models["reused"]} reused, {models["downloaded"]} downloaded and verified.')
    report = verify_ditto_runtime(python, root, run_command=run_command)
    installer.ditto_verification = report
    ok(f'Ditto ready in its own environment: {report["gpu"]}, CUDA {report["cuda"]}; ONNX CUDA and native blender verified.')
