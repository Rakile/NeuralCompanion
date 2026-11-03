"""Process-local diagnostic selection. Never used for application admission."""
import copy
import json
import re
import threading
from pathlib import Path

_ROOT=Path(__file__).resolve().parents[2]/'diagnostics/contracts'
CONTRACT=json.loads((_ROOT/'logging-policy-v1.json').read_text(encoding='utf-8'))
SITES=json.loads((_ROOT/'logging-sites-v1.json').read_text(encoding='utf-8'))
LEVELS=tuple(CONTRACT['levels'])
CATEGORIES=frozenset(CONTRACT['categories'])

def validate_policy(raw):
    if (type(raw) is not dict or set(raw)!= {'version','revision','default_level','categories'}
        or type(raw['version']) is not int or raw['version']!=1
        or type(raw['revision']) is not str or not re.fullmatch(CONTRACT['revision_pattern'],raw['revision'])
        or raw['default_level'] not in LEVELS or type(raw['categories']) is not dict
        or any(k not in CATEGORIES or v not in LEVELS for k,v in raw['categories'].items())):
        raise ValueError('diagnostic_policy_invalid')
    return copy.deepcopy(raw)

class DiagnosticPolicy:
    def __init__(self):
        self._snapshot=copy.deepcopy(CONTRACT['default'])
        self._lock=threading.Lock()

    def apply_policy(self, raw):
        selected=validate_policy(raw)
        with self._lock:
            if selected['revision']==self._snapshot['revision'] and selected!=self._snapshot:
                raise ValueError('diagnostic_policy_revision_conflict')
            self._snapshot=selected
        return selected['revision']

    def snapshot(self):
        return copy.deepcopy(self._snapshot)

    def enabled(self, category, verbosity='trace', mandatory=False):
        if mandatory:return True
        current=self._snapshot
        category=category if category in CATEGORIES else 'uncategorized'
        level=current['categories'].get(category,current['default_level'])
        return level!='off' and verbosity in LEVELS[1:] and LEVELS.index(level)>=LEVELS.index(verbosity)

def classify(site, level='debug', outcome='observed', data=None):
    data=data if type(data) is dict else {}
    site=site if type(site) is str else ''
    mandatory=(level in ('error','warning') or outcome in ('failed','rejected')
        or data.get('begin_recorded') is True
        or bool(re.search(r'(?:^|[._])(reject(?:ed|ion)?|fail(?:ed|ure)?|error|overflow|unavailable)(?:$|[._])',site))
        or any(site.startswith(p) for p in SITES['mandatory_prefixes'])
        or bool(data.get('failure_kind')) or data.get('state_after') in ('rejected','failed')
        or (data.get('expected') is not None and 'actual' in data and data['expected']!=data['actual']
            and data.get('condition') not in SITES['nonfailure_conditions']))
    for prefix,category,verbosity in SITES['prefixes']:
        if site.startswith(prefix):return category,verbosity,mandatory
    return 'uncategorized','trace',mandatory

policy=DiagnosticPolicy()

def site_enabled(site, level='debug', outcome='observed', data=None):
    return policy.enabled(*classify(site,level,outcome,data))
