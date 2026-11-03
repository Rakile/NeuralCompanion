"""Torch checkpoint loading compatibility helpers for bundled MuseTalk weights."""

from __future__ import annotations

import torch


def trusted_torch_load(*args, **kwargs):
    """Load trusted local MuseTalk checkpoints across old and new PyTorch versions."""
    kwargs = dict(kwargs)
    kwargs.setdefault("weights_only", False)
    try:
        return torch.load(*args, **kwargs)
    except TypeError as exc:
        if "weights_only" not in str(exc):
            raise
        kwargs.pop("weights_only", None)
        return torch.load(*args, **kwargs)
