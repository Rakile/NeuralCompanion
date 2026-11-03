"""Consent-bound, offline installation of NC-owned VSeeFace bridge files."""
from pathlib import Path
import configparser
import hashlib
import io
import json
import math
import os
import re
import subprocess
import threading
import time
import uuid
import zipfile

from .bridge_bundle import LOADER_NAME, SUPPORTED_ASSEMBLIES, digest, safe_child, verify_bridge_bundle
from .bridge_processes import vseeface_processes

MANIFEST='NCVSeeFaceBridge.install.json'
PLUGIN='BepInEx/plugins/NCVSeeFaceBridge/'
CONFIG='BepInEx/config/nc.vseeface.speech.prototype.cfg'


class BridgeInstallation:
    def __init__(self, app_root: Path, *, process_reader=None):
        self.app_root=Path(app_root).resolve()
        self.shared_directory=self.app_root/'runtime/vseeface_speech_bridge'
        self._process_reader=process_reader or vseeface_processes
        self._plans={}
        self._lock=threading.RLock()

    def _payload(self):
        bundle=verify_bridge_bundle(self.app_root)
        base=self.app_root/'addons/vseeface_avatar/bridge_payload'
        files={}
        loader=(base/LOADER_NAME).read_bytes()
        if hashlib.sha256(loader).hexdigest()!=bundle['files'][LOADER_NAME]:
            raise ValueError('Loader changed while preparing the installation.')
        with zipfile.ZipFile(io.BytesIO(loader)) as archive:
            for member in archive.infolist():
                if not member.is_dir():
                    # Validate names before they can become installation destinations.
                    safe_child(base,member.filename)
                    files[member.filename.replace('\\','/')]=archive.read(member)
        for relative in bundle['files']:
            if relative == LOADER_NAME:continue
            data=(base/relative).read_bytes()
            if hashlib.sha256(data).hexdigest()!=bundle['files'][relative]:
                raise ValueError('Payload changed while preparing the installation: '+relative)
            files[PLUGIN+relative]=data
        return bundle,files

    @staticmethod
    def _same(a,b):
        return os.path.normcase(str(Path(a).resolve()))==os.path.normcase(str(Path(b).resolve()))

    def _running(self,root):
        return [p for p in self._process_reader() if self._same(p['path'],root/'VSeeFace.exe')]

    def launch(self,installation: str) -> dict:
        """Start only the user-selected application; no installation or bridge activation."""
        with self._lock:
            if not str(installation or '').strip():
                raise ValueError('Choose your VSeeFace folder before starting it.')
            root=Path(installation).resolve()
            executable=safe_child(root,'VSeeFace.exe')
            if not executable.is_file() or not (root/'VSeeFace_Data').is_dir():
                raise ValueError('The saved folder does not contain VSeeFace. Choose its extracted application folder.')
            running=self._running(root)
            if running:
                return dict(state='running',message='VSeeFace is already running.',installation=str(root),pid=running[0]['pid'],already_running=True)
            try:
                process=subprocess.Popen([str(executable)],cwd=str(root))
            except OSError as error:
                raise ValueError('Could not start VSeeFace: '+str(error)) from error
            return dict(state='starting',message='Starting VSeeFace. Refresh status after it opens.',installation=str(root),pid=process.pid,already_running=False)

    def _root(self,installation):
        if not str(installation or '').strip():raise ValueError('Choose the extracted VSeeFace folder first.')
        root=Path(installation).resolve(strict=True)
        if not root.is_dir() or not (root/'VSeeFace.exe').is_file():
            raise ValueError('Choose the folder containing VSeeFace.exe.')
        game_hash=digest(safe_child(root,'VSeeFace_Data/Managed/Assembly-CSharp.dll'))
        version=next((v for v,h in SUPPORTED_ASSEMBLIES.items() if game_hash==h),None)
        if version is None:raise ValueError('Unsupported VSeeFace build. Use the inspected c4/c5 release; c5 is recommended.')
        return root,version

    def _owned(self,root,allowed):
        path=safe_child(root,MANIFEST)
        if not path.exists():return None
        data=json.loads(path.read_text(encoding='utf-8-sig'))
        if not isinstance(data,dict) or not self._same(data.get('root',''),root):
            raise ValueError('Bridge ownership manifest belongs to a different installation.')
        rows=data.get('files')
        if not isinstance(rows,list) or not rows:raise ValueError('Invalid bridge ownership inventory.')
        seen=set()
        for row in rows:
            relative=str(row['relative']).replace('\\','/')
            safe_child(root,relative)
            if relative not in allowed or relative.casefold() in seen:
                raise ValueError('Unrecognized or duplicate bridge-owned path: '+relative)
            seen.add(relative.casefold())
            if not re.fullmatch('[0-9a-fA-F]{64}',str(row.get('sha256',''))):
                raise ValueError('Invalid owned checksum: '+relative)
            if not relative.startswith(PLUGIN) and row['sha256'].lower()!=hashlib.sha256(allowed[relative]).hexdigest():
                raise ValueError('Recorded loader is not the pinned NC loader; preserving it: '+relative)
            row['relative']=relative
        required={'winhttp.dll','BepInEx/core/BepInEx.dll','BepInEx/core/0Harmony.dll',PLUGIN+'NCVSeeFaceBridge.dll'}
        if not {name.casefold() for name in required}.issubset(seen):
            raise ValueError('Ownership manifest is missing required bridge/loader files.')
        return data

    def inspect(self,installation: str) -> dict:
        if not str(installation or '').strip():
            return dict(state='not_configured',message='Choose your extracted VSeeFace folder.',installation='',can_install=False,can_adopt=False,can_repair=False,can_remove=False)
        try:
            bundle,files=self._payload();root,version=self._root(installation)
            owned=self._owned(root,files)
            running=self._running(root)
            result=dict(state='not_installed',message='Speech bridge is not installed.',installation=str(root),game_version=version,bridge_version=bundle['bridge_version'],
                        running=bool(running),can_install=False,can_adopt=False,can_repair=False,can_remove=False)
            if owned is None:
                # Leftover logs/configs are not a loader; real foreign bootstrap/core files are.
                if any(safe_child(root,p).exists() for p in files if not p.startswith(PLUGIN)):
                    result.update(state='conflict',message='An unrecognized loader exists. NC will not overwrite it.')
                else:result['can_install']=not running
                if running:result['message']+=' Close VSeeFace before installing.'
                return result
            missing=[];changed=[]
            for row in owned['files']:
                p=safe_child(root,row['relative'])
                if not p.exists():missing.append(row['relative'])
                elif digest(p)!=row['sha256'].lower():changed.append(row['relative'])
            if changed:
                result.update(state='modified',message='Installed files were changed; NC will preserve them: '+', '.join(changed))
                return result
            if missing:
                result.update(state='damaged',message='Owned bridge files are missing; repair is available.',can_repair=not running,can_remove=not running)
                return result
            result.update(state='installed',message='Bridge installed; start VSeeFace and refresh status.',can_adopt=True,can_repair=not running,can_remove=not running)
            dll=next((r['sha256'].lower() for r in owned['files'] if r['relative']==PLUGIN+'NCVSeeFaceBridge.dll'),'')
            if dll!=bundle['files']['NCVSeeFaceBridge.dll']:
                result.update(state='update_available',message='An owned bridge build is installed. Approve Update to use the packaged build and live status.')
            if not self._configured(root):
                result.update(state='configuration_mismatch',message='The bridge points to a different NC folder. Close VSeeFace and approve Repair.',can_adopt=False)
            return result
        except (OSError,ValueError,KeyError,TypeError,configparser.Error) as exc:
            return dict(state='unavailable',message=str(exc),installation=str(installation),can_install=False,can_adopt=False,can_repair=False,can_remove=False)

    def _configured(self,root):
        path=safe_child(root,CONFIG)
        if not path.is_file():return False
        c=configparser.ConfigParser(interpolation=None)
        c.read_string(path.read_text(encoding='utf-8-sig'))
        return c.has_option('Bridge','SharedDirectory') and self._same(c['Bridge']['SharedDirectory'],self.shared_directory)

    def _fingerprint(self,root,files):
        paths=set(files)|{MANIFEST,CONFIG,'VSeeFace_Data/Managed/Assembly-CSharp.dll','VSeeFace.exe'}
        current={name:digest(p) if p.is_file() else None for name in sorted(paths) for p in [safe_child(root,name)]}
        current['bundle_manifest']=digest(self.app_root/'addons/vseeface_avatar/bridge_payload/manifest.json')
        return hashlib.sha256(json.dumps(current,sort_keys=True).encode()).hexdigest()

    def prepare(self,action: str,installation: str) -> dict:
        with self._lock:
            if action not in {'install','adopt','repair','remove'}:raise ValueError('Unknown bridge setup action.')
            status=self.inspect(installation)
            if not status.get('can_'+action):raise ValueError(status['message'])
            root=Path(status['installation']);bundle,files=self._payload()
            token=uuid.uuid4().hex
            plan=dict(action=action,installation=str(root),fingerprint=self._fingerprint(root,files),approval_token=token,
                      bridge_version=bundle['bridge_version'],files=sorted(files),message=status['message'])
            # Cache one current preview per action; refreshing invalidates older dialogs.
            self._plans={key:value for key,value in self._plans.items()
                         if value['action']!=action and value['installation']==str(root)}
            self._plans[token]=plan
            return dict(plan)

    def _configuration_bytes(self,root):
        path=safe_child(root,CONFIG)
        text=path.read_text(encoding='utf-8-sig') if path.is_file() else ''
        replacement='SharedDirectory = '+str(self.shared_directory)
        if re.search(r'^\s*SharedDirectory\s*=',text,re.M):
            text=re.sub(r'^\s*SharedDirectory\s*=.*$',lambda _m:replacement,text,flags=re.M)
        elif re.search(r'^\[Bridge\]\s*$',text,re.M):
            text=re.sub(r'^\[Bridge\]\s*$',lambda _m:'[Bridge]\n'+replacement,text,count=1,flags=re.M)
        else:text+='\n[Bridge]\n'+replacement+'\n'
        return text.encode('utf-8')

    @staticmethod
    def _write(path,data):
        path.parent.mkdir(parents=True,exist_ok=True)
        temporary=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
        try:
            temporary.write_bytes(data);os.replace(temporary,path)
        finally:temporary.unlink(missing_ok=True)

    def execute(self,approval_token: str) -> dict:
        with self._lock:
            plan=self._plans.pop(str(approval_token),None)
            if plan is None:raise ValueError('Review the setup action and approve its current confirmation first.')
            root,version=self._root(plan['installation']);bundle,files=self._payload()
            if self._fingerprint(root,files)!=plan['fingerprint']:
                raise ValueError('Installation or package changed after preview. Refresh and review the action again.')
            action=plan['action'];status=self.inspect(str(root))
            if not status.get('can_'+action):raise ValueError(status['message'])
            if action=='adopt':return dict(status,action=action)
            if self._running(root):raise ValueError('Close VSeeFace before changing its bridge files.')
            owned=self._owned(root,files)
            backup=self.app_root/'runtime/vseeface_bridge_backups'/uuid.uuid4().hex
            changes={}
            if action=='remove':
                changes={r['relative']:None for r in owned['files']}
                changes[MANIFEST]=None
            else:
                previously_owned={row['relative'] for row in owned['files']} if owned else set()
                for name in files:
                    if safe_child(root,name).exists() and name not in previously_owned:
                        raise ValueError('Would overwrite an unowned file: '+name)
                changes.update(files)
                changes[CONFIG]=self._configuration_bytes(root)
                inventory=[dict(relative=name,sha256=hashlib.sha256(data).hexdigest()) for name,data in sorted(files.items())]
                changes[MANIFEST]=json.dumps(dict(root=str(root),bridge_version=bundle['bridge_version'],files=inventory),indent=2).encode()
            # All destination validation/backup happens before writing anything in VSeeFace.
            originals={name:(p.read_bytes() if p.exists() else None) for name in changes for p in [safe_child(root,name)]}
            for name,data in originals.items():
                if data is not None:
                    path=safe_child(backup,name);path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
            applied=[]
            try:
                if self._running(root):raise ValueError('VSeeFace started during setup; close it and review again.')
                if self._fingerprint(root,files)!=plan['fingerprint']:
                    raise ValueError('Installation changed during setup; review again.')
                # Bootstrap last on fresh setup; no partially copied loader should be started.
                for name in sorted(changes,key=lambda n:n=='winhttp.dll'):
                    data=changes[name]
                    if data==originals[name]:continue
                    path=safe_child(root,name)
                    if (path.read_bytes() if path.exists() else None)!=originals[name]:
                        raise ValueError('Destination changed during installation: '+name)
                    if data is None:path.unlink(missing_ok=True)
                    else:self._write(path,data)
                    applied.append(name)
            except Exception as error:
                preserved=[]
                for name in reversed(applied):
                    path=safe_child(root,name);now=path.read_bytes() if path.exists() else None
                    if now!=changes[name]:preserved.append(name);continue
                    try:
                        if originals[name] is None:path.unlink(missing_ok=True)
                        else:self._write(path,originals[name])
                    except OSError:preserved.append(name)
                raise ValueError(f'Bridge setup failed: {error}. Recovery files: {backup}. Preserved concurrent changes: {preserved}') from error
            return dict(self.inspect(str(root)),action=action,backup=str(backup))

    def status(self,installation: str) -> dict:
        result=self.inspect(installation);result['checked_at']=time.time()
        if result['state']!='installed':return result
        if not result.get('running'):
            return dict(result,message='Bridge installed; VSeeFace is not running.')
        try:
            data=json.loads((self.shared_directory/'status.json').read_text(encoding='utf-8-sig'))
            root=Path(result['installation']);pids={p['pid'] for p in self._running(root)}
            age=float(data['max_clock_age_seconds']);elapsed=time.time()-float(data['updated'])
            if (not math.isfinite(age) or age<=0 or not 0<=elapsed<=age or data['pid'] not in pids
                    or not self._same(data['installation_path'],root) or data.get('bridge_version')!=result['bridge_version']):
                return dict(result,state='waiting',message='VSeeFace is running; waiting for a matching fresh bridge heartbeat.')
            if data.get('state')=='error':return dict(result,state='bridge_error',message=str(data.get('detail','Bridge reported an error.')))
            return dict(result,state='ready',message='Bridge ready. Audible speech is played by NC.',bridge_version=data['bridge_version'])
        except (OSError,ValueError,KeyError,TypeError):
            return dict(result,state='waiting',message='VSeeFace is running; waiting for the bridge heartbeat. Legacy bridges may need Update.')
