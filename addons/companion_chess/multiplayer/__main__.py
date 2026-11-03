"""Private authority entry point. Run explicitly with Python 3.11."""
import argparse
import os
from pathlib import Path
import sys

from .store import OnlineStore
from .transport import OnlineMcpServer


def main():
    if sys.version_info[:2] != (3,11):
        raise SystemExit('Companion Chess multiplayer requires Python 3.11.')
    parser=argparse.ArgumentParser(description='Private NC Relay Chess MCP authority')
    parser.add_argument('--storage',type=Path,required=True)
    parser.add_argument('--port',type=int,default=8767)
    parser.add_argument('--private-container-network',action='store_true')
    args=parser.parse_args()
    keyfile=os.environ.get('NC_CHESS_GATEWAY_KEY_FILE','')
    key=Path(keyfile).read_text().strip() if keyfile else os.environ.pop('NC_CHESS_GATEWAY_KEY','')
    store=OnlineStore(args.storage/'online.sqlite3')
    with OnlineMcpServer(('0.0.0.0' if args.private_container_network else '127.0.0.1',args.port),store,key,
                         private_container_network=args.private_container_network) as server:
        server.serve_forever(poll_interval=.2)


if __name__=='__main__': main()
