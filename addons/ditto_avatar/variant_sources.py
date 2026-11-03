"""Mapped prepared variants and one globally bounded decoded-image cache."""
from collections import OrderedDict
from pathlib import Path
import threading

try:
    from .media_cache import load_features, close_features, validate_prepared_avatar
except ImportError:
    from media_cache import load_features, close_features, validate_prepared_avatar


class VariantSources:
    def __init__(self, worker, *, rgb_budget_bytes=256*1024**2, max_images=64):
        if type(rgb_budget_bytes) is not int or rgb_budget_bytes < 0 or type(max_images) is not int or max_images < 1:
            raise ValueError('Invalid shared source-image cache limits.')
        self.worker = worker
        self.rgb_budget_bytes, self.max_images = rgb_budget_bytes, max_images
        self.entries = {}
        self.images = OrderedDict()
        self.cached_bytes = 0
        self._lock = threading.RLock()

    def register(self, avatar_path):
        root = Path(avatar_path).resolve()
        if root.is_file():
            root = root.parent
        key = str(root)
        with self._lock:
            if key in self.entries:
                return key
        checked = validate_prepared_avatar(root, portable_signature=self.worker.signature,
            legacy_signature=self.worker.legacy_signature,
            compatible_signatures=getattr(self.worker, 'compatible_signatures', ()),
            compatible_legacy_signatures=getattr(self.worker, 'compatible_legacy_signatures', ()))
        features = load_features(root/'features')
        features['memory_geometry'] = checked['canvas']
        registry = self
        class Images:
            def __len__(self):
                return len(checked['paths'])
            def __getitem__(self, index):
                return registry.image(key,index)
        features['img_rgb_lst'] = Images()
        with self._lock:
            if key in self.entries:
                close_features(features)
                return key
            self.entries[key] = dict(features=features, **checked)
        return key

    def get(self, source_key):
        return self.entries[source_key]['features']

    def manifest(self, source_key):
        return self.entries[source_key]['manifest']

    def image(self, source_key, index):
        import numpy as np
        from PIL import Image
        key = (source_key,index)
        with self._lock:
            if key in self.images:
                image = self.images.pop(key)
                self.images[key] = image
                return image
            path = self.entries[source_key]['paths'][index]
            with Image.open(path) as source:
                image = np.asarray(source.convert('RGB'))
            if image.nbytes <= self.rgb_budget_bytes:
                while self.images and (self.cached_bytes+image.nbytes > self.rgb_budget_bytes or len(self.images) >= self.max_images):
                    _, old = self.images.popitem(last=False)
                    self.cached_bytes -= old.nbytes
                self.images[key] = image
                self.cached_bytes += image.nbytes
            return image

    def close(self):
        with self._lock:
            for entry in self.entries.values():
                close_features(entry['features'])
            self.entries.clear()
            self.images.clear()
            self.cached_bytes = 0

    def retain(self, avatar_paths):
        """Called only after pipeline threads stop using the previous package."""
        keep = set()
        for path in avatar_paths:
            root = Path(path).resolve()
            keep.add(str(root.parent if root.is_file() else root))
        with self._lock:
            for key in list(self.entries):
                if key not in keep:
                    close_features(self.entries.pop(key)['features'])
            for key in list(self.images):
                if key[0] not in keep:
                    self.cached_bytes -= self.images.pop(key).nbytes
