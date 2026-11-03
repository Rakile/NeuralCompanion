"""Bounded engine analysis; optional Stockfish, deterministic legal fallback."""
from __future__ import annotations

from pathlib import Path
import chess
import chess.engine
from ..engine_paths import resolve_engine_path


def candidates(board: chess.Board, engine_path: str = '', skill: int = 8) -> tuple[list[dict], str]:
    count = min(4, board.legal_moves.count())
    if not count:
        return [], 'Game over'
    engine_path = resolve_engine_path(engine_path)
    if engine_path:
        if not Path(engine_path).is_file():
            raise ValueError('The selected Stockfish executable is unavailable.')
        with chess.engine.SimpleEngine.popen_uci(engine_path, timeout=8) as engine:
            options = {'Threads': 1, 'Hash': 32}
            if 'Skill Level' in engine.options:
                options['Skill Level'] = max(0, min(20, skill))
            engine.configure(options)
            analysis = engine.analyse(board, chess.engine.Limit(time=.5), multipv=count)
            moves = [info['pv'][0] for info in analysis if info.get('pv')]
        label = 'Stockfish'
    else:
        # A bounded one-ply material/check policy keeps offline play usable.
        values = {chess.PAWN:100, chess.KNIGHT:320, chess.BISHOP:330,
                  chess.ROOK:500, chess.QUEEN:900, chess.KING:0}
        def score(move: chess.Move) -> int:
            target = board.piece_at(move.to_square)
            value = values.get(target.piece_type, 0) if target else 0
            if board.is_en_passant(move): value += 100
            if move.promotion: value += values[move.promotion] - 100
            trial = board.copy(stack=False)
            trial.push(move)
            if trial.is_checkmate(): return 100000
            if trial.is_check(): value += 20
            center = 7 - abs(2*chess.square_file(move.to_square)-7) - abs(2*chess.square_rank(move.to_square)-7)
            return value + center
        moves = sorted(board.legal_moves, key=lambda m: (-score(m), m.uci()))[:count]
        label = 'Built-in basic engine'
    return [dict(id=m.uci(), uci=m.uci(), san=board.san(m), rank=i+1)
            for i, m in enumerate(moves) if m in board.legal_moves], label
