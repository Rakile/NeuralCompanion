"""Prepared-avatar metadata and safe NumPy arrays; heavy imports stay in worker calls."""
import hashlib
import json
import math
from pathlib import Path

FPS = 25
SCHEMA = 2
EXTRACTOR_FORMAT = 'ditto-source-v2'
PREPARE_DEFAULTS = {'max_size': 1920, 'crop_scale': 2.3, 'crop_vx_ratio': 0.0,
                    'crop_vy_ratio': -0.125, 'crop_flag_do_rot': True,
                    'loop_mode': 'pingpong', 'sequence_fps': 25, 'source_frames': -1,
                    'video_fps_policy': 'ask', 'canvas': None}


def numeric_pngs(directory):
    frames = sorted((p for p in Path(directory).glob('*.png') if p.stem.isdecimal()),
                    key=lambda p: int(p.stem))
    if not frames:
        raise ValueError('PNG directory must contain numerically named frames, e.g. 0.png.')
    if len({int(p.stem) for p in frames}) != len(frames):
        raise ValueError('Ambiguous numeric frame names (e.g. 1.png and 01.png).')
    return frames


def deduplicate_frames(paths):
    unique, indices, hashes = [], [], {}
    for path in paths:
        digest = hashlib.sha256(Path(path).read_bytes()).hexdigest()
        if digest not in hashes:
            hashes[digest] = len(unique)
            unique.append(Path(path))
        indices.append(hashes[digest])
    return unique, indices


def playback_indices(order, start, count, loop_mode='pingpong'):
    if not order or start < 0 or count < 0 or loop_mode not in ('pingpong', 'forward'):
        raise ValueError('Invalid playback timeline, position, count, or loop mode.')
    cycle = order + order[::-1] if loop_mode == 'pingpong' and len(order) > 1 else order
    return [cycle[i % len(cycle)] for i in range(start, start + count)]


def prepare_options(options=None):
    supplied = options or {}
    if set(supplied) - set(PREPARE_DEFAULTS):
        raise ValueError('Unsupported preparation options: ' + ', '.join(set(supplied) - set(PREPARE_DEFAULTS)))
    result = {**PREPARE_DEFAULTS, **supplied}
    canvas = result['canvas']
    if canvas is not None:
        if not isinstance(canvas, (list, tuple)) or len(canvas) != 2 or any(type(v) is not int or not 1 <= v <= 8192 for v in canvas):
            raise ValueError('Package canvas needs width and height between 1 and 8192.')
        result['canvas'] = list(canvas)
    if result['loop_mode'] not in ('pingpong', 'forward'):
        raise ValueError('loop_mode must be pingpong or forward.')
    if result['video_fps_policy'] not in ('ask', 'convert', 'keep'):
        raise ValueError('video_fps_policy must be ask, convert or keep.')
    if not isinstance(result['crop_flag_do_rot'], bool):
        raise ValueError('crop_flag_do_rot must be boolean.')
    limit = result['source_frames']
    if isinstance(limit, bool) or not isinstance(limit, int) or limit == 0 or limit < -1:
        raise ValueError('source_frames must be -1 (all) or a positive integer.')
    for key, low, high in (('max_size', 256, 8192), ('crop_scale', .1, 10),
                           ('crop_vx_ratio', -2, 2), ('crop_vy_ratio', -2, 2),
                           ('sequence_fps', 1, 240)):
        value = float(result[key])
        if not math.isfinite(value) or not low <= value <= high:
            raise ValueError(f'Invalid {key}.')
        if key == 'max_size':
            if not value.is_integer():
                raise ValueError('max_size must be an integer.')
            value = int(value)
        result[key] = value
    return result


