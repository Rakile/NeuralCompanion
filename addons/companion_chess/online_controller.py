"""Independent online session worker; never reads or writes the local game save."""
from __future__ import annotations

from copy import deepcopy
import json
import hashlib
import queue
import threading
import time
from uuid import uuid4

import chess
from core.runtime.contracts import CancellationToken
from .hardware import Hardware
from .lighting import palette_frame


class ConnectionRequired(RuntimeError):
    """Normal disconnected state, not a failed addon capability."""


class OnlineController:
    ACTIONS = {'open','refresh','availability','search','page','challenge','accept','decline','cancel',
               'invite','join','square','drop','promote','resign','draw','settings','activate_hardware',
               'connect_hardware','disconnect_hardware','reconcile'}

    def __init__(self, context, prepare_join, persona_getter=lambda:'', light_getter=lambda:{}):
        self.context, self.prepare_join = context, prepare_join
        self.persona_getter=persona_getter
        self.light_getter=light_getter
        self._account=''
        self._lock=threading.RLock(); self._stop=threading.Event(); self._queue=queue.Queue(maxsize=16)
        self._opened=False; self._pending=None; self._match_id=''; self._last_lease=0.; self._last_poll=0.
        self._hardware=Hardware(); self._hardware_revision=-1
        self._state=dict(revision=0,busy=False,connected=False,connection_required=False,status='Open Online to connect to NC Relay.',
            available=False,side='either',players=[],challenges=[],game={},selected='',targets=[],promotion=[],
            search='',offset=0,next_offset=None,invite='',invite_expires=0,commentary='',commentator=True,voice=True,foreground=False,error='',hardware=self._hardware.snapshot())
        self._comment_queue=queue.Queue(maxsize=1); self._comment_cancel=CancellationToken()
        self._worker=context.tasks.spawn('chess-online',self._run,on_cancel=lambda _:self.begin_shutdown())
        self._comment_worker=context.tasks.spawn('chess-online-commentary',self._comments,on_cancel=lambda _:self.begin_shutdown())

    def snapshot(self):
        with self._lock: return deepcopy(self._state)

    def update(self, **values):
        with self._lock:
            if any(self._state.get(k)!=v for k,v in values.items()):
                self._state.update(values); self._state['revision']+=1

    def submit(self, action, **args):
        if action not in self.ACTIONS or self._stop.is_set(): return False
        try: self._queue.put_nowait((action,deepcopy(args))); return True
        except queue.Full: return False

    def _journal(self):
        if not self._account: return
        path=self.context.storage.resolve('online/'+hashlib.sha256(self._account.encode()).hexdigest()+'.json')
        path.parent.mkdir(parents=True,exist_ok=True)
        temp=path.with_suffix('.tmp')
        temp.write_text(json.dumps(dict(match_id=self._match_id,pending=self._pending)),encoding='utf-8')
        temp.replace(path)

    @staticmethod
    def _result(reply):
        if isinstance(reply,dict) and isinstance(reply.get('error'),dict):
            error=reply['error']
            if error.get('code')=='RELAY_CONNECTION_REQUIRED':
                raise ConnectionRequired(str(error.get('message','Connect NC Relay, then press Refresh.')))
            raise RuntimeError(str(error.get('message','Online request unconfirmed; synchronize first.')))
        if not isinstance(reply,dict) or not isinstance(reply.get('result'),dict):
            raise RuntimeError('Online response unconfirmed. Synchronize before retrying.')
        return reply['result']

    def _request(self, tool, args, *, mutation=False):
        if mutation:
            if self._pending: raise RuntimeError('Synchronize the previous unconfirmed operation first.')
            args=dict(args,operation_id=uuid4().hex)
            self._pending=dict(tool=tool,args=args); self._journal()
        reply=self.context.capabilities.chess_personas.online_request(tool,args,expected_account=self._account)
        result=self._result(reply)
        if result.get('isError'):
            if mutation: self._pending=None; self._journal()
            raise ValueError(str((result.get('content') or [{}])[0].get('text','Online action rejected.'))[:250])
        value=result.get('structuredContent')
        if not isinstance(value,dict): raise RuntimeError('Invalid online response.')
        if mutation: self._pending=None; self._journal()
        return value

    def _recover(self):
        if not self._pending: return
        pending=self._pending
        # Same operation ID and arguments: never manufacture a retry move.
        reply=self.context.capabilities.chess_personas.online_request(pending['tool'],pending['args'],expected_account=self._account)
        result=self._result(reply)
        if not isinstance(result,dict) or ('isError' not in result): raise RuntimeError('Previous operation still unconfirmed.')
        value=result.get('structuredContent')
        if not result['isError'] and not isinstance(value,dict): raise RuntimeError('Previous response is malformed; keep the operation ID.')
        self._pending=None; self._journal()
        if result['isError']: return
        if pending['tool']=='chess_online_create_invite': self.update(invite=value['code'],invite_expires=value['expires_at'])
        game=value.get('match') or (value if value.get('id') and value.get('fen') else None)
        if game: self._match_id=game['id']; self._journal()

    def _publish_game(self, game):
        game=deepcopy(game)
        # Local display hints only; the relay still validates every submitted move.
        game['legal_moves']=[move.uci() for move in chess.Board(game['fen']).legal_moves] if game.get('fen') else []
        old=self.snapshot()['game']
        if game and game.get('id'):
            self._match_id=game['id']; self._journal()
        changed=game.get('revision')!=old.get('revision') or game.get('id')!=old.get('id')
        if changed:
            self.update(game=game,selected='',targets=[],promotion=[])
            if self._hardware.snapshot()['connected']:
                self._hardware_revision=-1
                self.update(status='Match the physical board to the confirmed position, then press Board matches.')
            if old and game.get('id')==old.get('id') and len(game.get('moves',[]))>len(old.get('moves',[])):
                self._comment_cancel.cancel('new_online_move'); self._comment_cancel=CancellationToken()
                cancel=getattr(self.context.capabilities.chess_personas,'cancel_online',None)
                if callable(cancel): cancel()
                try: self._comment_queue.get_nowait()
                except queue.Empty: pass
                try: self._comment_queue.put_nowait((deepcopy(game),self._comment_cancel))
                except queue.Full: pass
        self._lights()

    def _poll(self):
        if self.snapshot()['invite'] and time.time()>=self.snapshot()['invite_expires']:
            self.update(invite='',invite_expires=0)
        status=self._request('chess_lobby_status',{})
        if status['account_id']!=self._account:
            self._comment_cancel.cancel('online_account_changed')
            self._comment_cancel=CancellationToken()
            cancel=getattr(self.context.capabilities.chess_personas,'cancel_online',None)
            if callable(cancel): cancel()
            self._hardware.disconnect(); self._hardware_revision=-1
            self._account=status['account_id']; self._pending=None; self._match_id=''
            self.update(game={},available=False,invite='',commentary='',selected='',targets=[],promotion=[],hardware=self._hardware.snapshot())
            try:
                saved=self.context.storage.read_json('online/'+hashlib.sha256(self._account.encode()).hexdigest()+'.json')
                self._match_id=str(saved.get('match_id',''))[:128]; self._pending=saved.get('pending')
            except (FileNotFoundError,ValueError,TypeError): pass
        if self._pending:
            self._recover()
            status=self._request('chess_lobby_status',{})
        self.update(challenges=status['challenges'],connected=True,connection_required=False,error='')
        game=status.get('match')
        if game: self._publish_game(game)
        elif self._match_id:
            self._publish_game(self._request('chess_online_state',dict(match_id=self._match_id)))
        if self.snapshot()['available'] and not game and time.monotonic()-self._last_lease>=20:
            self._request('chess_lobby_availability',dict(enabled=True,side=self.snapshot()['side']),mutation=True)
            self._last_lease=time.monotonic()
        elif game: self.update(available=False)
        players=self._request('chess_lobby_list',dict(search=self.snapshot()['search'],offset=self.snapshot()['offset']))
        self.update(players=players['players'],next_offset=players.get('next_offset'))
        if self._hardware_revision>=0 or not self._hardware.snapshot()['connected']:
            self.update(status='Connected through NC Relay. Online positions are confirmed by Chess MCP.')

    def _move(self, uci):
        game=self.snapshot()['game']
        value=self._request('chess_online_move',dict(match_id=game['id'],expected_revision=game['revision'],uci=uci),mutation=True)
        self._publish_game(value)

    def _square(self, square):
        state=self.snapshot(); game=state['game']
        if not state['connected'] or game.get('status')!='active' or game.get('turn')!=game.get('your_side'): return
        if self._hardware.snapshot()['connected'] and self._hardware_revision!=game['revision']: return
        if len(square)!=2 or square[0] not in 'abcdefgh' or square[1] not in '12345678': return
        board=chess.Board(game['fen']); selected=state['selected']
        if selected and square in state['targets']:
            options=[m.uci() for m in board.legal_moves if m.uci().startswith(selected+square)]
            if len(options)>1: self.update(promotion=options)
            elif options: self._move(options[0])
            return
        origin=chess.parse_square(square); piece=board.piece_at(origin)
        if piece and piece.color==board.turn:
            self.update(selected=square,targets=sorted({chess.square_name(m.to_square) for m in board.legal_moves if m.from_square==origin}))
        else: self.update(selected='',targets=[],promotion=[])
        self._lights()

    def _dispatch(self, action, args):
        if action=='open': self._opened=True; self._poll(); return
        if action=='settings':
            values={k:bool(v) for k,v in args.items() if k in {'commentator','voice','foreground'}}
            self.update(**values)
            if not self.snapshot()['commentator'] or not self.snapshot()['foreground']:
                self._comment_cancel.cancel('commentary_disabled')
            if not self.snapshot()['voice'] or not self.snapshot()['commentator'] or not self.snapshot()['foreground']:
                cancel=getattr(self.context.capabilities.chess_personas,'cancel_online',None)
                if callable(cancel): cancel()
            return
        if action=='search': self.update(search=str(args.get('text',''))[:64],offset=0); self._poll(); return
        if action=='page':
            offset=args.get('offset',0)
            if type(offset) is not int or not 0<=offset<=100000: raise ValueError('Invalid lobby page.')
            self.update(offset=offset); self._poll(); return
        if action=='refresh': self._poll(); return
        if not self._account: self._poll()
        if self._pending: self._recover()
        if action=='availability':
            enabled=args.get('enabled') is True
            self._request('chess_lobby_availability',dict(enabled=enabled,side=args.get('side','either')),mutation=True)
            self.update(available=enabled,side=args.get('side','either')); self._last_lease=time.monotonic()
        elif action in {'challenge','accept','invite','join'}:
            if args.get('confirm') is not True: raise ValueError('Confirm saving the local game before joining online.')
            self.prepare_join()
            if action=='challenge': self._request('chess_lobby_challenge',dict(player_id=args['player_id']),mutation=True)
            elif action=='accept':
                value=self._request('chess_lobby_respond',dict(challenge_id=args['challenge_id'],accept=True),mutation=True)
                self._publish_game(value['match'])
            elif action=='invite':
                value=self._request('chess_online_create_invite',dict(side=args.get('side','either')),mutation=True)
                self.update(invite=value['code'],invite_expires=value['expires_at'])
            else: self._publish_game(self._request('chess_online_join_invite',dict(code=args['code']),mutation=True))
        elif action in {'decline','cancel'}:
            fields=dict(challenge_id=args['challenge_id'])
            if action=='decline': fields['accept']=False
            self._request('chess_lobby_respond' if action=='decline' else 'chess_lobby_cancel',fields,mutation=True)
        elif action=='drop':
            state=self.snapshot(); game=state['game']
            source,destination=args.get('source',''),args.get('destination','')
            if (not state['connected'] or game.get('id')!=args.get('game_id') or game.get('revision')!=args.get('revision')
                    or game.get('status')!='active' or game.get('turn')!=game.get('your_side')):
                raise ValueError('The position changed; pick up the piece again.')
            if self._hardware.snapshot()['connected'] and self._hardware_revision!=game['revision']:
                raise ValueError('Confirm the physical board first.')
            if not isinstance(source,str) or not isinstance(destination,str) or len(source)!=2 or len(destination)!=2:
                raise ValueError('Invalid drop square.')
            options=[m.uci() for m in chess.Board(game['fen']).legal_moves if m.uci().startswith(source+destination)]
            if not options: raise ValueError('That drop is not a legal move.')
            if len(options)>1: self.update(promotion=options)
            else: self._move(options[0])
            return
        elif action=='square': self._square(str(args.get('square',''))); return
        elif action=='promote':
            if args.get('uci') not in self.snapshot()['promotion']: raise ValueError('Select an offered promotion.')
            self._move(args['uci']); return
        elif action in {'resign','draw'}:
            game=self.snapshot()['game']; fields=dict(match_id=game['id'],expected_revision=game['revision'])
            if action=='draw': fields['action']=args.get('action','offer')
            self._publish_game(self._request('chess_online_'+action,fields,mutation=True))
        elif action=='activate_hardware': self.update(hardware=self._hardware.activate()); return
        elif action=='connect_hardware':
            self.prepare_join()
            self._hardware.set_model(args.get('model','launchpad_s'))
            self._hardware.connect(args['input'],args['output']); self._hardware_revision=-1
            self.update(hardware=self._hardware.snapshot(),status='Match the physical pieces, then press Board matches.'); return
        elif action=='disconnect_hardware': self._hardware.disconnect(); self.update(hardware=self._hardware.snapshot()); return
        elif action=='reconcile': self._hardware_revision=self.snapshot()['game'].get('revision',-1); self._lights(); return
        self._poll()

    def _lights(self):
        state=self.snapshot(); game=state['game']
        if not self._hardware.snapshot()['connected'] or not game: return
        self._hardware.orientation=game.get('your_side','white')
        values=palette_frame(game,state['selected'],state['targets'],self.light_getter(),time.time())
        self._hardware.set_color_leds(values)

    def _comments(self, token):
        while not self._stop.is_set() and not token.cancelled:
            try: game,cancel=self._comment_queue.get(timeout=.2)
            except queue.Empty: continue
            if not self.snapshot()['commentator'] or not self.snapshot()['foreground'] or cancel.cancelled: continue
            try:
                value=self.context.capabilities.chess_personas.commentate_online(self.persona_getter(),game,cancellation=cancel,
                    is_current=lambda:not self._stop.is_set() and not cancel.cancelled,
                    voice=self.snapshot()['voice'])
                if not cancel.cancelled: self.update(commentary=value)
            except Exception:
                if not cancel.cancelled: self.update(commentary='Move confirmed: '+str(game.get('last_san','')))

    def _run(self, token):
        last_frame=0.
        try:
            while not self._stop.is_set() and not token.cancelled:
                try:
                    try: action,args=self._queue.get(timeout=.08)
                    except queue.Empty: action,args='',{}
                    if action:
                        self.update(busy=True)
                        try: self._dispatch(action,args)
                        finally: self.update(busy=False)
                        self._last_poll=time.monotonic()
                    elif self._opened and not self.snapshot()['connection_required'] and (self.snapshot()['foreground'] or self.snapshot()['available']
                            or self.snapshot()['game'].get('status')=='active' or self.snapshot()['challenges']
                            or self.snapshot()['invite']) and time.monotonic()-self._last_poll>=4:
                        self._last_poll=time.monotonic(); self._poll()
                    if self._hardware.snapshot()['connected']:
                        for square in self._hardware.poll(): self._square(square)
                        if time.monotonic()-last_frame>=.125:
                            self._lights()
                            last_frame=time.monotonic()
                except ConnectionRequired as exc:
                    self.update(connected=False,connection_required=True,error='',status=str(exc)[:250])
                    self._last_poll=time.monotonic()
                except ValueError as exc:
                    self.update(error=str(exc)[:250],status='Online action rejected; match unchanged.')
                    self._last_poll=time.monotonic()
                except Exception as exc:
                    self.update(connected=False,error=str(exc)[:250],status='Online unavailable. Local single-player is unaffected.')
                    self._last_poll=time.monotonic()
        finally: self._hardware.close()

    def begin_shutdown(self):
        self._stop.set(); self._comment_cancel.cancel('online_closed')
        cancel=getattr(self.context.capabilities.chess_personas,'cancel_online',None)
        if callable(cancel): cancel()

    def close(self):
        self.begin_shutdown()
        for worker in (self._worker,self._comment_worker): self.context.tasks.join_worker(worker)
