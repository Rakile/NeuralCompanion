"""Optional render-result metadata; no inference or playback decisions."""
from pathlib import Path


def render_source_mapping(paths, *, start, explicit, cycle):
    # Gapped output cannot be described as contiguous video. Let the existing
    # render validation handle it; never publish a plausible but wrong mapping.
    if (type(cycle) is not int or not 1 <= cycle <= 1440
            or type(start) is not int or not 1 <= len(paths) <= 1440
            or any(Path(path).name != f'{index:08d}.png' for index, path in enumerate(paths))
            or not isinstance(explicit, list)
            or (explicit and (len(explicit) < len(paths) or any(type(i) is not int for i in explicit)))):
        return {}
    return {'source_frame_count': cycle,
            'source_indices': [(explicit[i] if explicit else start+i) % cycle for i in range(len(paths))]}
