"""One serialized authority for rules, durable receipts and physical transactions."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import secrets
import threading
from uuid import uuid4

import chess
from .engine import candidates
from .storage_lock import StorageLock


class ChessError(ValueError):
    """A rejected command. The authoritative position has not changed."""


def physical_steps(board: chess.Board, move: chess.Move) -> list[dict]:
    if move not in board.legal_moves:
        raise ChessError('Illegal move.')
    source, target = chess.square_name(move.from_square), chess.square_name(move.to_square)
    piece = board.piece_at(move.from_square)
    steps = [dict(square=source, kind='pickup', instruction=f'Lift the {chess.piece_name(piece.piece_type)} from {source}.')]
    if board.is_capture(move):
        captured = move.to_square + (-8 if board.turn else 8) if board.is_en_passant(move) else move.to_square
        square = chess.square_name(captured)
        steps.append(dict(square=square, kind='capture', instruction=f'Remove the captured piece from {square}.'))
    steps.append(dict(square=target, kind='place', instruction=f'Place the {chess.piece_name(piece.piece_type)} on {target}.'))
    if board.is_castling(move):
        rank = chess.square_rank(move.from_square)
        kingside = move.to_square > move.from_square
        rook_from = chess.square_name(chess.square(7 if kingside else 0, rank))
        rook_to = chess.square_name(chess.square(5 if kingside else 3, rank))
        steps.extend([dict(square=rook_from, kind='pickup', instruction=f'Lift the rook from {rook_from}.'),
                      dict(square=rook_to, kind='place', instruction=f'Place the rook on {rook_to}.')])
    if move.promotion:
        steps.append(dict(square=target, kind='promotion', instruction=f'Replace the pawn on {target} with a {chess.piece_name(move.promotion)}.'))
    return steps


class Game:
    RECEIPT_LIMIT = 128

    def __init__(self, path: Path):
        self.path = Path(path)
        self._storage_lock = StorageLock(self.path.with_suffix('.lock'))
        self._lock = threading.RLock()
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='chess-engine')
        self._ticket = ''
        self._candidates: list[dict] = []
        self._analysis_status = ''
        self._analysis_error = ''
        self._closed = False
        self._data = dict(version=1, game_id=uuid4().hex, revision=0, initial_fen=chess.STARTING_FEN,
                          moves=[], human='white', persona_id='', hardware=False, reconciled=True,
                          paused=False, pending=None, resigned='', ended=False, receipts={}, engine_path='', skill=8,
                          last_event=None)
        try:
            if self.path.exists():
                value = json.loads(self.path.read_text(encoding='utf-8'))
                if not isinstance(value, dict) or value.get('version') != 1:
                    raise ChessError('Unsupported saved chess game.')
                self._data.update(value)
                self._board()  # Validate before accepting persisted state.
                if self._data['hardware'] or self._data['pending']:
                    self._data.update(hardware=False, reconciled=False, paused=True)
                # Tickets are deliberately ephemeral across a server restart.
                self._data['revision'] += 1
                self._save()
        except Exception:
            self._pool.shutdown(wait=True, cancel_futures=True)
            self._storage_lock.close()
            raise

    def _board(self) -> chess.Board:
        board = chess.Board(self._data['initial_fen'])
        for uci in self._data['moves']:
            move = chess.Move.from_uci(uci)
            if move not in board.legal_moves: raise ChessError('Invalid saved move history.')
            board.push(move)
        return board

    def _phase(self, board: chess.Board) -> str:
        if self._data['ended']: return 'game_over'
        if self._data['paused']: return 'paused'
        if self._data['pending']:
            return 'awaiting_physical_confirmation' if self._data['pending']['announced'] else 'chosen_pending_announcement'
        if board.is_game_over(claim_draw=True) or self._data['resigned']: return 'game_over'
        if self._ticket:
            return 'analysing' if self._analysis_status == 'analysing' else 'awaiting_persona'
        return 'human_turn' if board.turn == (self._data['human'] == 'white') else 'persona_turn'

    def _state(self) -> dict:
        board = self._board()
        pending = deepcopy(self._data['pending'])
        outcome = board.outcome(claim_draw=True)
        termination = ('ended' if self._data['ended'] else 'resignation' if self._data['resigned']
                       else outcome.termination.name.lower() if outcome else '')
        return dict(protocol=1, game_id=self._data['game_id'], revision=self._data['revision'],
                    fen=board.fen(), ply=len(board.move_stack), turn='white' if board.turn else 'black',
                    human=self._data['human'], persona_id=self._data['persona_id'], phase=self._phase(board),
                    hardware=self._data['hardware'], reconciled=self._data['reconciled'], pending=pending,
                    pieces=[dict(square=chess.square_name(s), piece=p.symbol(), color='white' if p.color else 'black')
                            for s,p in board.piece_map().items()],
                    legal_moves=[m.uci() for m in board.legal_moves], moves=list(self._data['moves']),
                    result='*' if self._data['ended'] else board.result(claim_draw=True) if not self._data['resigned'] else ('0-1' if self._data['resigned']=='white' else '1-0'),
                    termination=termination,
                    check=board.is_check(), last_event=deepcopy(self._data['last_event']))

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix('.tmp')
        with temporary.open('w', encoding='utf-8') as stream:
            json.dump(self._data, stream, ensure_ascii=False, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, self.path)

    def execute(self, tool: str, arguments: dict) -> dict:
        with self._lock:
            if self._closed: raise ChessError('Server is stopping.')
            if tool == 'chess_get_state': return self._state()
            if tool == 'chess_get_operation':
                receipt = self._data['receipts'].get(arguments.get('operation_id'))
                return dict(status='found', receipt=deepcopy(receipt['result'])) if receipt else dict(status='unknown')
            if tool == 'chess_get_candidates':
                self._check_ticket(arguments.get('ticket'))
                return dict(status=self._analysis_status, candidates=deepcopy(self._candidates),
                            engine=getattr(self, '_engine_label', ''), error=self._analysis_error,
                            revision=self._data['revision'])
            if tool not in {'chess_game_control','chess_prepare_turn','chess_choose_move','chess_finalize_move'}:
                raise ChessError('Unknown chess tool.')
            fingerprint = hashlib.sha256(json.dumps([tool, arguments], sort_keys=True, allow_nan=False).encode()).hexdigest()
            operation = str(arguments.get('operation_id', ''))
            old = self._data['receipts'].get(operation)
            if old:
                if old['fingerprint'] != fingerprint: raise ChessError('Operation ID was reused with different arguments.')
                return deepcopy(old['result'])
            prefix = f"{self._data['game_id']}:{self._data['revision']}:"
            if (arguments.get('game_id') != self._data['game_id'] or
                arguments.get('expected_revision') != self._data['revision'] or
                not operation.startswith(prefix) or not 8 <= len(operation[len(prefix):]) <= 80):
                raise ChessError('Stale game revision or invalid operation ID. Refresh the board.')
            before = deepcopy(self._data)
            transient = (self._ticket, self._candidates, self._analysis_status, self._analysis_error)
            try:
                extra = self._mutate(tool, arguments)
                self._data['revision'] += 1
                result = dict(state=self._state(), **extra)
                self._data['receipts'][operation] = dict(fingerprint=fingerprint, result=deepcopy(result))
                while len(self._data['receipts']) > self.RECEIPT_LIMIT:
                    del self._data['receipts'][next(iter(self._data['receipts']))]
                self._save()
            except Exception:
                self._data = before
                self._ticket, self._candidates, self._analysis_status, self._analysis_error = transient
                raise
            if tool == 'chess_prepare_turn':
                self._pool.submit(self._analyse, self._ticket, self._board(), self._data['engine_path'], self._data['skill'])
            return result

    def _check_ticket(self, ticket: str) -> None:
        if not self._ticket or not isinstance(ticket, str) or not secrets.compare_digest(ticket, self._ticket):
            raise ChessError('The persona turn ticket is expired or invalid.')

    def _invalidate(self) -> None:
        self._ticket = ''
        self._candidates = []
        self._analysis_status = ''

    def _analyse(self, ticket: str, board: chess.Board, engine_path: str, skill: int) -> None:
        try:
            choices, label = candidates(board, engine_path, skill)
            error = ''
        except Exception as exc:
            choices, label, error = [], 'Engine unavailable', str(exc)[:250]
        with self._lock:
            if self._closed or self._ticket != ticket: return
            self._candidates, self._engine_label, self._analysis_error = choices, label, error
            self._analysis_status = 'error' if error else 'ready'

    def _pending(self, board: chess.Board, move: chess.Move, *, announced: bool) -> None:
        self._data['pending'] = dict(uci=move.uci(), san=board.san(move), announced=announced,
                                     steps=physical_steps(board, move), step=0, undo=False)

    def _commit_pending(self) -> None:
        pending = self._data['pending']
        board = self._board()
        move = chess.Move.from_uci(pending['uci'])
        if pending.get('undo'):
            self._data['moves'].pop()
            self._data['last_event'] = None
        else:
            if move not in board.legal_moves: raise ChessError('The pending move is no longer legal.')
            piece = board.piece_at(move.from_square)
            kind = 'castle' if board.is_castling(move) else 'capture' if board.is_capture(move) else 'move_'+chess.piece_name(piece.piece_type)
            board.push(move)
            if board.is_checkmate(): kind = 'checkmate'
            elif board.is_game_over(claim_draw=True): kind = 'end'
            elif board.is_check(): kind = 'check'
            self._data['moves'].append(move.uci())
            self._data['last_event'] = dict(id=uuid4().hex, key=kind if kind=='end' else kind+'_'+('white' if piece.color else 'black'), san=pending['san'])
        self._data['pending'] = None
        self._invalidate()

    def _mutate(self, tool: str, args: dict) -> dict:
        board = self._board()
        phase = self._phase(board)
        if tool == 'chess_prepare_turn':
            if phase != 'persona_turn': raise ChessError('It is not the persona\'s turn.')
            pid = str(args.get('persona_id', '')).strip()
            if not pid or len(pid)>128: raise ChessError('Choose a saved NC persona.')
            self._data['persona_id'] = pid
            self._ticket = secrets.token_urlsafe(32)
            self._analysis_status, self._analysis_error, self._candidates = 'analysing', '', []
            return dict(ticket=self._ticket)
        if tool == 'chess_choose_move':
            self._check_ticket(args.get('ticket'))
            if phase != 'awaiting_persona' or self._analysis_status != 'ready': raise ChessError('Candidates are not ready.')
            choice = next((c for c in self._candidates if c['id']==args.get('candidate_id')), None)
            if not choice: raise ChessError('Choose one of the offered candidates.')
            self._pending(board, chess.Move.from_uci(choice['uci']), announced=False)
            self._invalidate()
            return {}
        if tool == 'chess_finalize_move':
            if phase != 'chosen_pending_announcement' or args.get('announcement') not in {'queued','skipped'}:
                raise ChessError('A validated move needs an announcement handoff first.')
            self._data['pending']['announced'] = True
            if not self._data['hardware']: self._commit_pending()
            return {}
        action = args.get('action')
        if action == 'new':
            if self._data['pending']: raise ChessError('Resolve the pending physical move before starting a new game.')
            human = args.get('human', 'white')
            if human not in {'white','black'}: raise ChessError('Choose white or black.')
            fen = args.get('fen') or chess.STARTING_FEN
            new = chess.Board(fen)
            if not new.is_valid(): raise ChessError('Invalid starting position.')
            self._data.update(game_id=uuid4().hex,initial_fen=fen, moves=[], human=human, resigned='', ended=False, paused=False,
                              persona_id=str(args.get('persona_id','')), last_event=dict(id=uuid4().hex,key='start'),
                              engine_path=str(args.get('engine_path','')), skill=max(0,min(20,int(args.get('skill',8)))))
            if self._data['hardware']: self._data.update(paused=True, reconciled=False)
            self._invalidate()
        elif action == 'move':
            if phase != 'human_turn' or not self._data['reconciled']: raise ChessError('The board is not ready for a human move.')
            try: move = chess.Move.from_uci(args.get('uci',''))
            except ValueError: raise ChessError('Invalid move coordinates.') from None
            if move not in board.legal_moves: raise ChessError('That move is not legal.')
            self._pending(board, move, announced=True)
            if not self._data['hardware']: self._commit_pending()
        elif action == 'physical':
            pending = self._data['pending']
            if phase != 'awaiting_physical_confirmation' or not self._data['hardware'] or not self._data['reconciled']:
                raise ChessError('No physical step is ready.')
            if args.get('square') != pending['steps'][pending['step']]['square']:
                raise ChessError('Confirm the highlighted square first.')
            confirmed = pending['steps'][pending['step']]
            pending['step'] += 1
            # A destination press confirms removal and placement together for a
            # normal capture. Keep the separate instructions for undo/recovery;
            # en passant, castling and promotion still need their own steps.
            if not pending.get('undo') and confirmed['kind'] == 'capture' and pending['step'] < len(pending['steps']):
                following = pending['steps'][pending['step']]
                if following['kind'] == 'place' and following['square'] == confirmed['square']:
                    pending['step'] += 1
            if pending['step'] == len(pending['steps']): self._commit_pending()
        elif action == 'hardware':
            if not isinstance(args.get('enabled'),bool): raise ChessError('Hardware activation must be explicit.')
            self._data.update(hardware=args['enabled'], reconciled=False, paused=True)
            self._invalidate()
        elif action == 'reconcile':
            # The user matches the displayed *uncommitted* position, then restarts steps.
            if not self._data['hardware']:
                raise ChessError('Reconnect hardware or explicitly choose Continue on screen.')
            self._data.update(reconciled=True, paused=False)
            if self._data['pending']:
                self._data['pending']['step'] = 0
        elif action == 'continue_desktop':
            self._data.update(hardware=False,reconciled=True,paused=False)
            if self._data['pending'] and self._data['pending']['announced']: self._commit_pending()
        elif action == 'pause':
            self._data['paused'] = True
            self._invalidate()
        elif action == 'resume':
            if not self._data['reconciled']: raise ChessError('Reconcile the physical position first.')
            self._data['paused'] = False
        elif action == 'takeback':
            if self._data['ended']: raise ChessError('Start a new game after ending this session.')
            if self._data['pending']: raise ChessError('Resolve the pending physical move first.')
            if not board.move_stack: raise ChessError('There are no moves to take back.')
            move = board.pop()
            if self._data['hardware']:
                steps = physical_steps(board, move)
                reverse = []
                for step in reversed(steps):
                    kind = step['kind']
                    if kind == 'promotion': instruction = f"Replace the promoted piece on {step['square']} with a pawn."
                    elif kind == 'capture': instruction = f"Restore the captured piece on {step['square']}."
                    elif kind == 'place': instruction = f"Lift the piece from {step['square']}."
                    else: instruction = f"Return the piece to {step['square']}."
                    reverse.append(dict(square=step['square'],kind='undo',instruction=instruction))
                self._data['pending'] = dict(uci=move.uci(),san=board.san(move),steps=reverse,step=0,announced=True,undo=True)
            else: self._data['moves'].pop()
            self._data.update(resigned='', last_event=None)
            self._invalidate()
        elif action == 'resign':
            if self._data['ended']: raise ChessError('This game has already ended without a winner.')
            if self._data['pending']: raise ChessError('Resolve the pending move first.')
            self._data['resigned'] = self._data['human']
            self._data['last_event'] = dict(id=uuid4().hex,key='end')
            self._invalidate()
        elif action == 'end':
            if not board.is_game_over(claim_draw=True) and not self._data['resigned']:
                self._data.update(ended=True, paused=False, pending=None,
                                  reconciled=not self._data['hardware'],
                                  last_event=dict(id=uuid4().hex, key='end'))
                self._invalidate()
        else:
            raise ChessError('Unknown chess command.')
        return {}

    def close(self) -> None:
        with self._lock: self._closed = True
        self._pool.shutdown(wait=True, cancel_futures=True)
        self._storage_lock.close()
