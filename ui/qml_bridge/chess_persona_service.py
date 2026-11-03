"""Host-bound chess persona turns, reusing NC providers, tool grants and speech."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
import json
import threading
from uuid import uuid4

from core import chat_providers
from core.conversation_tools import TOOL_OPTION, ToolCall, decode_tool_round, strict_arguments
from core.native_tool_calls import provider_protocol
from core.persona_overrides import apply_persona_overrides


class ChessPersonaService:
    def __init__(self, *, persona_store, config_snapshot, providers, invoke_chat_mcp, speech, online_mcp=None):
        self.store=persona_store
        self.config_snapshot=config_snapshot
        self.providers=providers
        self.invoke=invoke_chat_mcp
        self.speech=speech
        self.online_mcp=online_mcp

    def bind(self, *, addon_id, generation, owner_is_open):
        if addon_id!='nc.companion_chess': raise PermissionError('Chess persona service is owner-bound.')
        return _BoundChessPersona(self, owner_is_open)


class _BoundChessPersona:
    def __init__(self, service, owner_is_open):
        self._service=service
        self._owner_is_open=owner_is_open
        self._speech_control=None
        self._online_speech_control=None
        self._lock=threading.RLock()

    def _records(self):
        if not self._owner_is_open(): raise RuntimeError('Chess addon is closed.')
        return [deepcopy(p) for p in (self._service.store.load().get('personas') or {}).values() if isinstance(p,dict) and p.get('id')]

    def personas(self):
        return [dict(id=p['id'],name=p.get('name','Persona'),avatar=p.get('avatar_path','')) for p in self._records()]

    def server_credential(self, installation_id):
        """Reuse the existing Windows vault adapter, under a separate chess target."""
        if not self._owner_is_open(): raise RuntimeError('Chess addon is closed.')
        import hashlib
        import secrets
        from addons.mcp_core.credentials import WindowsVault
        vault=WindowsVault()
        target='NeuralCompanion/CompanionChess/'+hashlib.sha256(installation_id.encode()).hexdigest()[:32]
        secret=vault.read(target)
        if not secret:
            secret=secrets.token_urlsafe(40)
            vault.write(target,secret)
        return secret

    def online_request(self, tool, arguments, *, expected_account=''):
        if not self._owner_is_open() or self._service.online_mcp is None:
            raise RuntimeError('Online chess service unavailable.')
        if not isinstance(tool,str) or not tool.startswith(('chess_lobby_','chess_online_')):
            raise PermissionError('Only online chess operations are allowed.')
        return self._service.online_mcp(dict(jsonrpc='2.0',id=uuid4().hex,method='tools/call',
                                            params=dict(name=tool,arguments=arguments,_meta=dict(expectedAccount=expected_account))))

    def commentate_online(self, persona_id, game, *, cancellation, is_current, voice=True):
        """Read-only completed-move narration. No MCP grants, tools or engine access."""
        if not self._owner_is_open() or not is_current(): return ''
        record=next((p for p in self._records() if p['id']==persona_id),None)
        if record is None: return 'Move confirmed: '+str(game.get('last_san',''))
        service=self._service
        config=apply_persona_overrides(service.config_snapshot(),record.get('overrides'))
        config.update(voice_path=str(record.get('voice_path') or ''),tts_use_cloned_voice=bool(record.get('use_cloned_voice',True)))
        provider=str(config.get('chat_provider') or ''); model=str(config.get('model_name') or '')
        system=str(record.get('system_prompt') or '')+'\n'+str(record.get('emotional_instructions') or '')
        system+='\nYou are a private chess commentator. Briefly react to the last confirmed move only. Do not suggest future moves, engine evaluations or claim actions. No tools are available. Use one or two short sentences.'
        # Only public completed-move facts; no account IDs, invitations or credentials.
        public={key:game.get(key) for key in ('fen','moves','last_san','turn','check','result')}
        raw=service.providers.complete(dict(model=model,messages=[dict(role='system',content=system),
            dict(role='user',content=json.dumps(public))],max_tokens=160),{},provider_id=provider,model_id=model,
            cancellation=cancellation,require_exact_provider=True)
        if not is_current() or cancellation.cancelled: return ''
        text=str(raw).strip()[:600]
        if voice and text:
            with self._lock:
                if self._owner_is_open() and is_current():
                    try: self._online_speech_control=service.speech(text,voice_path=config['voice_path'],runtime_config=config)
                    except RuntimeError: pass
        return text

    def choose(self, *, persona_id, server_id, state, ticket, candidates, operation_id, cancellation, is_current):
        service=self._service
        record=next((p for p in self._records() if p['id']==persona_id),None)
        if record is None: raise ValueError('The selected saved persona is unavailable.')
        config=apply_persona_overrides(service.config_snapshot(),record.get('overrides'))
        config.update(voice_path=str(record.get('voice_path') or ''),tts_use_cloned_voice=bool(record.get('use_cloned_voice',True)))
        current=lambda:bool(self._owner_is_open() and not cancellation.cancelled and is_current())
        offer=service.invoke('offer',dict(persona_id=persona_id,current_persona=lambda:persona_id,
            is_current=current,scope_server_id=server_id,scope_tool_names=['chess_choose_move']))
        if not offer or not offer.get('available') or len(offer.get('tools',[]))!=1:
            raise PermissionError('Grant chess_choose_move to Chat MCP Tools and assign it to this persona in Persona → MCP.')
        tool=offer['tools'][0]
        binding=dict(game_id=state['game_id'],expected_revision=state['revision'],operation_id=operation_id,ticket=ticket)
        allowed={c['id'] for c in candidates}
        provider=str(config.get('chat_provider') or '')
        model=str(config.get('model_name') or '')
        protocol=provider_protocol(chat_providers.get_provider(provider))
        system=str(record.get('system_prompt') or '')+'\n'+str(record.get('emotional_instructions') or '')
        system+='\nYou are playing chess. Choose exactly one supplied candidate. Give at most two short sentences of in-character commentary, without claiming an unconfirmed move was made.'
        facts=dict(fen=state['fen'],candidates=candidates,required_arguments=binding)
        if state.get('comment_user_moves') is True and state.get('moves'):
            facts['last_human_move']=dict(uci=state['moves'][-1],san=(state.get('last_event') or {}).get('san',''))
            system+=" React briefly to your human opponent's last confirmed move in your commentary, then explain your chosen response. Do not invent engine scores or unconfirmed facts."
        prompt=json.dumps(facts,ensure_ascii=False)
        if protocol:
            prompt+='\nCall the offered move tool once with the exact required arguments and chosen candidate_id. Put commentary in your response text.'
        else:
            prompt+='\nReturn only JSON: {"candidate_id":"one offered ID","commentary":"short in-character thought"}.'
        params=dict(model=model,messages=[dict(role='system',content=system),dict(role='user',content=prompt)],max_tokens=700)
        # NC provider preparation consumes canonical messages and performs its
        # own Responses/Anthropic conversion. Converting here loses the prompt.
        commentary=''
        candidate=''
        fallback=False
        for attempt in range(2):
            if not current(): raise RuntimeError('Chess turn cancelled.')
            additional={TOOL_OPTION:dict(tools=offer['tools'],input=[])} if protocol else {}
            raw=service.providers.complete(params,additional,provider_id=provider,model_id=model,
                cancellation=cancellation,require_exact_provider=True)
            if not current(): raise RuntimeError('Chess turn cancelled.')
            try:
                if len(raw)>64000: raise ValueError('Response too long.')
                if protocol:
                    response=decode_tool_round(raw)
                    if len(response.calls)!=1 or response.calls[0].name!=tool['name']: raise ValueError('Choose once using the offered tool.')
                    args=strict_arguments(response.calls[0].arguments)
                    if set(args)!=set(binding)|{'candidate_id'} or any(args.get(k)!=v for k,v in binding.items()):
                        raise ValueError('Use the exact host-provided turn arguments.')
                    candidate=args['candidate_id']
                    commentary=response.text[:600]
                else:
                    parsed=strict_arguments(raw)
                    candidate=parsed.get('candidate_id')
                    if not isinstance(parsed.get('commentary',''),str): raise ValueError('Commentary must be text.')
                    commentary=parsed.get('commentary','')[:600]
                if candidate not in allowed: raise ValueError('Choose an offered candidate.')
                break
            except (ValueError,TypeError,KeyError):
                candidate=''
                # Retry the original request with a correction, not consecutive
                # user turns (strict model templates reject those). Do not replay
                # a rejected native tool call as assistant history.
                if attempt == 0:
                    params['messages'][-1]['content']+='\n\nInvalid choice. Try once more: select one offered candidate, use the exact arguments and required format.'
        if not candidate:
            candidate=candidates[0]['id']
            commentary=''
            fallback=True
        if not current(): raise RuntimeError('Chess turn cancelled.')
        call=ToolCall(uuid4().hex,tool['name'],json.dumps(dict(binding,candidate_id=candidate)))
        # Even JSON and engine fallback choices cross the same persona grant boundary.
        outcome=service.invoke('execute',dict(ticket=offer['ticket'],call=asdict(call)))
        if not outcome or not outcome.get('ok'):
            raise RuntimeError('Persona move completion is unconfirmed. Resolve the operation before retrying.')
        result=outcome.get('content',{}).get('result',{})
        if result.get('isError'): raise ValueError('The chess server rejected the persona choice.')
        receipt=result.get('structuredContent')
        if not isinstance(receipt,dict) or not receipt.get('state',{}).get('pending'):
            raise RuntimeError('Persona move response is unconfirmed.')
        return dict(receipt=receipt,commentary=commentary,fallback=fallback,voice_path=config['voice_path'],
                    voice_config=config,persona_name=record.get('name','Persona'),
                    grant_ticket=offer['ticket'])

    def announce(self, text, choice, *, is_current):
        with self._lock:
            if not self._owner_is_open() or not is_current(): return False
            status=self._service.invoke('current',dict(ticket=choice['grant_ticket']))
            if not status or not status.get('current'): return False
            try:
                self._speech_control=self._service.speech(text,voice_path=choice['voice_path'],runtime_config=choice['voice_config'])
                return True
            except RuntimeError:
                return False

    def cancel_online(self):
        with self._lock:
            control,self._online_speech_control=self._online_speech_control,None
        if control is not None: control.cancel('online_chess_cancelled')

    def cancel(self):
        with self._lock:
            control,self._speech_control=self._speech_control,None
        if control is not None:
            control.cancel('chess_cancelled')

    close=cancel
