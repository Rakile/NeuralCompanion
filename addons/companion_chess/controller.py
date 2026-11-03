"""Addon-owned worker: all network, engine-process, disk and MIDI work stays off Qt."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import queue
import sys
import threading
import time
from uuid import uuid4

from core.runtime.contracts import CancellationToken
from .hardware import Hardware
from .lighting import palette_frame, physical_route, validate_palette
from .midi_profiles import PROFILES
from .board_models import BOARD_MODELS
from .engine_paths import bundled_stockfish_path, normalize_engine_selection
from .launcher import ServerLauncher

TOOL_NAMES=('chess_get_state','chess_game_control','chess_prepare_turn','chess_get_candidates',
            'chess_choose_move','chess_finalize_move','chess_get_operation')
DEFAULT_LIGHT=dict(preset='spotlight',brightness=1.4,warmth=.55,azimuth=25,elevation=68,fill=0,shadows=True,
                   dust=True,ambient_occlusion=True,glow=True,reflections=False,
                   antialiasing='msaa4',depth_of_field=False,focus_blur=2.5,
                   physics_drag=False,tilt_shift=False,tilt_position=.5,tilt_width=.25,tilt_blur=4.,tilt_angle=0.,
                   move_animation=True,move_duration=280,led_brightness=.55,palette={},flowing_path=False,
                   refraction=True,transmission=.8,ior=1.49,camera_motion=False,camera_pattern='orbit',camera_speed=1.0)
DEFAULTS=dict(server_id='',persona_id='',port=8766,engine_path='',skill=8,human='white',
              style='classic',view='2d',lighting={name:deepcopy(DEFAULT_LIGHT) for name in ('classic','modern','fantasy')},
              orientation='white',hardware_model='launchpad_s',board_model='style',speech=True,comment_user_moves=False,sound_enabled=True,volume=.65,sounds={})


# Compatibility for callers validating all physical confirmation steps.
_move_route = physical_route


class ChessController:
    def __init__(self, context):
        self.context=context
        self._lock=threading.RLock()
        self._queue=queue.Queue(maxsize=32)
        self._stop=threading.Event()
        self._cancel=CancellationToken()
        self._hardware=Hardware()
        self._calibration_until=0.
        self._launcher=ServerLauncher(context)
        self._port=None
        self._tools={}
        self._opened=False
        self._uncertain=None
        self._promotion_physical: tuple[str, str] | None = None
        self._state=dict(revision=0,busy=False,closed=False,status='Open Companion Chess to begin.',
                         preferences=deepcopy(DEFAULTS),game={},personas=[],servers=[],access={},
                         hardware=self._hardware.snapshot(),selected='',targets=[],promotion=[],
                         commentary='',speaker='',fallback=False,endpoint='http://127.0.0.1:8766/mcp',
                         server_running=False,setup_token='',sound_event=None)
        self._state.update(bundled_engine_path=str(bundled_stockfish_path(context.paths.app_root)),
                           bundled_engine_available=False,engine_installing=False,engine_message='',
                           engine_install_supported=sys.platform == 'win32')
        self._state['connection'] = dict(connected=False, message='Choose a chess connection.')
        self._worker=context.tasks.spawn('companion-chess',self._run,on_cancel=lambda _:self.begin_shutdown())
        from .online_controller import OnlineController
        self._online=OnlineController(context,self._prepare_online_join,
            persona_getter=lambda:self.snapshot()['preferences']['persona_id'],
            light_getter=self._current_light)

    def snapshot(self):
        with self._lock: value=deepcopy(self._state)
        online=getattr(self,'_online',None)
        if online is not None:
            value['online']=online.snapshot()
            value['revision']+=value['online']['revision']
        return value

    def _prepare_online_join(self):
        """Online worker asks the existing local worker to persist/pause first."""
        state=self.snapshot()
        if state['game'] and state['game'].get('phase') != 'game_over':
            if not state['connection'].get('connected'):
                raise RuntimeError('Reconnect the local game to save/pause it before joining online.')
            if not self.command('pause'): raise RuntimeError('Local game could not be paused.')
            deadline=time.monotonic()+15
            while time.monotonic()<deadline and not self._stop.is_set():
                current=self.snapshot()
                if current['game'].get('phase')=='paused' and not current['busy']: break
                time.sleep(.05)
            else: raise RuntimeError('Local pause unconfirmed; online game was not joined.')
        if self._hardware.snapshot()['connected']:
            if not self.command('disconnect_hardware'): raise RuntimeError('Release the local Launchpad first.')
            deadline=time.monotonic()+10
            while self._hardware.snapshot()['connected'] and time.monotonic()<deadline: time.sleep(.05)
            if self._hardware.snapshot()['connected']: raise RuntimeError('Local Launchpad is still connected.')

    def _update(self, **values):
        with self._lock:
            if any(self._state.get(k)!=v for k,v in values.items()):
                self._state.update(values)
                self._state['revision']+=1

    def command(self, action, **fields):
        if action == 'engine_cancel':
            with self._lock:
                if not self._state.get('engine_installing'): return False
                self._cancel.cancel('stockfish_install_cancelled')
            return True
        if action.startswith('online_'):
            online=getattr(self,'_online',None)
            return online.submit(action.removeprefix('online_'),**fields) if online else False
        if action not in {'open','start_server','reveal_token','refresh','request','settings','new','square','drop','promote',
                          'pause','resume','takeback','resign','end','retry_persona','activate_hardware','connect_hardware',
                          'disconnect_hardware','reconcile','continue_desktop','calibrate','sound_assign','sound_import','sound_clear',
                          'engine_select','engine_install'}:
            return False
        with self._lock:
            if self._state['closed']: return False
            if action in {'pause','end'}: self._cancel.cancel('chess_'+action)
            if self._state['busy'] and action not in {'pause','end','open'}: return False
        try: self._queue.put_nowait((action,deepcopy(fields)))
        except queue.Full: return False
        return True

    def _load(self):
        self._refresh_engine_status()
        try:
            values=self.context.storage.read_json('preferences-v1.json')
            if not isinstance(values,dict): raise ValueError()
            prefs=deepcopy(DEFAULTS)
            prefs.update({k:v for k,v in values.items() if k in DEFAULTS})
            if not isinstance(prefs['engine_path'], str): raise ValueError('Invalid engine path.')
            prefs['engine_path'] = normalize_engine_selection(prefs['engine_path'])
            lights=prefs['lighting']
            if not isinstance(lights,dict): raise ValueError('Invalid lighting.')
            prefs['lighting']={name:dict(deepcopy(DEFAULT_LIGHT),**lights.get(name,{}))
                               for name in ('classic','modern','fantasy')}
            for light in prefs['lighting'].values():
                light['palette']=validate_palette(light['palette'])
                if type(light['flowing_path']) is not bool: raise ValueError('Invalid flowing path setting.')
            if prefs['hardware_model'] not in PROFILES: prefs['hardware_model']='launchpad_s'
            if prefs['board_model'] not in BOARD_MODELS: prefs['board_model']='style'
            self._hardware.set_model(prefs['hardware_model'])
            self._hardware.orientation=prefs['orientation']
            self._update(preferences=prefs,hardware=self._hardware.snapshot())
        except FileNotFoundError: pass
        except (OSError,ValueError,TypeError): self._update(status='Chess preferences could not be read; defaults are active.')
        try:
            journal=self.context.storage.read_json('pending-operation-v1.json')
            value=journal.get('operation_id')
            if value is not None and (not isinstance(value,str) or len(value)>160): raise ValueError()
            self._uncertain=value
        except FileNotFoundError: pass
        except (OSError,ValueError,TypeError):
            self._uncertain='unreadable-journal'
            self._update(status='The previous operation needs reconciliation. Connect and refresh before playing.')

    def _set_uncertain(self, operation):
        path=self.context.storage.resolve('pending-operation-v1.json')
        temporary=path.with_suffix('.tmp')
        with temporary.open('w',encoding='utf-8') as stream:
            json.dump(dict(operation_id=operation),stream)
            stream.flush()
            import os
            os.fsync(stream.fileno())
        temporary.replace(path)
        self._uncertain=operation

    def _resolve_uncertain(self):
        if not self._uncertain: return
        # Never replay a mutation: query its receipt and then read current authority.
        self._invoke('chess_get_operation',dict(operation_id=self._uncertain),cancellable=False)
        self._publish(self._invoke('chess_get_state',{},cancellable=False))
        self._set_uncertain(None)

    def _save_preferences(self, fields):
        prefs=self.snapshot()['preferences']
        if ('hardware_model' in fields and fields['hardware_model'] != prefs['hardware_model']
                and self._hardware.snapshot()['connected']):
            raise ValueError('Disconnect hardware before changing the Launchpad model.')
        for key,value in fields.items():
            if key not in DEFAULTS: raise ValueError('Unknown chess preference.')
            if key in {'server_id','persona_id','engine_path'}:
                if not isinstance(value,str) or len(value)>2048: raise ValueError('Invalid setting.')
            elif key in {'sound_enabled','speech','comment_user_moves'}:
                if type(value) is not bool: raise ValueError('Use an on/off setting.')
            elif key in {'style','view','human','orientation','hardware_model','board_model'}:
                options={'style':('classic','modern','fantasy'),'view':('2d','3d'),'human':('white','black'),'orientation':('white','black'),
                         'hardware_model':tuple(PROFILES),'board_model':BOARD_MODELS}
                if value not in options[key]: raise ValueError('Invalid chess option.')
            elif key in {'port','skill','volume'}:
                value=float(value) if key=='volume' else int(value)
                lo,hi={'port':(1024,65535),'skill':(0,20),'volume':(0,1)}[key]
                if not lo<=value<=hi: raise ValueError('Chess setting is outside its range.')
            elif key=='lighting':
                if not isinstance(value,dict): raise ValueError('Invalid lighting.')
                validated={}
                for style in ('classic','modern','fantasy'):
                    light=dict(DEFAULT_LIGHT,**value.get(style,{}))
                    if light['preset'] not in ('spotlight','study','studio','moon'): raise ValueError('Invalid lighting preset.')
                    for name,(lo,hi) in {'brightness':(0,4),'led_brightness':(0,1),'warmth':(0,1),'azimuth':(-180,180),'elevation':(15,90),'fill':(0,1),'transmission':(0,1),'ior':(1,2.4),'camera_speed':(.25,3),'tilt_position':(0,1),'tilt_width':(.05,1),'tilt_blur':(0,10),'tilt_angle':(-90,90)}.items():
                        light[name]=max(lo,min(hi,float(light[name])))
                    if light['antialiasing'] not in ('off','msaa2','msaa4','msaa8','ssaa'):
                        raise ValueError('Invalid antialiasing mode.')
                    light['focus_blur']=max(0,min(6,float(light['focus_blur'])))
                    light['move_duration']=max(100,min(800,int(light['move_duration'])))
                    for name in ('shadows','dust','ambient_occlusion','glow','reflections','depth_of_field','physics_drag','tilt_shift','move_animation','refraction'):
                        light[name]=bool(light[name])
                    light['palette']=validate_palette(light['palette'])
                    if type(light['camera_motion']) is not bool: raise ValueError('Use an on/off camera motion setting.')
                    if light['camera_pattern'] not in ('orbit','sway','figure8','breathe'): raise ValueError('Invalid camera motion pattern.')
                    if type(light['flowing_path']) is not bool: raise ValueError('Use an on/off flowing path setting.')
                    validated[style]=light
                value=validated
            prefs[key]=value
        path=self.context.storage.resolve('preferences-v1.json')
        temporary=path.with_suffix('.tmp')
        temporary.write_text(json.dumps(prefs,allow_nan=False),encoding='utf-8')
        temporary.replace(path)
        self._hardware.set_model(prefs['hardware_model'])
        self._hardware.orientation=prefs['orientation']
        self._update(preferences=prefs,hardware=self._hardware.snapshot())
        if {'orientation','lighting','style'}.intersection(fields): self._lights(force=True)

    def _refresh(self):
        try:
            self._refresh_current()
        except Exception:
            self._update(connection=dict(connected=False, message='Chess connection needs attention. Refresh to reconnect.'))
            raise

    def _refresh_current(self):
        self._refresh_engine_status()
        self._port=self.context.services.get('mcp.core.v1')
        host=self.context.capabilities.chess_personas
        if host: self._update(personas=host.personas())
        if self._port is None:
            self._update(status='Enable MCP Core to connect Companion Chess.',
                         connection=dict(connected=False, message='MCP Core is unavailable.'))
            return
        servers=self._port.list_servers().get('data') or []
        sid=self.snapshot()['preferences']['server_id']
        self._tools={tool['name'].rsplit('__',1)[-1]:tool for tool in (self._port.list_tools(sid).get('data') or [])} if sid else {}
        access=self._port.access_status(sid).get('data') or {} if sid else {}
        self._update(servers=servers,access=access)
        if 'chess_get_state' in self._tools:
            self._publish(self._invoke('chess_get_state',{},cancellable=False))
            if self._uncertain: self._resolve_uncertain()
        else:
            self._update(connection=dict(connected=False, message=(
                'Select a chess MCP connection in Setup.' if not sid else
                'Connect the server and grant Companion Chess access in MCP Core.')))

    def _refresh_engine_status(self) -> None:
        executable = bundled_stockfish_path(self.context.paths.app_root)
        self._update(bundled_engine_path=str(executable), bundled_engine_available=executable.is_file())

    def _invoke(self, name, args, *, cancellable=True):
        tool=self._tools.get(name)
        if not tool or self._port is None: raise PermissionError('Connect the chess server and grant its tools to Companion Chess in Runtime → MCP Core.')
        sid=self.snapshot()['preferences']['server_id']
        token=self._cancel
        guard=lambda:not self._stop.is_set() and (not cancellable or not token.cancelled)
        schema=hashlib.sha256(json.dumps(tool['inputSchema'],sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
        response=self._port.invoke_tool(sid,tool['name'],args,is_current=guard,expected_schema_fingerprint=schema)
        call=(response.get('data') or {}).get('call_id')
        deadline=time.monotonic()+35
        while response.get('status') in {'queued','running'} and call:
            if not guard() or time.monotonic()>deadline:
                self._port.cancel_call(call)
                raise RuntimeError('Chess operation completion is unconfirmed. Refresh to resolve it.')
            self._stop.wait(.04)
            response=self._port.call_status(call)
        if not response.get('ok') or response.get('status')!='ok':
            raise RuntimeError('Chess connection or permission unavailable; refresh to resolve any pending operation.')
        result=(response.get('data') or {}).get('result') or {}
        if result.get('isError'):
            raise ValueError(next((b.get('text','Rejected chess command.') for b in result.get('content',[]) if b.get('type')=='text'),'Rejected chess command.'))
        value=result.get('structuredContent')
        if not isinstance(value,dict): raise RuntimeError('Invalid chess server response.')
        return value

    def _arguments(self, **fields):
        state=self.snapshot()['game']
        if not state: raise ValueError('Connect and refresh the chess board first.')
        return dict(game_id=state['game_id'],expected_revision=state['revision'],
                    operation_id=f"{state['game_id']}:{state['revision']}:{uuid4().hex}",**fields)

    def _mutate(self, tool, **fields):
        if self._uncertain is not None: raise RuntimeError('Resolve the previous operation with Refresh before continuing.')
        args=self._arguments(**fields)
        self._set_uncertain(args['operation_id'])
        try: receipt=self._invoke(tool,args,cancellable=False)
        except ValueError:
            self._set_uncertain(None)
            raise
        self._set_uncertain(None)
        self._publish(receipt['state'])
        return receipt

    def _control(self, action, **fields):
        return self._mutate('chess_game_control',action=action,**fields)

    def _publish(self, game):
        if game.get('protocol')!=1: raise ValueError('Incompatible Companion Chess protocol.')
        if self._launcher.identity and game.get('server_identity') and game['server_identity']!=self._launcher.identity:
            raise ValueError('The MCP connection points to a different chess server. Select the endpoint started by this addon.')
        self._update(game=game,sound_event=game.get('last_event'),
                     connection=dict(connected=True, message='Chess server connected'))
        self._lights()

    def _current_light(self):
        with self._lock:
            prefs=self._state['preferences']
            return deepcopy(prefs['lighting'][prefs['style']])

    def _lights(self, *, force=False):
        if not self._hardware.snapshot()['connected']: return
        state=self.snapshot()
        game=state['game']
        light=state['preferences']['lighting'][state['preferences']['style']]
        leds=palette_frame(game,state['selected'],state['targets'],light,time.time())
        try:
            self._hardware.set_color_leds(leds,force=force)
        except (OSError,RuntimeError) as exc:
            self._hardware_failed(exc)

    def _hardware_failed(self, error: Exception):
        self._hardware.disconnect()
        self._update(hardware=self._hardware.snapshot())
        status='Launchpad disconnected. Reconnect or explicitly Continue on screen.'
        try:
            self._resolve_uncertain()
            self._control('pause')
        except Exception as exc:
            status+=' Refresh to resolve the chess operation: '+str(exc)[:160]
        self._update(status=status+' MIDI: '+str(error)[:120])

    def _poll_hardware(self):
        # Only transport failures close MIDI. A rejected/unconfirmed chess operation
        # must never reset the Launchpad or erase the current move's lights.
        try:
            squares=self._hardware.poll()
        except (OSError,RuntimeError) as exc:
            self._hardware_failed(exc)
            return
        if self._uncertain:
            if squares: self._update(status='Refresh to resolve the unconfirmed chess operation, then press the pad again.')
            return  # Drain, never replay physical presses after an uncertain receipt.
        for square in squares:
            self._square(square,physical=True)

    def _square(self, square, *, physical=False):
        state=self.snapshot()
        game=state['game']
        if game.get('phase')=='awaiting_physical_confirmation':
            pending=game['pending']
            step=pending['steps'][pending['step']]
            if physical and square != step['square']:
                # A poll drains a batch of MIDI events. Reject only this press,
                # not the remaining source/destination presses in that batch.
                self._update(status=step['instruction'])
                return
            self._control('physical',square=square)
            current=self.snapshot()['game']
            pending=current.get('pending')
            self._update(status=(pending['steps'][pending['step']]['instruction'] if pending
                                 else 'Physical move confirmed.'))
            return
        if game.get('phase')!='human_turn': return
        selected=state['selected']
        moves=[m for m in game['legal_moves'] if m[:2]==selected and m[2:4]==square] if selected else []
        if moves:
            if len(moves)>1:
                self._promotion_physical = (selected, square) if physical else None
                self._update(promotion=moves,status='Choose the piece for promotion.')
                return
            self._control('move',uci=moves[0])
            if physical:
                self._confirm_human_move(selected, square)
            self._update(selected='',targets=[],promotion=[])
            self._lights()
        else:
            self._promotion_physical = None
            targets=sorted({m[2:4] for m in game.get('legal_moves',[]) if m[:2]==square})
            key='select_'+game['human'] if targets else 'illegal'
            self._update(selected=square if targets else '',targets=targets,sound_event=dict(id=uuid4().hex,key=key))
            self._lights()

    def _confirm_human_move(self, source: str, target: str) -> None:
        """Keep physical presses already received before a promotion choice."""
        pending = self.snapshot()['game'].get('pending')
        if not pending: return
        step = pending['steps'][pending['step']]
        if step['square'] != source or step['kind'] != 'pickup': return
        self._control('physical', square=source)
        pending = self.snapshot()['game'].get('pending')
        if pending:
            step = pending['steps'][pending['step']]
            if step['square'] == target and step['kind'] in {'place', 'capture'}:
                self._control('physical', square=target)
        pending = self.snapshot()['game'].get('pending')
        if pending:
            self._update(status=pending['steps'][pending['step']]['instruction'])

    def _persona_turn(self):
        with self._lock:
            state=self.snapshot()
            if (state['game'].get('phase')!='persona_turn' or not state['preferences']['persona_id']
                    or self._uncertain or self._cancel.cancelled):
                return
            self._update(busy=True,status='Preparing the persona turn…')
            self._cancel=CancellationToken()
        host=self.context.capabilities.chess_personas
        prefs=state['preferences']
        try:
            prepared=self._mutate('chess_prepare_turn',persona_id=prefs['persona_id'])
            ticket=prepared['ticket']
            for _ in range(150):
                if self._cancel.cancelled or self._stop.is_set(): return
                choices=self._invoke('chess_get_candidates',dict(ticket=ticket))
                if choices['status']!='analysing': break
                self._stop.wait(.1)
            else: raise RuntimeError('Engine analysis timed out.')
            if choices['status']!='ready': raise RuntimeError(choices.get('error') or 'Engine unavailable.')
            game=self.snapshot()['game']
            args=self._arguments()
            expected=[game['revision']]
            guard=lambda:not self._stop.is_set() and not self._cancel.cancelled and self.snapshot()['game'].get('revision')==expected[0]
            self._update(status='Your persona is choosing a move…')
            self._set_uncertain(args['operation_id'])
            try:
                choice=host.choose(persona_id=prefs['persona_id'],server_id=prefs['server_id'],state=dict(game,comment_user_moves=prefs['comment_user_moves']),ticket=ticket,
                    candidates=choices['candidates'],operation_id=args['operation_id'],cancellation=self._cancel,is_current=guard)
            except (PermissionError,ValueError):
                self._set_uncertain(None)
                raise
            self._set_uncertain(None)
            # Advance only from this acknowledged server receipt, never model prose.
            expected[0]=choice['receipt']['state']['revision']
            self._publish(choice['receipt']['state'])
            pending=self.snapshot()['game']['pending']
            instruction=f"{choice['persona_name']}: {pending['san']} — {pending['uci'][:2]} to {pending['uci'][2:4]}."
            self._update(commentary=instruction+'\n'+choice['commentary'],speaker=choice['persona_name'],fallback=choice['fallback'])
            announced=host.announce(instruction+' '+choice['commentary'],choice,is_current=guard) if prefs['speech'] and guard() else False
            if not guard(): return
            self._mutate('chess_finalize_move',announcement='queued' if announced else 'skipped')
            self._update(status=('Engine fallback. ' if choice['fallback'] else '')+('Voice queued.' if announced else 'Move shown on screen; voice skipped.'))
        finally: self._update(busy=False)

    def _dispatch(self, action, fields):
        if action=='open':
            self._opened=True
            self._refresh()
        elif action=='start_server':
            result=self._launcher.start(self.snapshot()['preferences']['port'],self._stop)
            self._update(server_running=True,endpoint=result['endpoint'],status='Server ready. Add this endpoint with Bearer authentication in Runtime → MCP Core.')
        elif action=='reveal_token': self._update(setup_token=self._launcher.token)
        elif action=='refresh':
            self._refresh()
            self._resolve_uncertain()
        elif action=='request':
            if self._port is None: self._refresh()
            if self._port is None: raise ValueError('Enable MCP Core first.')
            self._port.request_access(self.snapshot()['preferences']['server_id'],
                'Play chess with your NC persona, including optional physical move confirmations.',
                requested_tools=[dict(name=name,match='name_or_namespace') for name in TOOL_NAMES])
            self._update(status='Access requested. Approve Companion Chess and grant the seven tools in MCP Core.')
        elif action=='settings':
            self._save_preferences(fields)
            if 'server_id' in fields: self._refresh()
        elif action=='engine_select':
            from .engine_setup import existing_engine
            self._save_preferences({'engine_path': existing_engine(fields.get('path', ''))})
            self._update(engine_message='Engine selected. Start a new game to apply changes.')
        elif action=='engine_install':
            from .engine_setup import install_engine
            cancellation = self._cancel
            self._update(engine_installing=True, engine_message='Preparing Stockfish installation…')
            try:
                path = install_engine(fields.get('folder', ''), self.context.paths.app_root,
                    lambda: self._stop.is_set() or cancellation.cancelled,
                    lambda message: self._update(engine_message=message))
                # Serialize the final cancellation check with engine_cancel.
                # Once committing, cancellation must no longer be accepted.
                with self._lock:
                    if self._stop.is_set() or cancellation.cancelled:
                        raise RuntimeError('Stockfish installation cancelled. Your engine selection was kept.')
                    self._update(engine_installing=False)
                self._save_preferences({'engine_path': path})
                self._update(engine_message='Stockfish installed and selected. Start a new game to apply changes.')
            except Exception as exc:
                self._update(engine_message=str(exc)[:400])
                raise
            finally:
                self._update(engine_installing=False)
        elif action=='new':
            p=self.snapshot()['preferences']
            if not p['persona_id']: raise ValueError('Choose your saved NC persona first.')
            self._control('new',human=p['human'],persona_id=p['persona_id'],engine_path=p['engine_path'],skill=p['skill'])
            self._promotion_physical = None
            self._update(selected='',targets=[],promotion=[],commentary='',fallback=False,status='New game ready.')
        elif action=='drop':
            game=self.snapshot()['game']
            source,destination=fields.get('source',''),fields.get('destination','')
            if (game.get('game_id')!=fields.get('game_id') or game.get('revision')!=fields.get('revision')
                    or game.get('phase')!='human_turn'):
                raise ValueError('The position changed; pick up the piece again.')
            if (not isinstance(source,str) or not isinstance(destination,str) or len(source)!=2 or len(destination)!=2
                    or not any(m.startswith(source+destination) for m in game.get('legal_moves',[]))):
                raise ValueError('That drop is not a legal move.')
            self._update(selected=source,targets=[],promotion=[])
            self._square(destination)
        elif action=='square': self._square(str(fields.get('square','')))
        elif action=='promote':
            move=fields.get('uci')
            if move not in self.snapshot()['promotion']: raise ValueError('Choose a promotion piece.')
            self._control('move',uci=move)
            if self._promotion_physical == (move[:2], move[2:4]):
                self._confirm_human_move(*self._promotion_physical)
            self._promotion_physical = None
            self._update(selected='',targets=[],promotion=[])
            self._lights()
        elif action in {'pause','resume','takeback','resign','end','reconcile','continue_desktop'}:
            if action in {'pause','end'}: self.context.capabilities.chess_personas.cancel()
            self._resolve_uncertain()
            if action=='continue_desktop': self._hardware.disconnect()
            self._control(action)
            self._promotion_physical = None
            self._update(hardware=self._hardware.snapshot(),selected='',targets=[],promotion=[])
            if action == 'end':
                self._update(status='Game ended. No winner was declared.'
                             if self.snapshot()['game'].get('termination') == 'ended' else 'Game already finished.')
            self._lights()
            if action in {'continue_desktop','reconcile','resume'} and self.snapshot()['game'].get('phase')=='chosen_pending_announcement':
                pending=self.snapshot()['game']['pending']
                self._update(commentary=f"Recovered move: {pending['san']} — {pending['uci'][:2]} to {pending['uci'][2:4]}.")
                self._mutate('chess_finalize_move',announcement='skipped')
        elif action=='retry_persona':
            self._control('pause')
            self._control('resume')
        elif action=='activate_hardware':
            self._update(hardware=self._hardware.activate())
        elif action=='connect_hardware':
            self._hardware.connect(str(fields.get('input','')),str(fields.get('output','')))
            self._update(hardware=self._hardware.snapshot())
            self._control('hardware',enabled=True)
            self._update(status='Match the physical pieces to the displayed board, then press Physical board matches.')
        elif action=='disconnect_hardware':
            self._hardware.disconnect()
            self._update(hardware=self._hardware.snapshot())
            self._control('pause')
        elif action=='calibrate':
            self._hardware.set_leds({'a8':48,'h1':3},force=True)
            self._calibration_until=time.monotonic()+2
            self._update(status='Calibration: a8 green, h1 red. Adjust orientation if needed.')
        elif action.startswith('sound_'):
            from .sounds import update_sounds
            settings=update_sounds(self.context.storage.resolve('sounds'),self.snapshot()['preferences']['sounds'],action,fields)
            self._save_preferences({'sounds':settings})

    def _run(self, token):
        self._load()
        last_refresh=last_heartbeat=0.
        last_frame=0.
        try:
            while not self._stop.is_set() and not token.cancelled:
                try:
                    try: action,fields=self._queue.get(timeout=.04)
                    except queue.Empty: action,fields='',{}
                    if action:
                        self._update(busy=True)
                        if action!='pause': self._cancel=CancellationToken()
                        try: self._dispatch(action,fields)
                        finally: self._update(busy=False)
                    if self._hardware.snapshot()['connected']:
                        self._poll_hardware()
                        if time.monotonic()-last_frame>=.125 and time.monotonic()>=self._calibration_until:
                            self._lights()
                            last_frame=time.monotonic()
                        if time.monotonic()-last_heartbeat>2 and time.monotonic()>=self._calibration_until:
                            self._lights(force=True)
                            last_heartbeat=time.monotonic()
                    if self._opened and time.monotonic()-last_refresh>3:
                        self._refresh()
                        last_refresh=time.monotonic()
                    if self._opened: self._persona_turn()
                except Exception as exc:
                    self._update(busy=False,status=str(exc)[:400])
                    # A prepared failed turn remains awaiting_persona until Retry.
                    last_refresh=time.monotonic()
        finally:
            self._hardware.close()
            host=self.context.capabilities.chess_personas
            if host: host.cancel()
            self._launcher.close()

    def begin_shutdown(self):
        self._stop.set()
        self._cancel.cancel('chess_shutdown')
        self._update(closed=True,setup_token='')
        online=getattr(self,'_online',None)
        if online: online.begin_shutdown()

    def close(self):
        self.begin_shutdown()
        online=getattr(self,'_online',None)
        if online: online.close()
        if threading.current_thread() is not self._worker.thread:
            self.context.tasks.join_worker(self._worker)
