"""Deny-by-default policy. Runtime serializes policy and dispatch using this lock."""
from __future__ import annotations

import hashlib
import json
import re
import threading
from urllib.parse import urlsplit
from uuid import uuid4

from .contracts import copy_value

SERVER_KEYS = {'id', 'name', 'endpoint', 'auth', 'principal', 'header'}


def server_config(value, server_id=None):
    if not isinstance(value, dict) or set(value) - SERVER_KEYS:
        raise ValueError('Unsupported server configuration fields.')
    endpoint = str(value.get('endpoint', '')).strip()
    parsed = urlsplit(endpoint)
    if (parsed.scheme not in {'http', 'https'} or not parsed.hostname or parsed.username
            or parsed.password or parsed.fragment or parsed.query):
        raise ValueError('Use an HTTP(S) endpoint without user info, query secrets or fragments.')
    try:
        parsed.port
    except ValueError:
        raise ValueError('Invalid endpoint port.') from None
    auth = str(value.get('auth', 'none'))
    principal = str(value.get('principal', '')).strip()
    header = str(value.get('header', '')).strip()
    if auth not in {'none', 'bearer', 'api_key'}:
        raise ValueError('Unsupported authentication. OAuth is not supported.')
    if auth != 'none' and (not principal or len(principal) > 200):
        raise ValueError('An account identity label is required for authenticated connections.')
    if auth == 'api_key' and (not re.fullmatch(r'[A-Za-z0-9-]+', header) or
            header.lower() in {'host', 'content-type', 'accept', 'content-length', 'connection',
                               'mcp-session-id', 'mcp-protocol-version', 'authorization'}):
        raise ValueError('Choose a custom API-key header, such as X-API-Key.')
    return {'id': server_id or str(value.get('id') or uuid4().hex),
            'name': str(value.get('name', '')).strip()[:200] or parsed.hostname,
            'endpoint': endpoint, 'auth': auth,
            'principal': principal if auth != 'none' else '',
            'header': header if auth == 'api_key' else ''}


def fingerprint(schema):
    return hashlib.sha256(json.dumps(schema, sort_keys=True, separators=(',', ':'),
                                    allow_nan=False).encode()).hexdigest()


def requested_tool_specs(value):
    """Consumer-declared intent for review, never an authorization rule."""
    if not isinstance(value, list) or len(value)>32:
        raise ValueError('Requested tools must be a list of at most 32 declarations.')
    result = []
    for spec in value:
        if (not isinstance(spec,dict) or set(spec)-{'name','match'} or
                not isinstance(spec.get('name'),str) or not spec['name'] or len(spec['name'])>256 or
                not isinstance(spec.get('match','exact'),str) or
                spec.get('match','exact') not in {'exact','name_or_namespace'}):
            raise ValueError('Invalid requested tool declaration.')
        normalized = {'name':spec['name'],'match':spec.get('match','exact')}
        if normalized not in result:
            result.append(normalized)
    return result


