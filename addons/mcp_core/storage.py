"""Strict, atomic persistence in the installation's addon storage only."""
from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile

from .policy import AccessPolicy


class McpStateStore:
    def __init__(self, path):
        self.path = Path(path)

    def load(self):
        if not self.path.exists():
            return None
        try:
            if self.path.stat().st_size > 4_000_000:
                raise ValueError()
            return AccessPolicy(json.loads(self.path.read_text(encoding='utf-8'))).export()
        except (ValueError, TypeError, KeyError, AttributeError, RecursionError):
            raise ValueError('MCP state is invalid; access is disabled. Restore or repair the state file.') from None

    def save(self, state):
        data = json.dumps(AccessPolicy(state).export(), ensure_ascii=False, indent=2, allow_nan=False)
        if len(data.encode('utf-8')) > 4_000_000:
            raise ValueError('MCP state exceeds storage limit.')
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix='.mcp-', suffix='.tmp', dir=self.path.parent)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, self.path)
        finally:
            if os.path.exists(name):
                os.unlink(name)
