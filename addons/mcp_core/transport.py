"""Official MCP SDK adapter. All SDK/HTTP types stay behind this boundary."""
from __future__ import annotations

from contextlib import AsyncExitStack
from contextvars import ContextVar
from datetime import timedelta
import importlib.metadata
import json
import logging
import asyncio
import threading

from .contracts import copy_value

_private_transport = ContextVar('nc_mcp_private_transport', default=False)


class _PrivateDiagnostics(logging.Filter):
    def filter(self, record):
        if _private_transport.get():
            record.msg = 'MCP transport diagnostic (remote details suppressed)'
            record.args = ()
            record.exc_info = None
            record.exc_text = None
            record.stack_info = None
        return True


_diagnostics = _PrivateDiagnostics()
_logging_lock = threading.Lock()


def _install_private_diagnostics():
    # Logger filters do not cover lazily imported HTTP backends or root-logger
    # SDK diagnostics. Chain the existing record factory, changing only records
    # created inside this addon's transport ContextVar (including child tasks).
    with _logging_lock:
        previous = logging.getLogRecordFactory()
        if getattr(previous, '_nc_mcp_private', False):
            return
        def make_record(*args, **kwargs):
            record = previous(*args, **kwargs)
            _diagnostics.filter(record)
            return record
        make_record._nc_mcp_private = True
        logging.setLogRecordFactory(make_record)


def sdk_status():
    try:
        version = importlib.metadata.version('mcp')
        if version != '1.26.0':
            return 'MCP Core requires the tested mcp==1.26.0 SDK.'
        import mcp.client.streamable_http  # noqa: F401
        import jsonschema  # noqa: F401
    except (ImportError, importlib.metadata.PackageNotFoundError):
        return 'MCP SDK dependencies are missing. See the addon README.'
    return ''


def redact(value, secrets):
    if isinstance(value, str):
        for secret in secrets:
            if secret:
                value = value.replace(secret, '[redacted]')
        return value
    if isinstance(value, dict):
        return {redact(k, secrets): redact(v, secrets) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v, secrets) for v in value]
    return value


def validate_arguments(schema, arguments):
    """Validate locally; no remote $ref, dynamicRef, vocabulary or schema fetching."""
    import jsonschema
    from referencing import Registry
    def check(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key in {'$ref', '$dynamicRef', '$recursiveRef'} and (
                        not isinstance(item, str) or not item.startswith('#')):
                    raise ValueError('Remote schema references are unsupported.')
                check(item)
        elif isinstance(value, list):
            for item in value:
                check(item)
    try:
        check(schema)
        validator = jsonschema.validators.validator_for(schema)
        validator.check_schema(schema)
        validator(schema, registry=Registry()).validate(arguments)
    except Exception:
        raise ValueError('Arguments or tool schema are invalid or unsupported.') from None


class SdkHttpConnection:
    def __init__(self, endpoint, *, headers=None, secrets=(), timeout=30):
        self.endpoint = endpoint
        self._headers = dict(headers or {})
        self._secrets = tuple(s for s in secrets if s)
        self.timeout = timeout
        self._stack = None
        self._token = None
        self.protocol_failure = False

    async def __aenter__(self):
        status = sdk_status()
        if status:
            raise RuntimeError(status)
        import httpx
        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client
        # Context-local suppression preserves unrelated clients' diagnostics.
        _install_private_diagnostics()
        self._token = _private_transport.set(True)
        self._stack = AsyncExitStack()
        try:
            client = await self._stack.enter_async_context(httpx.AsyncClient(
                headers=self._headers, timeout=httpx.Timeout(self.timeout),
                follow_redirects=False, trust_env=False,
                transport=httpx.AsyncHTTPTransport(retries=0),
            ))
            read, write, _ = await self._stack.enter_async_context(
                streamable_http_client(self.endpoint, http_client=client))
            self._session = await self._stack.enter_async_context(ClientSession(
                read, write, read_timeout_seconds=timedelta(seconds=self.timeout),
                message_handler=self._on_message))
            await self._session.initialize()
            return self
        except BaseException:
            await self.__aexit__(None, None, None)
            raise

    async def __aexit__(self, *args):
        try:
            if self._stack is not None:
                await self._stack.aclose()
        finally:
            self._stack = None
            if self._token is not None:
                _private_transport.reset(self._token)
                self._token = None

    async def catalog(self):
        tools = []
        cursor = None
        seen = set()
        for _ in range(100):
            page = await self._session.list_tools(cursor=cursor)
            tools.extend(t.model_dump(mode='json', exclude_none=True) for t in page.tools)
            if len(tools) > 2000:
                raise ValueError('Tool catalog exceeds limit.')
            cursor = page.nextCursor
            if not cursor:
                return self._safe(tools)
            if cursor in seen:
                raise ValueError('Repeated catalog cursor.')
            seen.add(cursor)
        raise ValueError('Tool catalog pagination exceeds limit.')

    async def probe(self):
        """Check the established session with one read-only MCP tools/list request."""
        page = await self._session.list_tools()
        self._safe(page.model_dump(mode='json', exclude_none=True))

    async def invoke(self, name, arguments):
        from mcp import types
        try:
            # The convenience call_tool validates remote output schemas and may
            # fetch their $refs. Use the SDK's public request API to preserve the
            # tool result without implicit discovery or external schema retrieval.
            value = await self._session.send_request(
                types.ClientRequest(types.CallToolRequest(
                    params=types.CallToolRequestParams(name=name, arguments=arguments))),
                types.CallToolResult,
                request_read_timeout_seconds=timedelta(seconds=self.timeout))
        except (Exception, asyncio.CancelledError):
            if self.protocol_failure:
                raise ValueError('Invalid MCP protocol response.') from None
            raise
        return self._safe(value.model_dump(mode='json', exclude_none=True))

    async def _on_message(self, message):
        if isinstance(message, Exception):
            self.protocol_failure = True

    def _safe(self, value):
        value = copy_value(value)
        if len(json.dumps(value).encode()) > 2_000_000:
            raise ValueError('MCP response exceeds limit.')
        return redact(value, self._secrets)
