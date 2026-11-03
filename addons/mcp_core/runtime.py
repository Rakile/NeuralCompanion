"""Supervised loop and per-server actors. No connections or credentials on the UI thread."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import json
import threading
import time
from uuid import uuid4

from .contracts import copy_value, result
from .policy import fingerprint
from .transport import SdkHttpConnection, sdk_status, validate_arguments


def _consumer_current(guard):
    """A local consumer may narrow authority; it can never grant authority."""
    try:
        return guard is None or (callable(guard) and bool(guard()))
    except Exception:
        return False


@dataclass
class _Job:
    binding: object
    sid: str
    name: str
    arguments: dict
    config: dict
    schema: str
    is_current: object = None
    outcome: dict = field(default_factory=lambda: result('queued'))
    task: object = None
    updated: float = field(default_factory=time.monotonic)


def _failure_status(error, *, sent=False):
    if isinstance(error, BaseExceptionGroup):
        return _failure_status(error.exceptions[0], sent=sent)
    import httpx
    from mcp.shared.exceptions import McpError
    if isinstance(error, McpError) and error.error.code in {408, -32000, -32001}:
        return 'unconfirmed' if sent else 'unavailable'
    if isinstance(error, (ValueError, McpError)):
        return 'protocol'
    if isinstance(error, httpx.HTTPStatusError):
        return 'protocol'
    return 'unconfirmed' if sent else 'unavailable'


class McpRuntime:
    def __init__(self, tasks, policy, *, persist, credential_getter,
                 configure=None, initialize=None, tool_timeout=30, connect_timeout=10):
        self.tasks = tasks
        self.policy = policy
        self.persist = persist
        self.credential_getter = credential_getter
        self.configure = configure
        self.initialize = initialize
        self.tool_timeout = max(.05, min(120, float(tool_timeout)))
        self.connect_timeout = max(.05, min(30, float(connect_timeout)))
        self.probe_timeout = 2.0
        self.max_calls = 32
        self.jobs = {}
        self.connections = {}
        self._actors = {}
        self._queues = {}
        self._disconnecting = set()
        self._probe_tasks = set()
        self._pending_management = 0
        self.management_status = 'ok'
        self.dependency_status = 'Checking MCP SDK dependencies…'
        self.closed = False
        self._ready = threading.Event()
        self._snapshot_cache = dict(policy.export(), closed=False, busy=True,
            management_status='ok', dependency_status=self.dependency_status, connections={})
        self._worker = tasks.spawn('mcp-http-loop', self._run, on_cancel=lambda reason: self.begin_shutdown())
        tasks.register_resource('mcp-http-runtime', self)

    def _run(self, token):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        try:
            self.loop.run_until_complete(self._main(token))
        finally:
            self.loop.run_until_complete(self.loop.shutdown_asyncgens())
            self.loop.close()

    async def _main(self, token):
        self._management_lock = asyncio.Lock()
        self._management_tasks = set()
        self.dependency_status = sdk_status()
        if self.initialize is not None:
            try:
                self.initialize()
            except Exception:
                self.management_status = 'Secure credential storage could not be read.'
        self._ready.set()
        try:
            while not self.closed and not token.cancelled:
                with self.policy.lock:
                    self._invalidate()
                    finished = [cid for cid, job in self.jobs.items()
                                if job.outcome['status'] not in {'queued', 'running'}]
                    for cid in finished[:-128]:
                        del self.jobs[cid]
                await asyncio.sleep(.025)
        finally:
            with self.policy.lock:
                self.closed = True
                for job in self.jobs.values():
                    self._cancel_job(job, 'cancelled')
            for task in list(self._probe_tasks):
                task.cancel()
            if self._probe_tasks:
                await asyncio.gather(*self._probe_tasks, return_exceptions=True)
            for task in list(self._management_tasks):
                task.cancel()
            if self._management_tasks:
                await asyncio.gather(*self._management_tasks, return_exceptions=True)
            await self._disconnect_all()

    def snapshot(self):
        # Vault transactions and atomic file writes may own the policy lock.
        # UI reads use the last detached projection instead of waiting for IO.
        if not self.policy.lock.acquire(blocking=False):
            return dict(copy_value(self._snapshot_cache), busy=True, closed=self.closed)
        try:
            state = self.policy.export()
            state.update(closed=self.closed, busy=bool(self._pending_management) or not self._ready.is_set(),
                         management_status=self.management_status, dependency_status=self.dependency_status,
                         connections=copy_value(self.connections))
            self._snapshot_cache = copy_value(state)
            return state
        finally:
            self.policy.lock.release()

    def manage(self, payload):
        try:
            payload = copy_value(payload)
            if not isinstance(payload, dict) or len(json.dumps(payload)) > 128_000:
                raise ValueError()
        except (TypeError, ValueError, RecursionError):
            return result('invalid_configuration')
        if not self.policy.lock.acquire(blocking=False):
            return result('busy')
        try:
            if self.closed:
                return result('unavailable')
            if self._pending_management >= 32:
                return result('busy')
            if not self._ready.is_set():
                return result('busy')
            self._pending_management += 1
            try:
                self.loop.call_soon_threadsafe(self._schedule_management, payload)
            except RuntimeError:
                self._pending_management -= 1
                return result('unavailable')
        finally:
            self.policy.lock.release()
        return result('accepted')

    def _schedule_management(self, payload):
        if self.closed:
            with self.policy.lock:
                self._pending_management -= 1
            return
        task = self.loop.create_task(self._manage(payload))
        self._management_tasks.add(task)
        task.add_done_callback(self._management_tasks.discard)

    async def _manage(self, payload):
        try:
            async with self._management_lock:
                action = payload.get('action')
                sid = str(payload.get('server_id') or '')
                with self.policy.lock:
                    if self.closed:
                        return
                    if action == 'master':
                        self.policy.set_master(payload.get('enabled', False))
                    elif action == 'approval':
                        self.policy.approval(str(payload.get('addon_id') or ''), payload.get('decision'))
                    elif action == 'select':
                        self.policy.select(str(payload.get('addon_id') or ''), sid,
                                           str(payload.get('tool') or ''), bool(payload.get('enabled')))
                    elif action == 'select_all':
                        self.policy.select_all(str(payload.get('addon_id') or ''), sid, bool(payload.get('enabled')))
                    elif action in {'save_server', 'remove_server'}:
                        if self.configure is None:
                            raise ValueError('Configuration unavailable.')
                        sid = self.configure(payload)
                    elif action not in {'connect', 'disconnect', 'test', 'refresh', 'clear_status', 'persist'}:
                        raise ValueError('Unknown management action.')
                    self._invalidate()
                    self.persist()
                if action == 'master' and not self.policy.master:
                    await self._disconnect_all()
                elif action in {'save_server', 'remove_server', 'disconnect'}:
                    await self._disconnect(sid)
                elif action in {'connect', 'test'}:
                    self._connect(sid, test_only=action == 'test')
                elif action == 'refresh':
                    if sid not in self._queues:
                        raise ValueError('Connect before refreshing tools.')
                    self._queues[sid].put_nowait(('refresh', None))
                elif action == 'clear_status':
                    for item in self.connections.values():
                        item['error'] = ''
                with self.policy.lock:
                    self.management_status = 'ok'
        except asyncio.CancelledError:
            raise
        except ValueError as error:
            with self.policy.lock:
                self.management_status = str(error)[:300]
        except Exception:
            # Never relay exceptions: HTTP, vault and SDK failures may contain secrets.
            with self.policy.lock:
                self.management_status = 'Management operation failed; check configuration and secure storage.'
        finally:
            # The off switch takes effect even if saving choices fails. Close
            # connections concurrently so the cleanup bound is per batch.
            if not self.policy.master:
                await self._disconnect_all()
            with self.policy.lock:
                self._pending_management -= 1

    def _connect(self, sid, test_only=False):
        with self.policy.lock:
            if self.closed or not self.policy.master or sid not in self.policy.servers or self.dependency_status:
                raise ValueError('MCP access or dependency unavailable.')
            if sid in self._actors:
                raise ValueError('Connection already open or connecting.')
            if len(self._actors) >= 8:
                raise ValueError('Connection limit reached.')
            self.connections[sid] = {'status': 'connecting', 'error': '', 'tested': False}
            queue = asyncio.Queue(maxsize=64)
            self._queues[sid] = queue
            self._actors[sid] = self.loop.create_task(self._serve(sid, queue, test_only))

    async def _serve(self, sid, queue, test_only):
        connection = None
        try:
            with self.policy.lock:
                config = copy_value(self.policy.servers[sid])
            secret = self.credential_getter(sid) if config['auth'] != 'none' else None
            if config['auth'] != 'none' and not secret:
                raise ValueError('Secure credential missing.')
            headers = ({'Authorization': 'Bearer ' + secret} if config['auth'] == 'bearer' else
                       {config['header']: secret} if config['auth'] == 'api_key' else {})
            connection = SdkHttpConnection(config['endpoint'], headers=headers,
                                            secrets=[secret], timeout=max(self.connect_timeout, self.tool_timeout) + 1)
            async with asyncio.timeout(self.connect_timeout):
                await connection.__aenter__()
                tools = await connection.catalog()
            with self.policy.lock:
                self.policy.catalog(sid, tools)
                self._invalidate()
                self.persist()
                self.connections[sid] = {'status': 'connected', 'error': '', 'tested': test_only}
            if test_only:
                return
            while True:
                kind, value = await queue.get()
                if kind == 'refresh':
                    tools = await asyncio.wait_for(connection.catalog(), self.connect_timeout)
                    with self.policy.lock:
                        self.policy.catalog(sid, tools)
                        self._invalidate()
                        self.persist()
                elif kind == 'probe':
                    if value.done():
                        continue
                    try:
                        await asyncio.wait_for(connection.probe(), self.probe_timeout)
                        healthy = True
                    except Exception:
                        healthy = False
                    if not value.done():
                        value.set_result(healthy)
                else:
                    job = self.jobs.get(value)
                    if job is None or job.outcome['status'] != 'queued':
                        continue
                    job.task = self.loop.create_task(self._execute(connection, job))
                    await asyncio.gather(job.task, return_exceptions=True)
        except asyncio.CancelledError:
            if not self.closed and sid not in self._disconnecting:
                with self.policy.lock:
                    self.connections[sid] = {'status': 'error', 'error': 'unavailable', 'tested': False}
        except Exception as error:
            with self.policy.lock:
                self.connections[sid] = {'status': 'error', 'error': _failure_status(error), 'tested': False}
        finally:
            if connection is not None:
                try:
                    async with asyncio.timeout(2):
                        await connection.__aexit__(None, None, None)
                except BaseException:
                    pass
            with self.policy.lock:
                for job in self.jobs.values():
                    if job.sid == sid:
                        self._cancel_job(job, 'unavailable')
                if self.connections.get(sid, {}).get('status') != 'error':
                    self.connections[sid] = {'status': 'disconnected', 'error': '', 'tested': test_only}
                self._actors.pop(sid, None)
                self._queues.pop(sid, None)

    async def _disconnect_all(self):
        await asyncio.gather(*(self._disconnect(sid) for sid in tuple(self._actors)),
                             return_exceptions=True)

    async def _disconnect(self, sid):
        with self.policy.lock:
            for job in self.jobs.values():
                if job.sid == sid:
                    self._cancel_job(job, 'unavailable')
            task = self._actors.get(sid)
        if task is not None:
            self._disconnecting.add(sid)
            try:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            finally:
                self._disconnecting.discard(sid)

    def probe_servers(self, binding, server_ids):
        """Bounded read-only checks on existing sessions, never a tool invocation."""
        if (not isinstance(server_ids, list) or len(server_ids) > 32 or
                any(not isinstance(sid, str) or not sid or len(sid) > 512 for sid in server_ids)):
            return result('invalid_arguments')
        with self.policy.lock:
            if self.closed or binding.closed:
                return result('denied')
            if not self._ready.is_set() or threading.current_thread() is self._worker.thread:
                return result('unavailable')
        coroutine = self._probe_servers(binding, list(dict.fromkeys(server_ids)))
        try:
            future = asyncio.run_coroutine_threadsafe(coroutine, self.loop)
        except RuntimeError:
            coroutine.close()
            return result('unavailable')
        try:
            return result('ok', future.result(timeout=self.probe_timeout + .75))
        except Exception:
            future.cancel()
            return result('unavailable')

    async def _probe_servers(self, binding, server_ids):
        if len(self._probe_tasks) >= 32:
            return []
        task = asyncio.current_task()
        self._probe_tasks.add(task)
        try:
            return await self._run_probe_batch(binding, server_ids)
        finally:
            self._probe_tasks.discard(task)

    async def _run_probe_batch(self, binding, server_ids):
        pending = {}
        with self.policy.lock:
            if self.closed or binding.closed:
                return []
            aid = binding.owner.addon_id
            for sid in server_ids:
                queue = self._queues.get(sid)
                actor = self._actors.get(sid)
                if (sid not in self.policy.servers or queue is None or actor is None or actor.done()
                        or self.connections.get(sid, {}).get('status') != 'connected'
                        or not self.policy.permitted(aid, sid)):
                    continue
                future = self.loop.create_future()
                try:
                    queue.put_nowait(('probe', future))
                except asyncio.QueueFull:
                    continue
                pending[sid] = (future, queue, actor)
        if not pending:
            return []
        try:
            done, _ = await asyncio.wait([item[0] for item in pending.values()], timeout=self.probe_timeout)
        finally:
            for future, _, _ in pending.values():
                if not future.done():
                    future.cancel()
        with self.policy.lock:
            if self.closed or binding.closed:
                return []
            return [sid for sid, (future, queue, actor) in pending.items()
                    if future in done and not future.cancelled() and future.result() is True
                    and self._queues.get(sid) is queue and self._actors.get(sid) is actor
                    and not actor.done() and self.connections.get(sid, {}).get('status') == 'connected'
                    and self.policy.permitted(aid, sid)]

    def _authorized(self, job):
        current = self.policy.servers.get(job.sid, {})
        tool = self.policy.catalogs.get(job.sid, {}).get(job.name)
        return (not self.closed and not job.binding.closed and _consumer_current(job.is_current) and
                self.policy.authorized(job.binding.owner.addon_id, job.sid, job.name) and tool and
                fingerprint(tool['inputSchema']) == job.schema and
                all(current.get(k) == job.config.get(k) for k in ('endpoint', 'auth', 'principal', 'header')))

    def _invalidate(self):
        for job in self.jobs.values():
            if job.outcome['status'] in {'queued', 'running'} and not self._authorized(job):
                self._cancel_job(job, 'denied')

    def _cancel_job(self, job, queued_status):
        status = job.outcome['status']
        if status not in {'queued', 'running'}:
            return
        job.outcome = result('cancelled' if status == 'running' else queued_status,
                             {'completion_confirmed': False})
        job.updated = time.monotonic()
        if job.task is not None:
            self.loop.call_soon_threadsafe(job.task.cancel)

    async def _execute(self, connection, job):
        with self.policy.lock:
            # Final acceptance check occurs in the dispatch task, before its first IO.
            if job.outcome['status'] != 'queued' or not self._authorized(job):
                self._cancel_job(job, 'denied')
                return
            job.outcome = result('running')
        try:
            async with asyncio.timeout(self.tool_timeout):
                value = await connection.invoke(job.name, job.arguments)
            outcome = result('tool_error' if value.get('isError') else 'ok',
                             {'result': value, 'completion_confirmed': True})
        except asyncio.CancelledError:
            # Explicit cancellation already set the job's result. An unsolicited
            # SDK task-group cancellation means the HTTP outcome is uncertain.
            outcome = result('unconfirmed', {'completion_confirmed': False})
        except Exception as error:
            outcome = result(_failure_status(error, sent=True), {'completion_confirmed': False})
        with self.policy.lock:
            if job.outcome['status'] == 'running':
                job.outcome = outcome
            job.updated = time.monotonic()

    def submit(self, binding, sid, name, arguments, *, is_current=None, expected_schema_fingerprint=None):
        with self.policy.lock:
            aid = binding.owner.addon_id
            if (self.closed or binding.closed or not _consumer_current(is_current)
                    or not self.policy.authorized(aid, sid, name)):
                return result('denied')
            if self.connections.get(sid, {}).get('status') != 'connected':
                return result('unavailable')
            if sum(j.outcome['status'] in {'queued', 'running'} for j in self.jobs.values()) >= self.max_calls:
                return result('busy')
            try:
                arguments = copy_value(arguments)
                if not isinstance(arguments, dict) or len(json.dumps(arguments)) > 128_000:
                    raise ValueError()
                schema = self.policy.catalogs[sid][name]['inputSchema']
                if expected_schema_fingerprint is not None and fingerprint(schema)!=expected_schema_fingerprint:
                    return result('denied')
                validate_arguments(schema, arguments)
            except (ValueError, TypeError, RecursionError):
                return result('invalid_arguments')
            cid = uuid4().hex
            self.jobs[cid] = _Job(binding, sid, name, arguments,
                                  copy_value(self.policy.servers[sid]), fingerprint(schema), is_current)
            self.loop.call_soon_threadsafe(self._enqueue, sid, cid)
            return result('queued', {'call_id': cid})

    def _enqueue(self, sid, cid):
        queue = self._queues.get(sid)
        if queue is None or queue.full():
            with self.policy.lock:
                self._cancel_job(self.jobs[cid], 'unavailable')
        else:
            queue.put_nowait(('call', cid))

    def call_status(self, binding, cid):
        with self.policy.lock:
            job = self.jobs.get(cid)
            if (self.closed or binding.closed or job is None or job.binding.owner != binding.owner):
                return result('denied')
            return copy_value(job.outcome)

    def cancel_call(self, binding, cid):
        with self.policy.lock:
            job = self.jobs.get(cid)
            if self.closed or binding.closed or job is None or job.binding.owner != binding.owner:
                return result('denied')
            self._cancel_job(job, 'cancelled')
            return result('ok', {'completion_confirmed': False})

    def begin_shutdown(self):
        with self.policy.lock:
            self.closed = True

    def close(self):
        self.begin_shutdown()
        if threading.current_thread() is not self._worker.thread:
            self.tasks.join_worker(self._worker)
