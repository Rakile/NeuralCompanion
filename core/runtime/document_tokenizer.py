"""Cancellable local token counting, isolated from chat and SDK global state."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time
from urllib.parse import urlsplit


@contextmanager
def loaded_model_counter(spec):
    """Runs only inside the hidden helper; never loads or substitutes a model."""
    import lmstudio
    parsed = urlsplit(spec['base_url'])
    if parsed.scheme != 'http':
        raise ValueError('LM Studio token counting requires a local HTTP server.')
    lmstudio.set_sync_api_timeout(5)  # Child process only; does not affect NC clients.
    with lmstudio.Client(parsed.netloc) as client:
        model = None
        for handle in client.embedding.list_loaded():
            info = handle.get_info()
            key = info.get('modelKey') or info.get('model_key') if isinstance(info,dict) else getattr(info,'model_key','')
            if str(key) == spec['model']:
                model = handle
                break
        if model is None:
            raise RuntimeError(f'Embedding model “{spec["model"]}” is no longer loaded. Retry indexing when it is available.')
        if model.get_context_length() != spec['context_tokens']:
            raise ValueError('Loaded embedding model context changed; retry with matching package settings.')
        yield model.count_tokens


def _respond(value, response_path=None):
    if response_path is None:
        print(json.dumps(value, ensure_ascii=False), flush=True)
        return
    # A running pre-upgrade parent still supplies a response-file argument.
    path = response_path if value['id'] == 0 else response_path.with_name(f'response-{value["id"]}.json')
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value,ensure_ascii=False),encoding='utf-8')
    os.replace(temporary,path)


def worker_main(response_path=None):
    request_id = 0
    try:
        spec = json.loads(sys.stdin.readline())
        with loaded_model_counter(spec) as count:
            _respond({'ok':True,'id':0}, response_path)
            for line in sys.stdin:
                request = json.loads(line)
                request_id = request['id']
                _respond({'ok':True,'id':request_id,'count':count(request['text'])}, response_path)
    except Exception as exc:
        _respond({'ok':False,'id':request_id,'error':str(exc)[:1000]}, response_path)
        return 1
    return 0


@contextmanager
def token_counter_process(spec, *, cancelled, register_process=None):
    process = subprocess.Popen([sys.executable,'-B','-X','utf8',str(Path(__file__).resolve())],
        stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,
        text=True,encoding='utf-8',creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    responses = queue.Queue()
    reader = None
    def read_responses():
        try:
            for line in process.stdout:
                responses.put(json.loads(line))
        except Exception as exc:
            responses.put(exc)
        finally:
            responses.put(None)
    try:
        if register_process is not None:register_process('document-tokenizer',process)
        reader = threading.Thread(target=read_responses, name='document-tokenizer-responses', daemon=True)
        reader.start()
        process.stdin.write(json.dumps({'base_url':spec.base_url,'model':spec.model,'context_tokens':int(spec.context_tokens)})+'\n')
        process.stdin.flush()
        def wait(expected):
            deadline = time.monotonic()+10
            while True:
                if cancelled():raise InterruptedError('Document token counting paused for activity.')
                remaining = deadline-time.monotonic()
                if remaining <= 0:raise TimeoutError('Local document tokenizer did not respond within 10 seconds.')
                try:
                    value = responses.get(timeout=min(.025, remaining))
                except queue.Empty:
                    continue
                if value is None:raise RuntimeError('Document tokenizer stopped before returning a result.')
                if isinstance(value, Exception):raise RuntimeError('Invalid document tokenizer response.') from value
                if not isinstance(value, dict) or value.get('id') != expected:
                    raise RuntimeError('Unexpected document tokenizer response.')
                if not value.get('ok'):raise RuntimeError('Document token counting failed: '+str(value.get('error','')))
                return value
        wait(0)
        request_id = 0
        def count(text):
            nonlocal request_id
            if cancelled():raise InterruptedError('Document token counting paused for activity.')
            request_id += 1
            process.stdin.write(json.dumps({'id':request_id,'text':text},ensure_ascii=False)+'\n')
            process.stdin.flush()
            value = wait(request_id)['count']
            if type(value) is not int or value < 0:raise ValueError('Invalid model token count.')
            return value
        yield count
    finally:
        if process.poll() is None:
            process.terminate()
            try:process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill();process.wait(timeout=2)
        if process.stdin is not None:
            try:process.stdin.close()
            except OSError:pass
        if reader is not None:reader.join(timeout=1)
        if process.stdout is not None:process.stdout.close()


if __name__ == '__main__':
    # Legacy launchers predate the explicit Python UTF-8 flag.
    sys.stdin.reconfigure(encoding='utf-8')
    raise SystemExit(worker_main(Path(sys.argv[1]) if len(sys.argv) > 1 else None))
