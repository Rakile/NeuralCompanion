"""Bounded Desktop discovery and conversion; snapshots perform no file I/O."""
from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor
import copy
import os
from pathlib import Path
import re
import threading
from urllib.parse import urlsplit, unquote
from uuid import uuid4
from .media import MAX_BYTES, file_hash
from .models import metadata

EXTENSIONS = {'.wav', '.flac', '.mp3', '.m4a', '.aac', '.ogg', '.opus'}
MAX_SELECTION, MAX_ENTRIES = 100, 10000
REVIEW_PAGE_SIZE = 100


def local_file(value: str) -> Path:
    if not isinstance(value, str) or not value or len(value) > 4096:
        raise ValueError('Choose a local audio file.')
    if value.startswith('file:'):
        parsed = urlsplit(value)
        if parsed.netloc or parsed.query or parsed.fragment:
            raise ValueError('Choose a local audio file.')
        value = unquote(parsed.path)
        if len(value) > 2 and value[0] == '/' and value[2] == ':': value = value[1:]
    if value.startswith(('\\\\', '//')) or '://' in value:
        raise ValueError('Choose a local audio file.')
    return Path(value).absolute()


def suggested_tags(name: str) -> list[str]:
    words = re.findall(r'[^\W\d_]+', name.casefold(), flags=re.UNICODE)
    ignored = {'wav', 'mp3', 'flac', 'ogg', 'opus', 'm4a', 'aac', 'audio', 'ambience', 'sfx'}
    return list(dict.fromkeys(w[:32] for w in words if len(w) > 2 and w not in ignored))[:20]


def _linked(path: Path) -> bool:
    return path.is_symlink() or bool(getattr(path.lstat(), 'st_file_attributes', 0) & 0x400)


def _regular(path: Path) -> None:
    if any(_linked(parent) for parent in (path, *path.parents)):
        raise ValueError('Directory links and linked audio files are skipped.')
    if path.suffix.lower() not in EXTENSIONS or not path.is_file() or not 0 < path.stat().st_size <= MAX_BYTES:
        raise ValueError('Choose regular audio files up to 100 MB each.')


def _directory(path: Path) -> None:
    if any(_linked(parent) for parent in (path, *path.parents)) or not path.is_dir():
        raise ValueError('Choose a regular local folder without directory links.')