def save_features(directory, data):
    import numpy as np
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    counter = 0

    def encode(value):
        nonlocal counter
        if isinstance(value, np.ndarray):
            if value.dtype.hasobject:
                raise ValueError('Object arrays cannot be stored in an avatar cache.')
            filename = f'array-{counter:06d}.npy'
            counter += 1
            np.save(directory / filename, value, allow_pickle=False)
            return {'__array__': filename}
        if isinstance(value, dict):
            return {key: encode(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [encode(item) for item in value]
        if isinstance(value, (str, int, float, bool)) or value is None:
            return value
        raise ValueError(f'Unsupported cache value: {type(value).__name__}')

    tree = encode(data)
    (directory / 'features.json').write_text(json.dumps(tree, allow_nan=False), encoding='utf-8')


def load_features(directory):
    import numpy as np
    directory = Path(directory).resolve()

    def decode(value):
        if isinstance(value, dict):
            if set(value) == {'__array__'}:
                path = (directory / value['__array__']).resolve()
                if path.parent != directory or path.suffix != '.npy':
                    raise ValueError('Invalid cache array path.')
                return np.load(path, mmap_mode='r', allow_pickle=False)
            return {key: decode(item) for key, item in value.items()}
        if isinstance(value, list):
            return [decode(item) for item in value]
        return value

    return decode(json.loads((directory / 'features.json').read_text(encoding='utf-8')))


def _compatible_crop_sources(current):
    # Saved crops/features are self-contained. This exact vx forwarding fix
    # changes future preparation, not the format/meaning of existing tensors.
    # Never generalize this exception to arbitrary edits or unchecked code.
    fixed = 'b2cd927bde6bd877815c294f766b7b4e311ecbc703435c0c8b455d163a039279'
    previous = '3c361d3651bba2e87a6e04708958f4f0821c301202697e9ac01a799399589757'
    if hashlib.sha256(current).hexdigest() == fixed:
        line = b'        vx_ratio=kwargs.get("vx_ratio", 0),\r\n'
        predecessor = current.replace(line, b'')
        if current.count(line) == 1 and hashlib.sha256(predecessor).hexdigest() == previous:
            return current, predecessor
    return (current,)


def legacy_model_signature(repo, *, include_compatible=False):
    """Fingerprint checkpoint inventory, config, and extraction code without rereading GB weights."""
    repo = Path(repo)
    files = sorted((repo / 'checkpoints/ditto_pytorch').rglob('*'))
    inventory = [(str(p.relative_to(repo)), p.stat().st_size, p.stat().st_mtime_ns)
                 for p in files if p.is_file()]
    digest = hashlib.sha256(json.dumps(inventory).encode())
    for relative in ('checkpoints/ditto_cfg/v0.4_hubert_cfg_pytorch.pkl',
                     'checkpoints/download-manifest.json',
                     'core/atomic_components/source2info.py'):
        path = repo / relative
        if path.is_file():
            digest.update(path.read_bytes())
    crop = repo / 'core/utils/crop.py'
    current = crop.read_bytes() if crop.is_file() else b''
    versions = _compatible_crop_sources(current) if include_compatible else (current,)
    signatures = []
    for source in versions:
        candidate = digest.copy()
        candidate.update(source)
        signatures.append(candidate.hexdigest())
    return tuple(signatures) if include_compatible else signatures[0]


def portable_model_signature(repo, *, include_compatible=False):
    """Verify model bytes once per worker load; never use locations or mtimes."""
    repo = Path(repo).resolve()
    inventory_path = repo / 'model-manifest.json'
    if inventory_path.is_file():
        inventory = json.loads(inventory_path.read_text(encoding='utf-8'))['files']
    else:
        original = json.loads((repo / 'checkpoints/download-manifest.json').read_text(encoding='utf-8'))
        inventory = [dict(path=item['path'], size=item['size'], sha256=item['lfs']['oid']) for item in original]
    if not inventory:
        raise ValueError('Ditto checkpoint inventory is empty.')
    content = []
    for item in sorted(inventory, key=lambda value: value['path']):
        root = (repo / 'checkpoints').resolve()
        path = (root / item['path']).resolve()
        if not path.is_relative_to(root) or not path.is_file() or path.stat().st_size != item['size']:
            raise ValueError(f'Missing/incompatible checkpoint: {item["path"]}')
        digest = hashlib.sha256()
        with path.open('rb') as handle:
            for block in iter(lambda: handle.read(8*1024**2), b''):
                digest.update(block)
        if digest.hexdigest() != item['sha256']:
            raise ValueError(f'Checkpoint content differs from inventory: {item["path"]}')
        content.append((item['path'], digest.hexdigest()))
    name = 'core/atomic_components/source2info.py'
    content.append((name, hashlib.sha256((repo / name).read_bytes()).hexdigest()))
    name = 'core/utils/crop.py'
    current = (repo / name).read_bytes()
    versions = _compatible_crop_sources(current) if include_compatible else (current,)
    signatures = tuple(hashlib.sha256(json.dumps([EXTRACTOR_FORMAT,
        content + [(name, hashlib.sha256(source).hexdigest())]],
        separators=(',', ':')).encode()).hexdigest() for source in versions)
    return signatures if include_compatible else signatures[0]


# Keep callers on the portable signature; schema-1 validation takes a separate proof.
model_signature = portable_model_signature


def read_manifest(avatar_path, expected_signature=None, *, legacy_signature=None,
                  compatible_signatures=(), compatible_legacy_signatures=()):
    root = Path(avatar_path).resolve()
    if root.is_file():
        root = root.parent
    manifest = json.loads((root / 'avatar.json').read_text(encoding='utf-8'))
    schema = manifest.get('schema_version')
    if schema not in (1, SCHEMA) or manifest.get('fps') != FPS:
        raise ValueError('Unsupported Ditto avatar cache format or FPS; prepare the avatar again.')
    expected = legacy_signature if schema == 1 and legacy_signature is not None else expected_signature
    compatible = compatible_legacy_signatures if schema == 1 else compatible_signatures
    if expected and manifest.get('model_signature') not in (expected, *compatible):
        raise ValueError('Avatar was prepared with different models/extractor code; prepare again.')
    if schema == 2 and manifest.get('signature_kind') != 'content-v1':
        raise ValueError('Unsupported prepared-cache fingerprint; prepare the avatar again.')
    if not isinstance(manifest.get('frame_paths'), list) or not manifest['frame_paths']:
        raise ValueError('Avatar cache has no source frames.')
    paths = []
    for name in manifest['frame_paths']:
        path = (root / name).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise ValueError('Avatar cache has an invalid or missing frame path.')
        paths.append(path)
    order = manifest['source_order']
    if not isinstance(order, list) or not order or any(type(i) is not int or not 0 <= i < len(paths) for i in order):
        raise ValueError('Avatar has invalid source indices.')
    return root, manifest, paths


def close_features(data):
    """Release only maps owned by this prepared feature tree, after its users stop."""
    if isinstance(data, dict):
        for value in data.values():
            close_features(value)
    elif isinstance(data, (list, tuple)):
        for value in data:
            close_features(value)
    else:
        mapping = getattr(data, '_mmap', None)
        if mapping is not None and not mapping.closed:
            mapping.close()


def validate_prepared_avatar(avatar_path, *, portable_signature, legacy_signature=None, canvas=None,
                             compatible_signatures=(), compatible_legacy_signatures=()):
    import numpy as np
    from PIL import Image
    root, manifest, paths = read_manifest(avatar_path, portable_signature, legacy_signature=legacy_signature,
        compatible_signatures=compatible_signatures, compatible_legacy_signatures=compatible_legacy_signatures)
    if manifest['schema_version'] == 1 and legacy_signature is None:
        raise ValueError('Legacy prepared avatar compatibility is unproven; use its original runtime or prepare again.')
    geometry = None
    for path in paths:
        with Image.open(path) as image:
            if geometry is None:
                geometry = image.size
            if image.size != geometry:
                raise ValueError('Prepared avatar frames have different canvas dimensions; prepare again.')
    if canvas is not None and geometry != tuple(canvas):
        raise ValueError('Prepared avatar canvas differs from this package; make a preparation copy from source media.')
    data = None
    try:
        data = load_features(root / 'features')
        for key in ('x_s_info_lst', 'f_s_lst', 'M_c2o_lst', 'eye_open_lst', 'eye_ball_lst'):
            values = data.get(key)
            if not isinstance(values, list) or len(values) != len(paths):
                raise ValueError(f'Prepared feature count differs from source frames: {key}')
        for motion in data['x_s_info_lst']:
            if not isinstance(motion, dict) or any(np.asarray(motion.get(key)).size != 63 for key in ('kp', 'exp')):
                raise ValueError('Prepared source motion has invalid keypoints/expressions.')
        for transform in data['M_c2o_lst']:
            if np.asarray(transform).shape not in ((2, 3), (3, 3)) or not np.isfinite(transform).all():
                raise ValueError('Prepared compositing transform is invalid.')
        if np.asarray(data.get('sc')).size != 63 or type(data.get('is_image_flag')) is not bool:
            raise ValueError('Prepared source conditioning is invalid.')
        for key, size in (('eye_open_lst', 2), ('eye_ball_lst', 6)):
            if any(np.asarray(value).size != size for value in data[key]):
                raise ValueError(f'Invalid prepared eye conditioning: {key}')
        if any(np.asarray(value).ndim < 2 or not np.asarray(value).size for value in data['f_s_lst']):
            raise ValueError('Prepared appearance features are invalid.')
    finally:
        if data is not None:
            close_features(data)
    return dict(root=root, manifest=manifest, paths=paths, canvas=geometry,
                portable_signature=portable_signature, legacy_validated=manifest['schema_version'] == 1)
