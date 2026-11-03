"""Face-only crop analysis. Heavy imports execute only in the Ditto worker."""
from pathlib import Path
import uuid

try:
    from .crop_geometry import crop_basis
    from .media_cache import numeric_pngs, prepare_options
except ImportError:
    from crop_geometry import crop_basis
    from media_cache import numeric_pngs, prepare_options


def fit_source_frame(rgb, options):
    """Same resize/canvas rules for crop preview and actual preparation."""
    import cv2
    import numpy as np
    from core.atomic_components.loader import check_resize

    height, width, resize = check_resize(*rgb.shape[:2], max_dim=options['max_size'])
    if min(height, width) < 1:
        raise ValueError('Source frame is too small.')
    if resize:
        rgb = cv2.resize(rgb, (width, height))
    if options['canvas'] is not None:
        target_width, target_height = options['canvas']
        scale = min(target_width / rgb.shape[1], target_height / rgb.shape[0])
        width, height = max(1, round(rgb.shape[1]*scale)), max(1, round(rgb.shape[0]*scale))
        fitted = cv2.resize(rgb, (width, height))
        rgb = np.zeros((target_height, target_width, 3), dtype=np.uint8)
        x, y = (target_width-width)//2, (target_height-height)//2
        rgb[y:y+height, x:x+width] = fitted
    return rgb


def first_source_frame(source):
    import cv2
    import filetype
    import numpy as np

    source = Path(source).expanduser().resolve()
    if source.is_dir():
        source = numeric_pngs(source)[0]
    if not source.is_file():
        raise ValueError('Choose an existing source image, video or PNG frame folder.')
    if filetype.is_image(str(source)):
        bgr = cv2.imdecode(np.fromfile(source, dtype=np.uint8), cv2.IMREAD_COLOR)
    elif filetype.is_video(str(source)):
        reader = cv2.VideoCapture(str(source))
        try:
            ok, bgr = reader.read()
            if not ok:
                bgr = None
        finally:
            reader.release()
    else:
        raise ValueError('Source must be an image, video or numeric PNG frame folder.')
    if bgr is None:
        raise ValueError('Could not decode the first source frame.')
    return cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)


class FaceCropAnalyzer:
    """Only the three models used by Source2Info._crop, with its real method."""
    def __init__(self, repo):
        from core.atomic_components.cfg import parse_cfg
        from core.aux_models.insightface_det import InsightFaceDet
        from core.aux_models.insightface_landmark106 import Landmark106
        from core.aux_models.landmark203 import Landmark203

        cfg = parse_cfg(str(repo / 'checkpoints/ditto_cfg/v0.4_hubert_cfg_pytorch.pkl'),
                        str(repo / 'checkpoints/ditto_pytorch'))[0]
        self.insightface_det = InsightFaceDet(**cfg['insightface_det_cfg'])
        self.landmark106 = Landmark106(**cfg['landmark106_cfg'])
        self.landmark203 = Landmark203(**cfg['landmark203_cfg'])

    def _crop(self, rgb, **kwargs):
        from core.atomic_components.source2info import Source2Info
        return Source2Info._crop(self, rgb, **kwargs)


def preview_crop(worker, source_path, prepare_options=None):
    from PIL import Image

    options = globals()['prepare_options'](prepare_options)
    rgb = fit_source_frame(first_source_frame(source_path), options)
    if worker.registrar is not None:
        analyzer = worker.registrar.source2info
    else:
        if worker._crop_analyzer is None:
            worker.emit('progress', message='Loading face detection for crop preview…')
            worker._crop_analyzer = FaceCropAnalyzer(worker.repo)
        analyzer = worker._crop_analyzer
    worker.emit('progress', message='Finding the face in the first source frame…')
    result = analyzer._crop(rgb, crop_scale=1., crop_vx_ratio=0.,
                            crop_vy_ratio=0., crop_flag_do_rot=True)
    if result is None:
        raise ValueError('No face was detected in the first frame. Choose a clearer face image or video.')
    _, transform, _ = result
    height, width = rgb.shape[:2]
    basis = crop_basis(transform.tolist(), width, height)
    directory = worker.cache_root / 'crop-previews'
    directory.mkdir(parents=True, exist_ok=True)
    output = directory / (uuid.uuid4().hex + '.png')
    Image.fromarray(rgb).save(output)
    previous = getattr(worker, '_crop_preview_files', [])
    previous.append(output)
    worker._crop_preview_files = previous
    while len(previous) > 2:
        try:
            previous.pop(0).unlink(missing_ok=True)
        except OSError:
            pass
    return dict(preview_path=str(output), width=width, height=height, basis=basis)
