"""python -m addons.companion_chess.server --storage ... --installation-id ..."""
import argparse
import os
from pathlib import Path

from .game import Game
from .transport import ChessHttpServer


def main() -> None:
    parser = argparse.ArgumentParser(description='Companion Chess local MCP server')
    parser.add_argument('--storage', type=Path, required=True)
    parser.add_argument('--installation-id', required=True)
    parser.add_argument('--port', type=int, default=8766)
    args = parser.parse_args()
    token = os.environ.pop('NC_CHESS_BEARER_TOKEN','')
    game = Game(args.storage / 'game-v1.json')
    try:
        with ChessHttpServer(('127.0.0.1',args.port),game,token,args.installation_id) as server:
            server.serve_forever(poll_interval=.2)
    finally: game.close()


if __name__ == '__main__': main()
