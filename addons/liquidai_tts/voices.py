"""Read local voice packages without importing model libraries or weights."""
import json
from pathlib import Path

if __package__:
    from .config import MODEL_ID
else:
    from config import MODEL_ID

BUILTIN_VOICES = ('female', 'male')


def normalize_voice(value):
    if not isinstance(value, str):
        raise ValueError('Choose a built-in or installed LiquidAI voice.')
    value = value.strip()
    if not value or len(value) > 256 or any(c in value for c in '/\\\r\n\0'):
        raise ValueError('Invalid LiquidAI voice selection.')
    name = value[8:] if value.startswith('adapter:') else value
    if not name or name in ('.', '..') or ':' in name:
        raise ValueError('Invalid LiquidAI voice folder.')
    return value.lower() if value.lower() in BUILTIN_VOICES else value


def _label(folder_name):
    name = folder_name
    prefix = MODEL_ID.split('/')[-1] + '-'
    if name.lower().startswith(prefix.lower()):
        name = name[len(prefix):]
    for suffix in ('-lora', '_lora'):
        if name.lower().endswith(suffix):
            name = name[:-len(suffix)]
            break
    return name.strip(' _-') or folder_name


def _read_json(path, limit=65536):
    if path.stat().st_size > limit:
        raise ValueError(f'Voice metadata is too large: {path.name}')
    value = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(value, dict):
        raise ValueError(f'Voice metadata must be an object: {path.name}')
    return value


def _name(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 120 or any(c in value for c in '\r\n\0<>'):
        raise ValueError('Voice names must be short, nonempty single-line text.')
    return value.strip()


def _inspect(root, folder):
    root, folder = Path(root).resolve(), Path(folder)
    resolved = folder.resolve()
    if not resolved.is_relative_to(root) or resolved == root:
        raise ValueError('Voice adapter folder is outside the models directory.')
    config_path, weights = resolved/'adapter_config.json', resolved/'adapter_model.safetensors'
    if not config_path.is_file() or not weights.is_file() or not weights.stat().st_size:
        raise ValueError(f'Missing voice adapter config or safetensors weights: {folder.name}')
    config = _read_json(config_path)
    if config.get('peft_type') != 'LORA':
        raise ValueError(f'Voice adapter must use LoRA (peft_type LORA): {folder.name}')
    initialization = config.get('init_lora_weights',True)
    standard_init = initialization is True or initialization is False or initialization == 'gaussian'
    if (not standard_init or config.get('bias','none') != 'none'
            or any(config.get(key) for key in ('layer_replication','modules_to_save','trainable_token_indices','target_parameters'))):
        raise ValueError('Only standard LoRA voice adapters that leave base weights unchanged are supported for voice switching.')
    base = str(config.get('base_model_name_or_path') or '').replace('\\', '/').rstrip('/').split('/')[-1]
    architecture = (config.get('auto_mapping') or {}).get('base_model_class') if isinstance(config.get('auto_mapping') or {},dict) else ''
    if base.casefold() != MODEL_ID.split('/')[-1].casefold() and architecture != 'Lfm3AudioForConditionalGeneration':
        raise ValueError(f'Voice adapter is not identified as compatible with {MODEL_ID}: {folder.name}')
    metadata_path = resolved/'voice.json'
    metadata = _read_json(metadata_path,16384) if metadata_path.is_file() else {}
    name = _name(metadata.get('name', _label(folder.name)))
    prompt_name = _name(metadata.get('prompt_name', name))
    fingerprint = [str(resolved)]
    for path in (config_path, weights, metadata_path):
        stat = path.stat() if path.exists() else None
        fingerprint.extend([stat.st_size,stat.st_mtime_ns] if stat else [0,0])
    return {'id':'adapter:'+folder.name, 'name':name, 'prompt_name':prompt_name,
            'path':str(resolved), 'fingerprint':fingerprint,
            'aliases':list(dict.fromkeys([folder.name,_label(folder.name),name,prompt_name]))}


def _roots(models_dir, model_dir=None):
    roots = [Path(models_dir).expanduser().resolve()]
    if model_dir is not None:
        parent = Path(model_dir).expanduser().resolve().parent
        if parent not in roots:
            roots.append(parent)
    return roots


def discover_voice_adapters(models_dir, model_dir=None):
    voices, seen = [], set()
    for root in _roots(models_dir,model_dir):
        try:
            folders = sorted(root.iterdir(),key=lambda p:p.name.casefold())
        except OSError:
            continue
        for folder in folders:
            if folder.name.casefold() in seen:
                continue
            # A primary path owns its name even if its package is incomplete.
            # Resolution must never silently substitute a different root's voice.
            seen.add(folder.name.casefold())
            try:
                if not folder.is_dir() or not (folder/'adapter_config.json').is_file():
                    continue
                voice = _inspect(root,folder)
            except (OSError,ValueError,RuntimeError):
                continue
            voices.append(voice)
    return sorted(voices,key=lambda v:(v['name'].casefold(),v['id'].casefold()))


def matching_voices(value, voices):
    key = value.casefold()
    if key in BUILTIN_VOICES:
        return []
    exact = [v for v in voices if v['id'].casefold()==key]
    return exact or [v for v in voices if any(a.casefold()==key for a in v.get('aliases',[v['name']]))]


def resolve_voice_adapter(value, models_dir, model_dir=None):
    value = normalize_voice(value)
    if value in BUILTIN_VOICES:
        return None
    roots = _roots(models_dir,model_dir)
    if value.startswith('adapter:'):
        for root in roots:
            folder = root/value[8:]
            if folder.exists():
                return _inspect(root,folder)
    else:
        matches = matching_voices(value,discover_voice_adapters(models_dir,model_dir))
        if len(matches)==1:
            return matches[0]
        if len(matches)>1:
            raise ValueError('More than one voice adapter matches this saved name. Refresh voices and select its folder.')
    raise ValueError(f'Voice adapter {value!r} not found. Put its LoRA folder in {roots[0]} and refresh voices.')
