"""Shared storage defaults; future Debug Logger Addon settings belong here."""
from dataclasses import dataclass


@dataclass(frozen=True)
class RetentionLimits:
    capture_slots: int = 8
    capture_bytes: int = 64 * 1024 * 1024
    capture_files: int = 64
    archive_bytes: int = 1024 * 1024 * 1024
    warn_fraction: float = 0.8
    pressure_keep_latest: int = 2

    def __post_init__(self):
        for value in (self.capture_slots, self.capture_bytes, self.capture_files, self.archive_bytes):
            if type(value) is not int or value < 1:
                raise ValueError('diagnostic_retention_invalid_limit')
        if (type(self.warn_fraction) not in (int, float) or not 0 < self.warn_fraction < 1
                or type(self.pressure_keep_latest) is not int
                or not 0 <= self.pressure_keep_latest < self.capture_slots):
            raise ValueError('diagnostic_retention_invalid_limit')


DEFAULT_RETENTION = RetentionLimits()
