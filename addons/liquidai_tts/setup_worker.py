"""Private setup entry point. Imported discovery never runs setup or downloads."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from addons.liquidai_tts.config import MODEL_ID, REVISION, managed_paths, validate_model_folder
from addons.liquidai_tts.installer import READY_FILE, READY_STATE, child_environment
from installer_storage import cleanup_setup_caches

REQUIRED_MODEL_FILES = (
    'config.json', 'model.safetensors', 'preprocessor_config.json', 'processor_config.json',
    'tokenizer_config.json', 'tokenizer.json', 'special_tokens_map.json', 'generation_config.json',
    'chat_template.jinja', 'LICENSE',
    'configuration_lfm3_audio.py', 'configuration_lfm3.py', 'configuration_liquid_codec.py',
    'modeling_lfm3_audio.py', 'modeling_lfm3.py', 'modeling_liquid_codec.py',
    'processing_lfm3_audio.py', 'feature_extraction_lfm3_audio.py', 'lfm3_conv.py',
    'audio_tokenizer/config.json', 'audio_tokenizer/model.safetensors',
)


def contain_children():
    """Contain every setup descendant, including Windows venv launcher children.

    The non-inheritable job handle intentionally lives until this process exits.
    Its OS closure on cancellation/crash also kills any surviving descendants.
    POSIX uses the process group created by LiquidAIInstaller instead.
    """
    if os.name != 'nt':
        return None
    import ctypes
    from ctypes import wintypes

    class BasicLimits(ctypes.Structure):
        _fields_ = [('process_time', ctypes.c_longlong), ('job_time', ctypes.c_longlong),
            ('flags', wintypes.DWORD), ('minimum_working_set', ctypes.c_size_t),
            ('maximum_working_set', ctypes.c_size_t), ('active_processes', wintypes.DWORD),
            ('affinity', ctypes.c_size_t), ('priority', wintypes.DWORD), ('scheduling', wintypes.DWORD)]
    class IOCounters(ctypes.Structure):
        _fields_ = [(name, ctypes.c_ulonglong) for name in
            ('read_operations', 'write_operations', 'other_operations', 'read_bytes', 'write_bytes', 'other_bytes')]
    class ExtendedLimits(ctypes.Structure):
        _fields_ = [('basic', BasicLimits), ('io', IOCounters), ('process_memory', ctypes.c_size_t),
            ('job_memory', ctypes.c_size_t), ('peak_process_memory', ctypes.c_size_t), ('peak_job_memory', ctypes.c_size_t)]
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    kernel.CreateJobObjectW.restype = wintypes.HANDLE
    kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    kernel.SetInformationJobObject.restype = wintypes.BOOL
    kernel.GetCurrentProcess.argtypes = []
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel.AssignProcessToJobObject.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    job = kernel.CreateJobObjectW(None, None)
    if not job:
        raise RuntimeError('Cannot contain LiquidAI setup processes safely.')
    limits = ExtendedLimits()
    limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if (not kernel.SetInformationJobObject(job, 9, ctypes.byref(limits), ctypes.sizeof(limits))
            or not kernel.AssignProcessToJobObject(job, kernel.GetCurrentProcess())):
        kernel.CloseHandle(job)
        raise RuntimeError('Cannot contain LiquidAI setup processes safely.')
    return job


def ensure_managed_paths(paths):
    """Reject symlinks/junctions redirected outside the installation before writes."""
    # A redirected directory could target NC's main .venv even inside root.
    # The venv Python itself may legitimately symlink to the system interpreter
    # on POSIX; setup never writes through that executable.
    for path in (paths.environment, paths.model_dir, paths.cache, paths.work):
        if path.resolve() != path or not path.is_relative_to(paths.root):
            raise ValueError(f'LiquidAI managed directory is redirected: {path}')


def dependency_commands(paths, uv=None):
    requirements = str(Path(__file__).with_name('requirements.txt'))
    if uv:
        prefix = [str(uv), '--no-config', '--quiet', 'pip', 'install', '--link-mode', 'copy', '--python', str(paths.python)]
    else:
        prefix = [str(paths.python), '-m', 'pip', 'install', '--disable-pip-version-check']
    return [prefix + ['torch==2.11.0', '--index-url', 'https://download.pytorch.org/whl/cu128'],
            prefix + ['-r', requirements]]


def finalize_model(model_dir):
    """Write the pin only after weights, codec, custom code and license exist."""
    folder = Path(model_dir)
    marker = folder / 'PINNED_REVISION'
    marker.unlink(missing_ok=True)
    missing = [name for name in REQUIRED_MODEL_FILES
               if not (folder / name).is_file() or (folder / name).stat().st_size == 0]
    if missing:
        raise ValueError('Incomplete LiquidAI checkpoint; missing: ' + ', '.join(missing))
    config = json.loads((folder / 'config.json').read_text(encoding='utf-8'))
    if config.get('model_type') != 'lfm3_audio':
        raise ValueError('Downloaded checkpoint is not LFM3 Audio.')
    marker.write_text(REVISION + '\n', encoding='utf-8')
    try:
        validate_model_folder(folder)
    except Exception:
        marker.unlink(missing_ok=True)
        raise


def download_model(paths):
    # Imported only inside the private Python3.12 environment, after installation.
    from huggingface_hub import snapshot_download
    paths.model_dir.mkdir(parents=True, exist_ok=True)
    (paths.model_dir / 'PINNED_REVISION').unlink(missing_ok=True)
    print(f'Downloading {MODEL_ID} at {REVISION}; interrupted downloads can resume', flush=True)
    snapshot_download(repo_id=MODEL_ID, revision=REVISION, local_dir=str(paths.model_dir),
                      ignore_patterns=['assets/*', '.gitattributes'])
    finalize_model(paths.model_dir)
    print('Pinned model, audio codec, custom code and original LICENSE verified', flush=True)


def setup(app_root):
    if sys.version_info[:2] != (3, 12):
        raise RuntimeError('LiquidAI setup requires an installed Python 3.12 interpreter.')
    paths = managed_paths(app_root)
    ensure_managed_paths(paths)
    # Retain the handle until process exit; do not close it while setup is active.
    job = contain_children()
    for folder in (paths.environment.parent, paths.cache, paths.work, paths.model_dir.parent):
        folder.mkdir(parents=True, exist_ok=True)
    marker = paths.environment / READY_FILE
    marker.unlink(missing_ok=True)
    env = child_environment(paths)
    # This is the disposable setup child; HF imports below also need private caches.
    os.environ.update(env)
    config = paths.environment / 'pyvenv.cfg'
    compatible = (paths.python.is_file() and config.is_file()
                  and any(line.strip().startswith('version = 3.12.') for line in config.read_text().splitlines()))
    if not compatible:
        print('Creating private Python 3.12 environment', flush=True)
        subprocess.run([sys.executable, '-m', 'venv', '--clear', str(paths.environment)], check=True, env=env)
    uv = shutil.which('uv')
    print('Installing pinned CUDA 12.8 runtime packages' + (' using uv wheel cache' if uv else ' using pip wheel cache'), flush=True)
    for command in dependency_commands(paths, uv=uv):
        subprocess.run(command, check=True, env=env)
    subprocess.run([str(paths.python), '-u', str(Path(__file__).resolve()), '--download', str(paths.root)], check=True, env=env)
    # Verify package versions and native audio imports without allocating a model.
    subprocess.run([str(paths.python), '-I', '-c',
        'import sys,torch,transformers,accelerate,librosa,soundfile,peft; '
        'assert sys.version_info[:2]==(3,12); '
        'assert torch.__version__.split("+")[0]=="2.11.0"; '
        'assert torch.version.cuda=="12.8"; '
        'assert transformers.__version__=="5.22.1"; '
        'assert peft.__version__=="0.21.2"'], check=True, env=env)
    validate_model_folder(paths.model_dir)
    marker.write_text(json.dumps(READY_STATE, sort_keys=True) + '\n', encoding='utf-8')
    cleanup_setup_caches(paths.root, caches=(
        'runtime/liquidai_tts/cache/pip', 'runtime/liquidai_tts/cache/uv'),
        progress=lambda text: print(text, flush=True))
    print('LiquidAI runtime ready', flush=True)
    # job deliberately remains open until process exit, including exception exits.
    return job


def main():
    try:
        if len(sys.argv) == 3 and sys.argv[1] == '--download':
            paths = managed_paths(sys.argv[2])
            ensure_managed_paths(paths)
            os.environ.update(child_environment(paths))
            download_model(paths)
        elif len(sys.argv) == 2:
            setup(sys.argv[1])
        else:
            raise ValueError('Usage: setup_worker.py NC_ROOT')
        return 0
    except Exception as exc:
        print(f'LiquidAI setup failed: {exc}', file=sys.stderr, flush=True)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
