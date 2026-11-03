import os
import sys

try:
    from ditto_blend import blend_images_cy
except ModuleNotFoundError as error:
    # Only a missing optional wheel permits the existing developer build path.
    # A broken installed wheel must retain its actionable import error.
    if error.name != 'ditto_blend':
        raise
    import pyximport
    pyximport.install(build_dir=os.path.join(sys.prefix, ".pyxbld"))
    from .blend import blend_images_cy