class DesktopSoundImports:
    def __init__(self, library, *, executor=None):
        self.library = library
        self._lock = threading.Lock()
        self._closed = False
        self._cancel = threading.Event()
        self._paths: dict[str, Path] = {}
        self._entries: list[dict] = []
        self._entry_by_id: dict[str, dict] = {}
        self._results: dict[str, dict] = {}
        self._page = 0
        self._folders: list[dict] = []
        self._folder_paths: set[str] = set()
        self._folder_page = 0
        self._status = {'busy': False, 'phase': 'idle', 'scan_id': '', 'entries': [], 'results': [],
                        'discovered_count': 0, 'incomplete': False, 'scan_limited': False,
                        'from_folder': False, 'preview_url': '', 'preview_token': '',
                        'message': 'Import your ambience, music and effects.'}
        self._executor = executor or ThreadPoolExecutor(max_workers=1, thread_name_prefix='nc-desktop-sounds')

    def snapshot(self) -> dict:
        with self._lock:
            result = copy.deepcopy(self._status)
            start = self._page * REVIEW_PAGE_SIZE
            page = self._entries[start:start + REVIEW_PAGE_SIZE]
            result['page'] = self._page
            result['page_count'] = max(1, (len(self._entries) + REVIEW_PAGE_SIZE - 1) // REVIEW_PAGE_SIZE)
            result['entries'] = copy.deepcopy(page)
            result['results'] = copy.deepcopy([self._results[entry['id']] for entry in page
                                                if entry['id'] in self._results])
            folder_start = self._folder_page * REVIEW_PAGE_SIZE
            result['folder_page'] = self._folder_page
            result['folder_count'] = len(self._folders)
            result['folder_page_count'] = max(1, (len(self._folders) + REVIEW_PAGE_SIZE - 1) // REVIEW_PAGE_SIZE)
            result['folders'] = copy.deepcopy(self._folders[folder_start:folder_start + REVIEW_PAGE_SIZE])
            return result

    def _publish(self, scan_id: str, **values) -> None:
        with self._lock:
            if self._status['scan_id'] == scan_id and not self._cancel.is_set() and not self._closed:
                self._status.update(values)

    def start(self, request: dict) -> None:
        operation = request.get('operation', 'scan')
        if operation == 'confirm': self.confirm(request.get('scan_id'), request.get('selections'))
        elif operation == 'confirm_all': self.confirm_all(request.get('scan_id'), request.get('folder_overrides'))
        elif operation == 'page': self.page(request.get('scan_id'), request.get('page'))
        elif operation == 'folder_page': self.folder_page(request.get('scan_id'), request.get('page'))
        elif operation == 'cancel': self.cancel(request.get('scan_id'))
        elif operation == 'preview': self.preview(request.get('scan_id'), request.get('entry_id'))
        elif operation == 'scan': self.scan(request)
        else: raise ValueError('Unknown sound import operation.')

    def scan(self, request: dict) -> None:
        kind = request.get('kind')
        if kind not in ('ambience', 'music', 'effect'): raise ValueError('Choose a sound type.')
        paths, folder = request.get('paths', []), request.get('folder')
        if not isinstance(paths, list) or len(paths) > MAX_SELECTION or (not paths and not folder):
            raise ValueError('Choose up to 100 sounds or a folder.')
        recursive = request.get('recursive', True)
        if type(recursive) is not bool: raise ValueError('Choose whether to include subfolders.')
        captured = [local_file(p) for p in paths]
        directory = local_file(folder) if folder else None
        with self._lock:
            if self._closed or self._status['busy']: raise ValueError('Cancel or wait for the current sound operation.')
            self._cancel.set()
            self._cancel = cancel = threading.Event()
            scan_id = uuid4().hex
            self._paths = {}
            self._entries = []
            self._entry_by_id = {}
            self._results = {}
            self._page = 0
            self._folders = []
            self._folder_paths = set()
            self._folder_page = 0
            self._status.update(busy=True, phase='scanning', scan_id=scan_id, entries=[], results=[],
                                discovered_count=0, incomplete=False, scan_limited=False,
                                from_folder=directory is not None, preview_url='', message='Finding audio files…')
        self._executor.submit(self._scan, scan_id, cancel, captured, directory, kind, recursive)

    def _scan(self, scan_id, cancel, paths, directory, kind, recursive):
        entries, private, warnings = [], {}, []
        scan_limited = False
        try:
            if directory:
                _directory(directory)
                stack, visited = [directory], 0
                while stack and not cancel.is_set():
                    current = stack.pop()
                    try:
                        _directory(current)
                        with os.scandir(current) as listing:
                            for item in listing:
                                if cancel.is_set(): return
                                visited += 1
                                if visited > MAX_ENTRIES:
                                    scan_limited = True
                                    warnings.append('Scan limited to 10,000 entries. Choose a smaller folder to see the rest.')
                                    stack.clear(); break
                                path = Path(item.path)
                                if _linked(path): warnings.append('Skipped a linked file or folder.')
                                elif item.is_dir(follow_symlinks=False) and recursive: stack.append(path)
                                elif item.is_file(follow_symlinks=False) and path.suffix.lower() in EXTENSIONS: paths.append(path)
                    except (ValueError, OSError): warnings.append('Some linked or unreadable folders were skipped.')
                    if visited > MAX_ENTRIES: break
            for path in dict.fromkeys(paths):
                if cancel.is_set(): return
                try:
                    _regular(path)
                    relative = str(path.relative_to(directory)) if directory else path.name
                    folder = Path(relative).parent.as_posix()
                    if folder == '.': folder = ''
                    key = uuid4().hex; private[key] = path
                    entries.append({'id': key, 'relative_name': relative, 'folder': folder,
                                    'metadata': metadata({'title': path.stem[:120], 'kind': kind,
                                     'category': path.parent.name[:64] or 'Uncategorized',
                                     'tags': suggested_tags(str(Path(relative).with_suffix(''))), 'loop': kind != 'effect'})})
                except (ValueError, OSError): warnings.append('Skipped an invalid, unreadable or oversized audio file.')
            folder_counts: dict[str, list[int]] = {}
            if directory:
                for entry in entries:
                    folder = entry['folder']
                    if not folder: continue
                    parts = folder.split('/')
                    for depth in range(len(parts)):
                        node = '/'.join(parts[:depth + 1])
                        counts = folder_counts.setdefault(node, [0, 0])
                        counts[1] += 1
                        if depth == len(parts) - 1: counts[0] += 1
            folders = [{'path': path, 'name': path.rsplit('/', 1)[-1], 'depth': path.count('/'),
                        'direct_count': counts[0], 'total_count': counts[1]}
                       for path, counts in sorted(folder_counts.items(), key=lambda item: item[0].casefold())]
            message = f'Found {len(entries)} sound(s). Select up to 100, or import all.'
            if warnings: message += ' ' + ' '.join(dict.fromkeys(warnings))
            with self._lock:
                if self._status['scan_id'] == scan_id and not cancel.is_set() and not self._closed:
                    self._paths = private
                    self._entries = entries
                    self._entry_by_id = {entry['id']: entry for entry in entries}
                    self._folders = folders
                    self._folder_paths = set(folder_counts)
                    self._status.update(busy=False, phase='review', discovered_count=len(entries),
                                        incomplete=bool(warnings), scan_limited=scan_limited, message=message)
        except (ValueError, OSError) as error: self._publish(scan_id, busy=False, phase='failed', message=str(error))

    def page(self, scan_id: str, page: int) -> None:
        with self._lock:
            count = max(1, (len(self._entries) + REVIEW_PAGE_SIZE - 1) // REVIEW_PAGE_SIZE)
            if (scan_id != self._status['scan_id'] or self._status['busy']
                    or self._status['phase'] not in ('review', 'finished')
                    or type(page) is not int or not 0 <= page < count):
                raise ValueError('This sound page is unavailable. Scan the folder again.')
            self._page = page

    def folder_page(self, scan_id: str, page: int) -> None:
        with self._lock:
            count = max(1, (len(self._folders) + REVIEW_PAGE_SIZE - 1) // REVIEW_PAGE_SIZE)
            if (scan_id != self._status['scan_id'] or self._status['busy']
                    or self._status['phase'] not in ('review', 'finished')
                    or type(page) is not int or not 0 <= page < count):
                raise ValueError('This folder page is unavailable. Scan the folder again.')
            self._folder_page = page

    def _selection(self, scan_id, key):
        if self._closed or self._cancel.is_set() or scan_id != self._status['scan_id'] or key not in self._paths:
            raise ValueError('This selection expired. Scan the folder again.')
        return self._paths[key]

    def confirm(self, scan_id: str, selections: list[dict]) -> None:
        if not isinstance(selections, list) or not 1 <= len(selections) <= MAX_SELECTION:
            raise ValueError('Select between 1 and 100 sounds.')
        with self._lock:
            if self._status['busy'] or self._status['phase'] != 'review': raise ValueError('Wait for the scan to finish.')
            selected, seen = [], set()
            for item in selections:
                if not isinstance(item, dict) or set(item) - {'id', 'metadata'} or item.get('id') in seen:
                    raise ValueError('Invalid or duplicate sound selection.')
                key = item.get('id'); path = self._selection(scan_id, key)
                original = self._entry_by_id[key]['metadata']
                selected.append((key, path, metadata(item.get('metadata', original)))); seen.add(key)
            self._status.update(busy=True, phase='importing', preview_url='', results=[], message='Importing sounds…')
            cancel = self._cancel
        self._executor.submit(self._run, scan_id, cancel, selected)

    def confirm_all(self, scan_id: str, folder_overrides: dict[str, bool] | None = None) -> None:
        with self._lock:
            if (scan_id != self._status['scan_id'] or self._cancel.is_set()
                    or self._status['busy'] or self._status['phase'] != 'review'
                    or not self._entries or self._status['scan_limited']):
                raise ValueError('The folder scan is incomplete. Choose a smaller folder or rescan.')
            overrides = {} if folder_overrides is None else folder_overrides
            if (not isinstance(overrides, dict) or len(overrides) > len(self._folder_paths) + 1
                    or any(not isinstance(path, str) or (path and path not in self._folder_paths)
                           or type(included) is not bool for path, included in overrides.items())):
                raise ValueError('Choose valid folders to include or exclude.')
            def included(folder: str) -> bool:
                choice = overrides.get('', True)
                parent = ''
                for part in folder.split('/') if folder else ():
                    parent = part if not parent else parent + '/' + part
                    choice = overrides.get(parent, choice)
                return choice
            selected = [(entry['id'], self._paths[entry['id']], entry['metadata'])
                        for entry in self._entries if included(entry['folder'])]
            if not selected: raise ValueError('Include at least one folder with sounds to import.')
            self._results = {}
            self._status.update(busy=True, phase='importing', preview_url='', message='Importing sounds…')
            cancel = self._cancel
        self._executor.submit(self._run, scan_id, cancel, selected)

    def preview(self, scan_id: str, entry_id: str) -> None:
        with self._lock:
            if self._status['busy']: raise ValueError('Wait for the current sound operation.')
            path = self._selection(scan_id, entry_id); cancel = self._cancel
        def prepare():
            try:
                _regular(path)
                if not cancel.is_set(): self._publish(scan_id, preview_url=path.as_uri(), preview_token=uuid4().hex)
            except (ValueError, OSError): self._publish(scan_id, preview_url='', message='This audio file is unavailable.')
        self._executor.submit(prepare)

    def _run(self, scan_id, cancel, selected):
        added = duplicates = failed = 0
        library_full = False
        for index, (key, path, details) in enumerate(selected):
            if cancel.is_set() or self._closed: return
            self._publish(scan_id, message=f'Importing sound {index + 1} of {len(selected)}…')
            try:
                if library_full:
                    raise ValueError('Sound library operation limit reached.')
                _regular(path); digest = file_hash(path)
                if any(a['content_hash'] == digest for a in self.library.list_assets()): state = 'existing'
                else:
                    self.library.import_file(path, details, uuid4().hex, cancelled=cancel.is_set); state = 'imported'
                result = {'id': key, 'state': state}
                if state == 'imported': added += 1
                else: duplicates += 1
            except ValueError as error:
                library_full = library_full or str(error) == 'Sound library operation limit reached.'
                result = {'id': key, 'state': 'failed',
                          'error': ('Sound library is full (2,000 sounds). Remove some sounds before importing more.'
                                    if library_full else 'Audio could not be imported. Check format, file access and disk space.')}
                failed += 1
            except Exception:
                result = {'id': key, 'state': 'failed', 'error': 'Audio could not be imported. Check format, file access and disk space.'}
                failed += 1
            with self._lock:
                if self._status['scan_id'] == scan_id and not cancel.is_set() and not self._closed:
                    self._results[key] = result
        self._publish(scan_id, busy=False, phase='finished',
                      message=f'Imported {added}; {duplicates} duplicates; {failed} failed. Originals were kept.'
                              + (' Sound library is full (2,000 sounds).' if library_full else ''))

    def cancel(self, scan_id: str) -> None:
        with self._lock:
            if scan_id != self._status['scan_id']: raise ValueError('This selection expired.')
            self._cancel.set(); self._paths = {}; self._entries = []; self._entry_by_id = {}; self._results = {}
            self._folders = []; self._folder_paths = set()
            self._status.update(busy=False, phase='cancelled', preview_url='', message='Sound operation cancelled.')

    def close(self):
        self._closed = True; self._cancel.set()
        self._executor.shutdown(wait=False, cancel_futures=True)
