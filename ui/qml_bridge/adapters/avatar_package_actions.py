"""Use the public UI reservation to keep package maintenance outside live chats."""
from contextlib import contextmanager


def can_maintain_packages(application):
    access = getattr(application, 'avatar_creation', None)
    try:
        return access is not None and access.snapshot()['phase'] == 'free'
    except Exception:
        return False


@contextmanager
def package_maintenance(application):
    access = getattr(application, 'avatar_creation', None)
    if access is None:
        raise RuntimeError('Package maintenance is unavailable in this runtime.')
    token = access.reserve()
    try:
        access.claim(token)
        yield
    finally:
        access.begin_cleanup(token)
        access.finish(token, cleanup_ok=True)
