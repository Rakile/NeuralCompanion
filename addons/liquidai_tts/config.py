"""Lightweight LiquidAI provider settings and managed paths; no model imports."""
from dataclasses import dataclass
import math
from pathlib import Path
import json

MODEL_ID = 'LiquidAI/LFM3-Audio-2B'
REVISION = 'cddb56b5ec9b4703f9b3b2d0500143d1fff2fee0'
LANGUAGES = ('American English','British English','Swedish','Danish','Finnish','German','French','Spanish','Italian','Portuguese','Dutch','Polish','Greek','Turkish','Arabic','Hebrew','Japanese','Korean','Chinese')
DEFAULTS = {
 'liquidai_tts_python':'', 'liquidai_tts_model_dir':'',
 'liquidai_tts_language':'American English', 'liquidai_tts_voice':'female',
 'liquidai_tts_seed':0, 'liquidai_tts_temperature':1.0,
 'liquidai_tts_top_k':128, 'liquidai_tts_repetition_penalty':1.1,
 'liquidai_tts_max_tokens':1024, 'liquidai_tts_prewarm_on_start':True,
 'liquidai_tts_stream_audio':False, 'liquidai_tts_startup_buffer_seconds':1.0,
}

@dataclass(frozen=True)
class ManagedPaths:
    root: Path
    environment: Path
    python: Path
    model_dir: Path
    cache: Path
    work: Path


def managed_paths(root):
    import os
    root=Path(root).resolve()
    env=root/'.venvs'/'liquidai_tts'
    python=env/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
    return ManagedPaths(root,env,python,root/'models'/'LFM3-Audio-2B',root/'runtime'/'liquidai_tts'/'cache',root/'runtime'/'temp'/'liquidai_tts')


def normalize_settings(values):
    source=dict(values or {})
    result={key:source.get(key,default) for key,default in DEFAULTS.items()}
    for key in ('liquidai_tts_python','liquidai_tts_model_dir'):
        result[key]=str(result[key] or '').strip()
    if result['liquidai_tts_language'] not in LANGUAGES:
        raise ValueError('Choose a listed LiquidAI speech language.')
    if __package__:
        from .voices import normalize_voice
    else:
        from voices import normalize_voice
    result['liquidai_tts_voice'] = normalize_voice(result['liquidai_tts_voice'])
    for key,minimum,maximum,integer in [
      ('liquidai_tts_seed',0,2**32-1,True),('liquidai_tts_temperature',.05,2.,False),
      ('liquidai_tts_top_k',0,2016,True),('liquidai_tts_repetition_penalty',1.,3.,False),
      ('liquidai_tts_max_tokens',32,4096,True),
      ('liquidai_tts_startup_buffer_seconds',.2,2.,False)]:
        try:
            if isinstance(result[key], bool): raise ValueError("Use a number, not a switch value.")
            value=float(result[key])
        except (TypeError, ValueError) as error:
            raise ValueError(f"Invalid LiquidAI setting {key}: enter a number.") from error
        if not math.isfinite(value) or not minimum<=value<=maximum or (integer and value!=int(value)):
            raise ValueError(f'Invalid LiquidAI setting {key}: use {minimum}–{maximum}.')
        result[key]=int(value) if integer else value
    for key in ('liquidai_tts_prewarm_on_start', 'liquidai_tts_stream_audio'):
        value=result[key]
        result[key]=str(value).lower() not in ('false','no','off','0','') if isinstance(value,str) else bool(value)
    return result


def voice_prompt(settings, adapter=None):
    if adapter is None and settings['liquidai_tts_voice'] not in ('female','male'):
        raise ValueError('Resolve the installed voice adapter before building its prompt.')
    voice = f"{adapter['prompt_name']}'s voice" if adapter is not None else f"a {settings['liquidai_tts_voice']} voice"
    return f"Perform TTS in {settings['liquidai_tts_language']} using {voice}."


def validate_model_folder(path):
    folder=Path(path)
    required=('config.json','model.safetensors','preprocessor_config.json','processor_config.json','tokenizer_config.json','tokenizer.json','special_tokens_map.json','chat_template.jinja','generation_config.json','modeling_lfm3_audio.py','modeling_lfm3.py','lfm3_conv.py','processing_lfm3_audio.py','feature_extraction_lfm3_audio.py','configuration_lfm3_audio.py','configuration_lfm3.py','modeling_liquid_codec.py','configuration_liquid_codec.py','audio_tokenizer/model.safetensors','audio_tokenizer/config.json','LICENSE')
    missing=[name for name in required if not (folder/name).is_file()]
    if missing:
        raise ValueError('LiquidAI model files are missing; use Install / Repair. Missing: '+', '.join(missing))
    config=json.loads((folder/'config.json').read_text(encoding='utf-8'))
    if config.get('model_type')!='lfm3_audio':
        raise ValueError('The selected folder is not an LFM3 Audio checkpoint.')
    revision=folder/'PINNED_REVISION'
    if not revision.is_file() or revision.read_text(encoding='utf-8').strip()!=REVISION:
        raise ValueError('LiquidAI checkpoint revision is unverified or incompatible; install the pinned model.')
    return folder.resolve()
