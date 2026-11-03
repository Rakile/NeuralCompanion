"""Python 3.11 transactional lobby and chess authority, independent of local saves.

Only a trusted gateway supplies actor/name. Neither is accepted in tool arguments.
SQLite immediate transactions serialize decisions across threads/processes.
"""
from __future__ import annotations

from contextlib import closing
import hashlib
import json
from pathlib import Path
import secrets
import sqlite3
import time
from typing import Callable
from uuid import uuid4

import chess


class OnlineError(ValueError):
    """Safe rejection; the entire operation is rolled back."""


READ_TOOLS = {'chess_lobby_list', 'chess_lobby_status', 'chess_online_state'}
FIELDS = {
    'chess_lobby_list': {'search', 'offset'}, 'chess_lobby_status': set(),
    'chess_lobby_availability': {'enabled', 'side'},
    'chess_lobby_challenge': {'player_id'}, 'chess_lobby_respond': {'challenge_id', 'accept'},
    'chess_lobby_cancel': {'challenge_id'},
    'chess_online_create_invite': {'side'}, 'chess_online_join_invite': {'code'},
    'chess_online_state': {'match_id'}, 'chess_online_move': {'match_id', 'expected_revision', 'uci'},
    'chess_online_resign': {'match_id', 'expected_revision'},
    'chess_online_draw': {'match_id', 'expected_revision', 'action'},
}


