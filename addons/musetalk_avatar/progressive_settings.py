"""Progressive MuseTalk startup buffering; independent of avatar assets."""
import math

KEY='musetalk_progressive_buffer_seconds'
DEFAULT=2.0
MINIMUM=.5
MAXIMUM=4.0


def normalize_buffer_seconds(value):
    if isinstance(value,bool):return DEFAULT
    try:value=float(value)
    except (TypeError,ValueError,OverflowError):return DEFAULT
    if not math.isfinite(value):return DEFAULT
    return min(MAXIMUM,max(MINIMUM,value))


def initial_frame_count(seconds,fps):
    if type(fps) is not int or not 0<fps<=24000:
        raise ValueError('MuseTalk requires a positive integral frame rate')
    # Whisper's 50Hz feature phase also aligns the 24kHz PCM sample grid.
    phase=fps//math.gcd(50,fps)
    return math.ceil(normalize_buffer_seconds(seconds)*fps/phase)*phase
