"""Lossless adjacent parts for elongated Orb watch captures."""
import base64
import io

from PIL import Image


def split_watch_image(path):
    """Return chat image parts, or () to retain the original capture unchanged.

    Bounds are image-local (left, top, right, bottom), not desktop coordinates.
    The caller opts in only for the tested OpenAI watch path.
    """
    with Image.open(path) as source:
        width, height = source.size
        longest, shortest = max(width, height), min(width, height)
        if longest <= 2560 or longest <= 2 * shortest:
            return ()
        count = (longest + 2559) // 2560
        horizontal = width > height
        direction = 'left to right' if horizontal else 'top to bottom'
        image = source.convert('RGB')
        content = []
        for index in range(count):
            start, end = index * longest // count, (index + 1) * longest // count
            bounds = (start, 0, end, height) if horizontal else (0, start, width, end)
            with io.BytesIO() as buffer:
                image.crop(bounds).save(buffer, format='PNG')
                encoded = base64.b64encode(buffer.getvalue()).decode('ascii')
            content.extend((
                {'type': 'text', 'text': (
                    f'Part {index + 1}/{count} of the SAME screenshot, {direction}, no overlap. '
                    f'Original image bounds (left, top, right, bottom): {bounds}.')},
                {'type': 'image_url', 'image_url': {'url': f'data:image/png;base64,{encoded}'}},
            ))
        return tuple(content)
