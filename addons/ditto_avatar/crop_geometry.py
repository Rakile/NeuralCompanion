"""Small crop-outline math shared by the host and isolated worker; no SDK imports."""
import math


def _pair(value):
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise ValueError('Invalid crop basis.')
    result = [float(v) for v in value]
    if not all(math.isfinite(v) for v in result):
        raise ValueError('Invalid crop basis.')
    return result


def crop_basis(transform, width, height):
    """Unit-scale, zero-offset, rotation-aligned 512 crop -> source basis."""
    if len(transform) != 3 or any(len(row) != 3 for row in transform):
        raise ValueError('Invalid crop transform.')
    rows = [[float(v) for v in row] for row in transform]
    if not all(math.isfinite(v) for row in rows for v in row):
        raise ValueError('Invalid crop transform.')
    x = [rows[0][0] * 512, rows[1][0] * 512]
    y = [rows[0][1] * 512, rows[1][1] * 512]
    center = [rows[i][2] + (x[i] + y[i]) / 2 for i in range(2)]
    basis = dict(center=center, x=x, y=y, width=width, height=height)
    crop_outline(basis, 1., 0., 0., True)
    return basis


def crop_outline(basis, scale, horizontal, vertical, rotate):
    """Normalized source-image corners, retaining out-of-image positions."""
    center, x, y = (_pair(basis[key]) for key in ('center', 'x', 'y'))
    width, height = float(basis['width']), float(basis['height'])
    scale, horizontal, vertical = float(scale), float(horizontal), float(vertical)
    if (not all(math.isfinite(v) for v in (width, height, scale, horizontal, vertical))
            or min(width, height, scale, math.hypot(*x), math.hypot(*y)) <= 0
            or type(rotate) is not bool):
        raise ValueError('Invalid crop geometry or settings.')
    center = [center[i] + scale * (horizontal*x[i] + vertical*y[i]) for i in range(2)]
    if not rotate:
        x, y = [math.hypot(*x), 0.], [0., math.hypot(*y)]
    return [[(center[0] + scale*(a*x[0] + b*y[0])/2) / width,
             (center[1] + scale*(a*x[1] + b*y[1])/2) / height]
            for a, b in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
