"""Independent disposable-video cache preferences; no audio/stream settings."""
import json
import os
from pathlib import Path

DEFAULT = dict(enabled=True,preset='balanced',revision=0,clear_generation=0)

def load_settings(root):
    try:
        value=json.loads((Path(root)/'idle-cache-settings.json').read_text('utf-8'))
        if (set(value)!=set(DEFAULT) or type(value['enabled']) is not bool
                or value['preset'] not in {'low','balanced','high'}
                or any(type(value[k]) is not int or not 0<=value[k]<=2**53-1 for k in ('revision','clear_generation'))):
            raise ValueError('Invalid idle settings')
        return value
    except (OSError,ValueError,TypeError):return dict(DEFAULT)

def save_settings(root,patch):
    if (not isinstance(patch,dict) or not patch or not set(patch)<={'enabled','preset','clear'}
            or ('enabled' in patch and type(patch['enabled']) is not bool)
            or ('preset' in patch and patch['preset'] not in {'low','balanced','high'})
            or ('clear' in patch and patch['clear'] is not True)):
        raise ValueError('Invalid idle cache setting')
    value=load_settings(root)
    for key in ('enabled','preset'):
        if key in patch:value[key]=patch[key]
    value['revision']+=1
    if patch.get('clear'):value['clear_generation']+=1
    target=Path(root)/'idle-cache-settings.json'
    target.parent.mkdir(parents=True,exist_ok=True)
    temporary=target.with_suffix('.tmp')
    temporary.write_text(json.dumps(value),encoding='utf-8');os.replace(temporary,target)
    return value
