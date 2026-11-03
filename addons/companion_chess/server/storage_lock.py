"""One chess authority per saved game, including independently launched processes."""
import os


class StorageLock:
    def __init__(self, path):
        path.parent.mkdir(parents=True,exist_ok=True)
        self.stream=path.open('a+b')
        if path.stat().st_size==0:
            self.stream.write(b'0')
            self.stream.flush()
        self.stream.seek(0)
        try:
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(self.stream.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(self.stream,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError:
            self.stream.close()
            raise RuntimeError('Another Companion Chess Server already owns this saved game.') from None

    def close(self):
        if not self.stream.closed:
            self.stream.close()