class AccessPolicy:
    def __init__(self, state=None):
        self.lock = threading.RLock()
        self.master = False
        self.servers = {}
        self.addons = {}
        self.grants = {}
        self.catalogs = {}
        self.revision = 0
        if state is not None:
            if (not isinstance(state, dict) or set(state) !=
                    {'version', 'master', 'servers', 'addons', 'grants', 'catalogs'} or
                    state['version'] != 1 or not isinstance(state['master'], bool)):
                raise ValueError('Unsupported MCP state.')
            self.master = state['master']
            for sid, config in state['servers'].items():
                if config.get('id') != sid:
                    raise ValueError('Invalid server identity.')
                self.save_server(config)
            for sid, tools in state['catalogs'].items():
                self.catalog(sid, list(tools.values()))
            for aid, item in state['addons'].items():
                if (not isinstance(aid, str) or not aid or
                        not {'status','enabled','requests'}.issubset(item) or
                        set(item)-{'status','enabled','requests','requested_tools'}
                        or item['status'] not in {'pending', 'approved', 'rejected', 'revoked'}
                        or not isinstance(item['enabled'], bool) or not isinstance(item['requests'], dict)
                        or any(s not in self.servers or not isinstance(r, str) for s, r in item['requests'].items())):
                    raise ValueError('Invalid saved addon approval.')
                declarations = item.get('requested_tools',{})
                if not isinstance(declarations,dict) or any(sid not in item['requests'] for sid in declarations):
                    raise ValueError('Invalid saved tool request owner.')
                for specs in declarations.values():
                    if requested_tool_specs(specs)!=specs:
                        raise ValueError('Invalid saved tool request.')
                self.addons[aid] = copy_value(item)
            for aid, servers in state['grants'].items():
                if aid not in self.addons or self.addons[aid]['status'] != 'approved':
                    raise ValueError('Invalid saved grant owner.')
                for sid, tools in servers.items():
                    if sid not in self.servers or not isinstance(tools, dict):
                        raise ValueError('Invalid saved grant server.')
                    for name, fp in tools.items():
                        tool = self.catalogs.get(sid, {}).get(name)
                        if not tool or fp != fingerprint(tool['inputSchema']):
                            raise ValueError('Invalid saved tool grant.')
                self.grants[aid] = copy_value(servers)

    def export(self):
        with self.lock:
            return copy_value({'version': 1, 'master': self.master, 'servers': self.servers,
                               'addons': self.addons, 'grants': self.grants, 'catalogs': self.catalogs})

    def set_master(self, enabled):
        self.master = bool(enabled)
        self.revision += 1

    def save_server(self, value):
        config = server_config(value)
        sid = config['id']
        old = self.servers.get(sid)
        if old and any(old.get(k) != config[k] for k in ('endpoint', 'auth', 'principal', 'header')):
            self._clear_server_grants(sid)
            self.catalogs.pop(sid, None)
        self.servers[sid] = config
        self.revision += 1
        return sid

    def remove_server(self, sid):
        self.servers.pop(sid, None)
        self.catalogs.pop(sid, None)
        self._clear_server_grants(sid)
        for addon in self.addons.values():
            addon['requests'].pop(sid, None)
            addon.get('requested_tools',{}).pop(sid,None)
        self.revision += 1

    def _clear_server_grants(self, sid):
        for servers in self.grants.values():
            servers.pop(sid, None)

    def catalog(self, sid, tools):
        if sid not in self.servers:
            raise ValueError('Unknown server.')
        catalog = {}
        for tool in tools:
            if (not isinstance(tool, dict) or not isinstance(tool.get('name'), str)
                    or not tool['name'] or tool['name'] in catalog
                    or not isinstance(tool.get('inputSchema'), dict)):
                raise ValueError('Invalid or duplicate tool in catalog.')
            name = tool['name']
            catalog[name] = copy_value({'name': name, 'description': str(tool.get('description') or ''),
                                        'inputSchema': tool['inputSchema']})
        for servers in self.grants.values():
            grants = servers.get(sid, {})
            for name in list(grants):
                if name not in catalog or fingerprint(catalog[name]['inputSchema']) != grants[name]:
                    del grants[name]
        self.catalogs[sid] = catalog
        self.revision += 1

    def request(self, aid, sid, reason, *, requested_tools=None, update_only=False):
        if sid not in self.servers:
            raise ValueError('Unknown server.')
        if not isinstance(update_only,bool):
            raise ValueError('Invalid request update mode.')
        specs = requested_tool_specs(requested_tools) if requested_tools is not None else None
        existing = self.addons.get(aid,{})
        if update_only and (sid not in existing.get('requests',{}) or
                            existing.get('status') not in {'pending','approved'}):
            return self.access(aid,sid)
        item = self.addons.setdefault(aid, {'status': 'pending', 'enabled': False, 'requests': {}})
        if item['status'] in {'rejected', 'revoked'}:
            item['status'] = 'pending'
        item['requests'][sid] = str(reason)[:500]
        if specs is not None:
            item.setdefault('requested_tools',{})[sid] = specs
        self.revision += 1
        return self.access(aid, sid)

    def access(self, aid, sid=''):
        item = self.addons.get(aid, {})
        return {'status': item.get('status', 'not_requested'), 'enabled': item.get('enabled', False),
                'master': self.master, 'server_id': sid, 'requested':sid in item.get('requests',{}),
                'requested_tools':copy_value(item.get('requested_tools',{}).get(sid,[]))}

    def approval(self, aid, action):
        item = self.addons.get(aid)
        if item is None:
            raise ValueError('Addon has not requested access.')
        if action == 'approve' and item['status'] == 'pending':
            item.update(status='approved', enabled=True)
        elif action in {'reject', 'revoke'}:
            item.update(status='rejected' if action == 'reject' else 'revoked', enabled=False)
            self.grants.pop(aid, None)
        elif action in {'enable', 'disable'} and item['status'] == 'approved':
            item['enabled'] = action == 'enable'
        else:
            raise ValueError('Invalid approval transition.')
        self.revision += 1

    def select(self, aid, sid, name, enabled):
        if self.addons.get(aid, {}).get('status') != 'approved' or sid not in self.servers:
            raise ValueError('Approve the addon before selecting tools.')
        tool = self.catalogs.get(sid, {}).get(name)
        if tool is None:
            raise ValueError('Tool is not in the current catalog.')
        grants = self.grants.setdefault(aid, {}).setdefault(sid, {})
        if enabled:
            grants[name] = fingerprint(tool['inputSchema'])
        else:
            grants.pop(name, None)
        self.revision += 1

    def select_all(self, aid, sid, enabled):
        if self.addons.get(aid, {}).get('status') != 'approved' or sid not in self.servers:
            raise ValueError('Approve the addon before selecting tools.')
        if enabled:
            self.grants.setdefault(aid, {})[sid] = {
                name: fingerprint(tool['inputSchema']) for name, tool in self.catalogs.get(sid, {}).items()}
        else:
            self.grants.setdefault(aid, {})[sid] = {}
        self.revision += 1

    def authorized(self, aid, sid, name):
        item = self.addons.get(aid, {})
        tool = self.catalogs.get(sid, {}).get(name)
        return bool(self.master and item.get('status') == 'approved' and item.get('enabled')
                    and sid in self.servers and tool and
                    self.grants.get(aid, {}).get(sid, {}).get(name) == fingerprint(tool['inputSchema']))

    def permitted(self, aid, sid):
        return copy_value([dict(tool, server_id=sid, server_name=self.servers[sid]['name'])
                           for name, tool in self.catalogs.get(sid, {}).items()
                           if self.authorized(aid, sid, name)])