class OnlineStore:
    def __init__(self, path: Path, *, clock: Callable[[], float] = time.time):
        self.path, self.clock = Path(path), clock
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as db:
            db.executescript('''
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS availability (
                    actor TEXT PRIMARY KEY, public_id TEXT UNIQUE NOT NULL, name TEXT NOT NULL,
                    side TEXT NOT NULL, expires REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS challenges (
                    id TEXT PRIMARY KEY, source TEXT NOT NULL, target TEXT NOT NULL,
                    source_name TEXT NOT NULL, target_name TEXT NOT NULL, side TEXT NOT NULL,
                    state TEXT NOT NULL, expires REAL NOT NULL, match_id TEXT);
                CREATE INDEX IF NOT EXISTS challenge_people ON challenges(source,target,state);
                CREATE TABLE IF NOT EXISTS matches (
                    id TEXT PRIMARY KEY, white TEXT NOT NULL, black TEXT NOT NULL, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS members (actor TEXT PRIMARY KEY, match_id TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS invites (
                    code TEXT PRIMARY KEY, actor TEXT NOT NULL, name TEXT NOT NULL, side TEXT NOT NULL,
                    expires REAL NOT NULL, match_id TEXT);
                CREATE TABLE IF NOT EXISTS receipts (
                    actor TEXT NOT NULL, operation TEXT NOT NULL, fingerprint TEXT NOT NULL,
                    response TEXT NOT NULL, PRIMARY KEY(actor,operation));
            ''')

    def _connect(self):
        db = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        db.row_factory = sqlite3.Row
        return db

    def execute(self, actor: str, name: str, tool: str, arguments: dict, *, operation_id: str = '') -> dict:
        if not isinstance(actor, str) or not 1 <= len(actor) <= 128 or not isinstance(name, str) or not 1 <= len(name) <= 64:
            raise OnlineError('Verified account identity required.')
        if tool not in FIELDS or not isinstance(arguments, dict) or set(arguments) - FIELDS[tool]:
            raise OnlineError('Unknown tool or arguments.')
        if tool not in READ_TOOLS and (not isinstance(operation_id,str) or not 1 <= len(operation_id) <= 160):
            raise OnlineError('An operation ID is required.')
        fingerprint = hashlib.sha256(json.dumps([tool,arguments],sort_keys=True,allow_nan=False).encode()).hexdigest()
        with closing(self._connect()) as db:
            db.execute('BEGIN IMMEDIATE')
            try:
                if tool not in READ_TOOLS:
                    previous = db.execute('SELECT * FROM receipts WHERE actor=? AND operation=?',(actor,operation_id)).fetchone()
                    if previous:
                        if previous['fingerprint'] != fingerprint: raise OnlineError('Operation ID already used for another request.')
                        db.commit()
                        return json.loads(previous['response'])
                now = self.clock()
                db.execute("UPDATE challenges SET state='expired' WHERE state='pending' AND expires<=?",(now,))
                result = self._dispatch(db,actor,name,tool,arguments,now)
                if tool not in READ_TOOLS:
                    db.execute('INSERT INTO receipts VALUES (?,?,?,?)',(actor,operation_id,fingerprint,json.dumps(result,allow_nan=False)))
                db.commit()
                return result
            except BaseException:
                db.rollback()
                raise

    @staticmethod
    def _side(value):
        if value not in {'white','black','either'}: raise OnlineError('Choose White, Black or Either.')
        return value

    @staticmethod
    def _free(db, actor):
        if db.execute('SELECT 1 FROM members WHERE actor=?',(actor,)).fetchone():
            raise OnlineError('This player already has an active online match.')

    def _dispatch(self, db, actor, name, tool, args, now):
        if tool == 'chess_lobby_availability':
            if type(args.get('enabled')) is not bool: raise OnlineError('Availability must be true or false.')
            if not args['enabled']:
                db.execute('DELETE FROM availability WHERE actor=?',(actor,))
                return dict(available=False)
            self._free(db,actor)
            side = self._side(args.get('side','either'))
            row = db.execute('SELECT public_id FROM availability WHERE actor=?',(actor,)).fetchone()
            public = row['public_id'] if row else uuid4().hex
            db.execute('INSERT OR REPLACE INTO availability VALUES (?,?,?,?,?)',(actor,public,name,side,now+75))
            return dict(available=True,player_id=public,expires_at=now+75)
        if tool == 'chess_lobby_list':
            query = args.get('search',''); offset = args.get('offset',0)
            if not isinstance(query,str) or len(query)>64 or type(offset) is not int or not 0<=offset<=100000:
                raise OnlineError('Invalid player search.')
            # Heartbeats do not reorder the stable name/id listing. No account IDs leave the service.
            rows = db.execute('''SELECT public_id,name,side FROM availability a WHERE expires>?
                AND actor!=? AND NOT EXISTS(SELECT 1 FROM members m WHERE m.actor=a.actor)
                AND instr(lower(name),lower(?))>0 ORDER BY lower(name),public_id LIMIT 51 OFFSET ?''',
                (now,actor,query,offset)).fetchall()
            return dict(players=[dict(player_id=r['public_id'],name=r['name'],side=r['side']) for r in rows[:50]],
                        next_offset=offset+50 if len(rows)>50 else None)
        if tool == 'chess_lobby_status':
            rows = db.execute("SELECT * FROM challenges WHERE (source=? OR target=?) AND state='pending' ORDER BY expires LIMIT 50",(actor,actor)).fetchall()
            active = db.execute('SELECT match_id FROM members WHERE actor=?',(actor,)).fetchone()
            return dict(account_id=actor,challenges=[self._challenge(r,actor) for r in rows],
                        match=self._state(db,active['match_id'],actor) if active else None)
        if tool == 'chess_lobby_challenge':
            self._free(db,actor)
            own = db.execute('SELECT * FROM availability WHERE actor=? AND expires>?',(actor,now)).fetchone()
            other = db.execute('SELECT * FROM availability WHERE public_id=? AND expires>?',(args.get('player_id'),now)).fetchone()
            if not own or not other or other['actor']==actor: raise OnlineError('Both players must be available.')
            self._free(db,other['actor'])
            if db.execute("SELECT 1 FROM challenges WHERE source=? AND state='pending'",(actor,)).fetchone():
                raise OnlineError('Cancel the pending challenge first.')
            side = self._compatible(own['side'],other['side'])
            cid = uuid4().hex
            db.execute('INSERT INTO challenges VALUES (?,?,?,?,?,?,?,?,NULL)',
                       (cid,actor,other['actor'],name,other['name'],side,'pending',now+60))
            return self._challenge(db.execute('SELECT * FROM challenges WHERE id=?',(cid,)).fetchone(),actor)
        if tool in {'chess_lobby_respond','chess_lobby_cancel'}:
            row = db.execute('SELECT * FROM challenges WHERE id=?',(args.get('challenge_id'),)).fetchone()
            if not row or row['state']!='pending' or row['expires']<=now: raise OnlineError('Challenge is no longer pending.')
            if tool=='chess_lobby_cancel':
                if row['source']!=actor: raise OnlineError('Only the challenger may cancel.')
                db.execute("UPDATE challenges SET state='cancelled' WHERE id=?",(row['id'],))
                return dict(id=row['id'],state='cancelled')
            if row['target']!=actor or type(args.get('accept')) is not bool: raise OnlineError('Only the invited player may respond.')
            if not args['accept']:
                db.execute("UPDATE challenges SET state='declined' WHERE id=?",(row['id'],))
                return dict(id=row['id'],state='declined')
            for person in (row['source'],actor):
                if not db.execute('SELECT 1 FROM availability WHERE actor=? AND expires>?',(person,now)).fetchone():
                    raise OnlineError('A player is no longer available.')
            mid = self._create(db,row['source'],row['source_name'],actor,name,row['side'])
            db.execute("UPDATE challenges SET state='accepted',match_id=? WHERE id=?",(mid,row['id']))
            return dict(id=row['id'],state='accepted',match=self._state(db,mid,actor))
        if tool=='chess_online_create_invite':
            self._free(db,actor)
            side=self._side(args.get('side','either'))
            db.execute('DELETE FROM invites WHERE actor=? AND match_id IS NULL',(actor,))
            code=secrets.token_hex(5).upper()
            db.execute('INSERT INTO invites VALUES (?,?,?,?,?,NULL)',(code,actor,name,side,now+600))
            return dict(code=code,expires_at=now+600)
        if tool=='chess_online_join_invite':
            code=args.get('code','')
            if not isinstance(code,str) or len(code)>32: raise OnlineError('Invalid invitation.')
            row=db.execute('SELECT * FROM invites WHERE code=?',(code.strip().upper(),)).fetchone()
            if not row or row['expires']<=now or row['match_id'] or row['actor']==actor: raise OnlineError('Invitation is unavailable.')
            mid=self._create(db,row['actor'],row['name'],actor,name,row['side'])
            db.execute('UPDATE invites SET match_id=? WHERE code=?',(mid,row['code']))
            return self._state(db,mid,actor)
        if tool=='chess_online_state': return self._state(db,args.get('match_id'),actor)
        row=db.execute('SELECT * FROM matches WHERE id=?',(args.get('match_id'),)).fetchone()
        if not row or actor not in (row['white'],row['black']): raise OnlineError('Match is unavailable.')
        game=json.loads(row['payload'])
        if game['status']!='active': raise OnlineError('Match has ended.')
        if type(args.get('expected_revision')) is not int or args['expected_revision']!=game['revision']:
            raise OnlineError('Position changed; synchronize the match before retrying.')
        board=self._board(game)
        side='white' if actor==row['white'] else 'black'
        if tool=='chess_online_move':
            if (board.turn==chess.WHITE)!=(side=='white'): raise OnlineError('It is not your turn.')
            try: move=chess.Move.from_uci(args.get('uci',''))
            except (ValueError,TypeError): raise OnlineError('Invalid move.') from None
            if move not in board.legal_moves: raise OnlineError('Illegal move.')
            game['last_san']=board.san(move); board.push(move); game['moves'].append(move.uci()); game['draw_offer']=None
            outcome=board.outcome(claim_draw=False)
            if outcome: game.update(status='ended',result=outcome.result())
        elif tool=='chess_online_resign': game.update(status='ended',result='0-1' if side=='white' else '1-0')
        elif tool=='chess_online_draw':
            action=args.get('action')
            if action=='offer':
                if game['draw_offer']: raise OnlineError('There is already a draw offer.')
                game['draw_offer']=side
            elif action=='accept':
                if not game['draw_offer'] or game['draw_offer']==side: raise OnlineError('Only the opponent may accept an offered draw.')
                game.update(status='ended',result='1/2-1/2')
            elif action=='decline':
                if not game['draw_offer'] or game['draw_offer']==side: raise OnlineError('No opponent draw offer.')
                game['draw_offer']=None
            elif action=='claim':
                if (board.turn==chess.WHITE)!=(side=='white') or not board.can_claim_draw(): raise OnlineError('No claimable draw.')
                game.update(status='ended',result='1/2-1/2')
            else: raise OnlineError('Unknown draw action.')
        else: raise OnlineError('Unknown online action.')
        game['revision']+=1
        db.execute('UPDATE matches SET payload=? WHERE id=?',(json.dumps(game),row['id']))
        if game['status']=='ended': db.execute('DELETE FROM members WHERE match_id=?',(row['id'],))
        return self._state(db,row['id'],actor)

    @staticmethod
    def _compatible(source, target):
        if source=='either': return 'black' if target=='white' else 'white'
        if source==target: raise OnlineError('Players requested the same side.')
        return source

    def _create(self, db, source, source_name, target, target_name, side):
        self._free(db,source); self._free(db,target)
        if source==target: raise OnlineError('Choose another player.')
        white,black=(source,target) if side!='black' else (target,source)
        mid=uuid4().hex
        game=dict(revision=0,moves=[],names={source:source_name,target:target_name},status='active',result='*',draw_offer=None,last_san='')
        db.execute('INSERT INTO matches VALUES (?,?,?,?)',(mid,white,black,json.dumps(game)))
        for person in (source,target):
            db.execute('INSERT INTO members VALUES (?,?)',(person,mid))
            db.execute('DELETE FROM availability WHERE actor=?',(person,))
            db.execute("UPDATE challenges SET state='busy' WHERE state='pending' AND (source=? OR target=?)",(person,person))
            db.execute('DELETE FROM invites WHERE actor=? AND match_id IS NULL',(person,))
        return mid

    @staticmethod
    def _board(game):
        board=chess.Board()
        for uci in game['moves']: board.push_uci(uci)
        return board

    def _state(self, db, mid, actor):
        row=db.execute('SELECT * FROM matches WHERE id=?',(mid,)).fetchone()
        if not row or actor not in (row['white'],row['black']): raise OnlineError('Match is unavailable.')
        game=json.loads(row['payload']); board=self._board(game)
        return dict(id=mid,game_id=mid,revision=game['revision'],fen=board.fen(),moves=game['moves'],ply=board.ply(),
                    your_side='white' if actor==row['white'] else 'black',turn='white' if board.turn else 'black',
                    players=[dict(name=game['names'][row[c]],side=c) for c in ('white','black')],
                    status=game['status'],result=game['result'],draw_offer=game['draw_offer'],last_san=game['last_san'],
                    check=board.is_check(),pieces=[dict(square=chess.square_name(s),piece=p.symbol(),color='white' if p.color else 'black')
                                                  for s,p in board.piece_map().items()])

    @staticmethod
    def _challenge(row, actor):
        return dict(id=row['id'],incoming=row['target']==actor,name=row['source_name'] if row['target']==actor else row['target_name'],
                    state=row['state'],expires_at=row['expires'],side=row['side'])
