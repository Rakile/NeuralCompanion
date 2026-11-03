"""Separate user management and narrow owner-bound consumer ports."""
from __future__ import annotations
import threading

from .contracts import result
from .credentials import CredentialStore
from .policy import AccessPolicy, server_config
from .runtime import McpRuntime
from .storage import McpStateStore
from .transport import redact


class ConsumerPort:
    __slots__ = ('_service', '_binding')

    def __init__(self, service, binding):
        self._service = service
        self._binding = binding

    def _open(self):
        return not self._binding.closed and not self._service.runtime.closed

    def request_access(self, server_id, reason='', *, requested_tools=None, update_only=False):
        service = self._service
        with service.policy.lock:
            if not self._open() or service.storage_error:
                return result('denied')
            try:
                access = service.policy.request(self._binding.owner.addon_id, server_id, reason,
                                               requested_tools=requested_tools,update_only=update_only)
            except ValueError:
                return result('unavailable')
            service.runtime.manage({'action': 'persist'})
            return result(access['status'], access)

    def access_status(self, server_id=''):
        with self._service.policy.lock:
            if not self._open():
                return result('denied')
            return result('ok', self._service.policy.access(self._binding.owner.addon_id, server_id))

    def list_servers(self):
        service = self._service
        with service.policy.lock:
            if not self._open() or service.storage_error:
                return result('denied')
            return result('ok', [{'id':sid, 'name':config['name'],
                'status':service.runtime.connections.get(sid, {}).get('status','disconnected')}
                for sid, config in service.policy.servers.items()])

    def list_tools(self, server_id):
        with self._service.policy.lock:
            if not self._open():
                return result('denied')
            return result('ok', self._service.policy.permitted(self._binding.owner.addon_id, server_id))

    def probe_servers(self, server_ids):
        with self._service.policy.lock:
            if not self._open() or self._service.storage_error:
                return result('denied')
        return self._service.runtime.probe_servers(self._binding, server_ids)

    def invoke_tool(self, server_id, tool_name, arguments, *, is_current=None, expected_schema_fingerprint=None):
        return self._service.runtime.submit(self._binding, server_id, tool_name, arguments,
                                           is_current=is_current, expected_schema_fingerprint=expected_schema_fingerprint)

    def call_status(self, call_id):
        return self._service.runtime.call_status(self._binding, call_id)

    def cancel_call(self, call_id):
        return self._service.runtime.cancel_call(self._binding, call_id)


class McpCoreService:
    def __init__(self, context, *, vault=None):
        self.context = context
        self.vault = vault
        self.installation = str(context.paths.storage_root.resolve()).casefold()
        self.store = McpStateStore(context.storage.resolve('mcp-state-v1.json'))
        self.storage_error = ''
        self._known_secrets = set()
        self._credential_present = {}
        self._presentation_lock = threading.RLock()
        try:
            self.policy = AccessPolicy(self.store.load())
        except (ValueError, OSError):
            self.policy = AccessPolicy()
            self.storage_error = 'Saved MCP state could not be loaded. Repair it before enabling MCP.'
        self.runtime = McpRuntime(context.tasks, self.policy, persist=self._persist,
                                  credential_getter=self._get_credential, configure=self._configure,
                                  initialize=self._load_credential_presence)

    def _load_credential_presence(self):
        for sid, server in self.policy.servers.items():
            if server['auth'] != 'none':
                self._get_credential(sid)

    def credential(self, sid):
        return CredentialStore(self.installation, sid, vault=self.vault)

    def _get_credential(self, sid):
        secret = self.credential(sid).get()
        with self._presentation_lock:
            self._credential_present[sid] = bool(secret)
            if secret:
                self._known_secrets.add(secret)
        return secret

    def _persist(self):
        if self.storage_error:
            self.policy.set_master(False)
            raise ValueError('Saved state requires repair.')
        self.store.save(self.policy.export())

    def _restore(self, state):
        restored = AccessPolicy(state)
        for name in ('master', 'servers', 'addons', 'grants', 'catalogs'):
            setattr(self.policy, name, getattr(restored, name))
        self.policy.revision += 1

    def _configure(self, payload):
        """Called on the owned loop under policy lock. Save vault+state transactionally."""
        if self.storage_error:
            raise ValueError('Saved state requires repair.')
        action = payload['action']
        if action == 'save_server':
            config = server_config(payload.get('config', {}))
            sid = config['id']
            old = self.policy.servers.get(sid)
            if payload.get('config', {}).get('id') and old is None:
                raise ValueError('Unknown server to edit.')
            secret = payload.get('secret') or ''
            old_secret = self._get_credential(sid) if old and old['auth'] != 'none' else None
            identity_changed = old and any(old[k] != config[k] for k in ('endpoint', 'principal', 'auth', 'header'))
            if config['auth'] != 'none' and not secret and (not old_secret or identity_changed):
                raise ValueError('Enter credentials for the selected endpoint and account.')
        elif action == 'remove_server':
            sid = str(payload.get('server_id') or '')
            old = self.policy.servers.get(sid)
            if old is None:
                raise ValueError('Unknown server.')
            old_secret = self._get_credential(sid) if old['auth'] != 'none' else None
            secret = ''
            config = None
        else:
            raise ValueError('Unknown configuration action.')
        before = self.policy.export()
        changed_vault = False
        try:
            if config is None or config['auth'] == 'none':
                if old_secret:
                    self.credential(sid).delete()
                    changed_vault = True
            elif secret:
                self.credential(sid).set(secret)
                changed_vault = True
                with self._presentation_lock:
                    self._known_secrets.add(secret)
            if config is None:
                self.policy.remove_server(sid)
            else:
                self.policy.save_server(config)
            self._persist()
        except Exception:
            self._restore(before)
            if changed_vault:
                try:
                    if old_secret:
                        self.credential(sid).set(old_secret)
                    else:
                        self.credential(sid).delete()
                except Exception:
                    self.storage_error = 'Secure credential rollback failed. MCP access is disabled.'
                    self.policy.set_master(False)
            raise
        with self._presentation_lock:
            self._credential_present[sid] = bool(config and config['auth'] != 'none' and (secret or old_secret))
        return sid

    def snapshot(self):
        state = self.runtime.snapshot()
        with self._presentation_lock:
            state['storage_error'] = self.storage_error
            state['credentials_configured'] = dict(self._credential_present)
            secrets = tuple(self._known_secrets)
        return redact(state, secrets)

    def manage(self, payload):
        if self.storage_error:
            return result('unavailable')
        return self.runtime.manage(payload)

    def port(self, binding):
        binding.ensure_open()
        return ConsumerPort(self, binding)

    def begin_shutdown(self):
        self.runtime.begin_shutdown()

    def close(self):
        self.runtime.close()
