"""Local configuration IO, deliberately outside per-event callbacks."""
import argparse
import json
import os
from pathlib import Path
import threading
import uuid
from core.diagnostics.policy import CATEGORIES, policy, validate_policy

def policy_event(status, selected, reason=None):
    data={'site':'diagnostics.policy','status':status,'revision':selected['revision'],
          'effective':{c:selected['categories'].get(c,selected['default_level']) for c in sorted(CATEGORIES)}}
    if reason:data['reason']=reason
    return dict(level='info' if status=='applied' else 'warning',event_name='diagnostics.policy',
        trace_id='diagnostics-policy',operation_id='policy-'+selected['revision'],parent_operation_id=None,
        phase='snapshot',outcome='observed',basis='observed',links=[],context={},data=data)

class PolicyLoader:
    def __init__(self, root, target, notice):
        self.path=Path(root)/'runtime/diagnostics/logging-policy.json'
        self.target=target;self.notice=notice;self._last=None;self._loaded=False

    def refresh(self):
        status='applied';reason=None
        try:
            with self.path.open('rb') as handle:raw=handle.read(16385)
            if len(raw)>16384:reason='oversized_file';raise ValueError()
            self.target.apply_policy(json.loads(raw));self._loaded=True
        except FileNotFoundError:
            if self._loaded:status='rejected';reason='missing_file'
        except (ValueError,TypeError,UnicodeError):status='rejected';reason=reason or 'invalid_policy'
        except OSError:status='rejected';reason='read_failed'
        selected=self.target.snapshot();key=(status,reason,selected['revision'])
        if key!=self._last:
            # Retry failed notices instead of treating unrecorded evidence as delivered.
            if self.notice(status,selected,reason) is not False:self._last=key
        return selected

_lock=threading.Lock()
_loader=None
def ensure_policy_loader():
    global _loader
    with _lock:
        if _loader is not None:return _loader
        from core.diagnostics.emitter import DiagnosticEmitter
        from core.diagnostics.journal import enqueue_diagnostic
        emitter=DiagnosticEmitter(component='diagnostics',build_id=None,build_unavailable_reason='not_available',
            clock_id='policy-process',enqueue=enqueue_diagnostic,emergency=enqueue_diagnostic)
        _loader=PolicyLoader(Path(__file__).resolve().parents[2],policy,
            lambda status,selected,reason:emitter.emit(policy_event(status,selected,reason)) is not None)
        loader=_loader
        def run():
            while True:
                try:loader.refresh()
                except Exception:pass  # Policy is observational; last valid selection remains.
                threading.Event().wait(1.0)
        threading.Thread(target=run,name='nc-diagnostic-policy',daemon=True).start()
        return loader

def update_policy_file(root, overrides, default_level):
    target=Path(root)/'runtime/diagnostics/logging-policy.json'
    if target.exists():
        with target.open('rb') as handle:raw=handle.read(16385)
        if len(raw)>16384:raise ValueError('diagnostic_policy_oversized')
        selected=validate_policy(json.loads(raw))
    else:selected=policy.snapshot()
    selected['categories'].update(overrides)
    if default_level is not None:selected['default_level']=default_level
    selected['revision']=uuid.uuid4().hex
    selected=validate_policy(selected)
    target.parent.mkdir(parents=True,exist_ok=True)
    temporary=target.with_name('logging-policy-'+uuid.uuid4().hex+'.tmp')
    try:
        with temporary.open('x',encoding='utf-8') as handle:
            json.dump(selected,handle,sort_keys=True);handle.flush();os.fsync(handle.fileno())
        os.replace(temporary,target)
    finally:
        if temporary.exists():temporary.unlink()
    return selected

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime',required=True,type=Path)
    parser.add_argument('--set',action='append',default=[],metavar='CATEGORY=LEVEL')
    parser.add_argument('--default-level',choices=['off','errors','state','trace'])
    args=parser.parse_args()
    if not args.runtime.is_dir():parser.error('Runtime directory must already exist')
    try:
        overrides=dict(item.split('=',1) for item in getattr(args,'set'))
        result=update_policy_file(args.runtime,overrides,args.default_level)
    except (ValueError,OSError):parser.error('Invalid diagnostic policy or inaccessible file')
    print(json.dumps(result,sort_keys=True))

if __name__=='__main__':main()
