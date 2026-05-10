"""Shared hand debug and calibration state for avatar body controls."""

from __future__ import annotations


HAND_DEBUG = {
    "active": False,
    "thumb_x": 0.0,
    "thumb_y": 0.0,
    "thumb_z": 0.0,
    "finger_x": 0.0,
    "finger_y": 0.0,
    "finger_z": 0.0,
}


HAND_CALIBRATION = {
    "relaxed": {
        "finger_x": -180.0,
        "finger_y": -180.0,
        "finger_z": -180.0,
        "thumb_x": -180.0,
        "thumb_y": -180.0,
        "thumb_z": -180.0,
    },
    "fist": {
        "finger_x": -180.0,
        "finger_y": -170.0,
        "finger_z": -82.0,
        "thumb_x": -167.0,
        "thumb_y": -121.0,
        "thumb_z": -160.0,
    },
}


def hand_debug() -> dict:
    return HAND_DEBUG


def hand_calibration() -> dict:
    return HAND_CALIBRATION
