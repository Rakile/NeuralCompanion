from __future__ import annotations

import ctypes
import threading
from pathlib import Path
from typing import Any

from .models import DeviceDescriptor, LedPoint, RgbColor

CORSAIR_STRING_SIZE_M = 128
CORSAIR_DEVICE_COUNT_MAX = 64
CORSAIR_DEVICE_LEDCOUNT_MAX = 512
CE_SUCCESS = 0
CSS_CLOSED = 1
CSS_CONNECTING = 2
CSS_TIMEOUT = 3
CSS_CONNECTION_REFUSED = 4
CSS_CONNECTION_LOST = 5
CSS_CONNECTED = 6
CDT_KEYBOARD = 0x0001

_ERROR_NAMES = {
    0: "success",
    1: "not connected (is iCUE running with SDK integrations enabled?)",
    2: "lighting control is held by another exclusive client",
    3: "incompatible iCUE SDK protocol",
    4: "invalid SDK arguments",
    5: "invalid SDK operation",
    6: "device not found",
    7: "operation not allowed by iCUE",
}
_STATE_NAMES = {
    1: "closed",
    2: "connecting",
    3: "timeout",
    4: "connection refused",
    5: "connection lost",
    6: "connected",
}


class CorsairVersion(ctypes.Structure):
    _fields_ = [("major", ctypes.c_int), ("minor", ctypes.c_int), ("patch", ctypes.c_int)]


class CorsairSessionDetails(ctypes.Structure):
    _fields_ = [
        ("clientVersion", CorsairVersion),
        ("serverVersion", CorsairVersion),
        ("serverHostVersion", CorsairVersion),
    ]


class CorsairSessionStateChanged(ctypes.Structure):
    _fields_ = [("state", ctypes.c_int), ("details", CorsairSessionDetails)]


class CorsairDeviceInfo(ctypes.Structure):
    _fields_ = [
        ("type", ctypes.c_int),
        ("id", ctypes.c_char * CORSAIR_STRING_SIZE_M),
        ("serial", ctypes.c_char * CORSAIR_STRING_SIZE_M),
        ("model", ctypes.c_char * CORSAIR_STRING_SIZE_M),
        ("ledCount", ctypes.c_int),
        ("channelCount", ctypes.c_int),
    ]


class CorsairLedPosition(ctypes.Structure):
    _fields_ = [("id", ctypes.c_uint), ("cx", ctypes.c_double), ("cy", ctypes.c_double)]


class CorsairDeviceFilter(ctypes.Structure):
    _fields_ = [("deviceTypeMask", ctypes.c_int)]


class CorsairLedColor(ctypes.Structure):
    _fields_ = [
        ("id", ctypes.c_uint),
        ("r", ctypes.c_ubyte),
        ("g", ctypes.c_ubyte),
        ("b", ctypes.c_ubyte),
        ("a", ctypes.c_ubyte),
    ]


CorsairSessionStateChangedHandler = ctypes.CFUNCTYPE(
    None, ctypes.c_void_p, ctypes.POINTER(CorsairSessionStateChanged)
)


class IcueSdkError(RuntimeError):
    pass


def locate_sdk_dll(addon_root: Path, configured_path: str = "") -> Path:
    configured = str(configured_path or "").strip().strip('"')
    if configured:
        candidate = Path(configured).expanduser().resolve()
        if candidate.is_file():
            return candidate
        raise IcueSdkError(f"Configured iCUE SDK DLL was not found: {candidate}")
    sdk_dir = Path(addon_root).resolve() / "sdk"
    candidates = sorted(sdk_dir.glob("*.dll")) if sdk_dir.is_dir() else []
    preferred = [path for path in candidates if "cue" in path.name.lower() and "sdk" in path.name.lower()]
    if preferred:
        return preferred[0].resolve()
    raise IcueSdkError(
        f"Official iCUE SDK x64 DLL not found. Place it in {sdk_dir} or select it in addon settings."
    )


def _decode(value: Any) -> str:
    return bytes(value).split(b"\0", 1)[0].decode("utf-8", errors="replace").strip()


class IcueSdkBridge:
    """Minimal typed wrapper over Corsair's official iCUE SDK v4 C API."""

    def __init__(
        self,
        dll_path: Path,
        *,
        dll: Any = None,
        connection_timeout_s: float = 3.0,
        layer_priority: int = 180,
    ) -> None:
        self.dll_path = Path(dll_path)
        self._dll = dll if dll is not None else ctypes.WinDLL(str(self.dll_path))
        self._connection_timeout_s = max(0.1, float(connection_timeout_s))
        self._layer_priority = max(0, min(255, int(layer_priority)))
        self._connection_event = threading.Event()
        self._session_state = CSS_CLOSED
        self._session_open = False
        self._connected = False
        self._session_callback = CorsairSessionStateChangedHandler(self._on_session_state)
        self._configure_signatures()

    @property
    def connected(self) -> bool:
        return self._connected

    def _configure_signatures(self) -> None:
        self._dll.CorsairConnect.argtypes = [CorsairSessionStateChangedHandler, ctypes.c_void_p]
        self._dll.CorsairConnect.restype = ctypes.c_int
        self._dll.CorsairDisconnect.argtypes = []
        self._dll.CorsairDisconnect.restype = ctypes.c_int
        self._dll.CorsairGetDevices.argtypes = [
            ctypes.POINTER(CorsairDeviceFilter),
            ctypes.c_int,
            ctypes.POINTER(CorsairDeviceInfo),
            ctypes.POINTER(ctypes.c_int),
        ]
        self._dll.CorsairGetDevices.restype = ctypes.c_int
        self._dll.CorsairGetLedPositions.argtypes = [
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.POINTER(CorsairLedPosition),
            ctypes.POINTER(ctypes.c_int),
        ]
        self._dll.CorsairGetLedPositions.restype = ctypes.c_int
        self._dll.CorsairSetLedColors.argtypes = [
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.POINTER(CorsairLedColor),
        ]
        self._dll.CorsairSetLedColors.restype = ctypes.c_int
        self._dll.CorsairSetLayerPriority.argtypes = [ctypes.c_uint]
        self._dll.CorsairSetLayerPriority.restype = ctypes.c_int

    def _on_session_state(self, _context: Any, event_ptr: Any) -> None:
        if not event_ptr:
            return
        state = int(event_ptr.contents.state)
        self._session_state = state
        self._connected = state == CSS_CONNECTED
        if state in {CSS_CONNECTED, CSS_TIMEOUT, CSS_CONNECTION_REFUSED, CSS_CONNECTION_LOST, CSS_CLOSED}:
            self._connection_event.set()

    def connect(self) -> None:
        if self._connected:
            return
        self._connection_event.clear()
        self._session_state = CSS_CONNECTING
        result = int(self._dll.CorsairConnect(self._session_callback, None))
        self._check(result, "connect")
        self._session_open = True
        if not self._connection_event.wait(self._connection_timeout_s):
            raise IcueSdkError("Timed out waiting for iCUE SDK connection.")
        if not self._connected:
            state_name = _STATE_NAMES.get(self._session_state, f"state {self._session_state}")
            raise IcueSdkError(f"iCUE SDK connection did not open: {state_name}.")
        self._check(int(self._dll.CorsairSetLayerPriority(self._layer_priority)), "set layer priority")

    def disconnect(self) -> None:
        if not self._session_open:
            return
        try:
            result = int(self._dll.CorsairDisconnect())
            if result != CE_SUCCESS:
                raise IcueSdkError(f"Could not disconnect from iCUE SDK: {_ERROR_NAMES.get(result, result)}")
        finally:
            self._session_open = False
            self._connected = False
            self._session_state = CSS_CLOSED

    def list_keyboards(self) -> tuple[DeviceDescriptor, ...]:
        self._require_connected()
        device_filter = CorsairDeviceFilter(CDT_KEYBOARD)
        devices = (CorsairDeviceInfo * CORSAIR_DEVICE_COUNT_MAX)()
        count = ctypes.c_int(0)
        result = int(
            self._dll.CorsairGetDevices(
                ctypes.byref(device_filter), CORSAIR_DEVICE_COUNT_MAX, devices, ctypes.byref(count)
            )
        )
        self._check(result, "enumerate keyboards")
        descriptions: list[DeviceDescriptor] = []
        for index in range(max(0, min(CORSAIR_DEVICE_COUNT_MAX, int(count.value)))):
            info = devices[index]
            if int(info.type) != CDT_KEYBOARD:
                continue
            device_id = _decode(info.id)
            if not device_id:
                continue
            led_points = self.get_led_positions(device_id, expected_count=int(info.ledCount))
            descriptions.append(DeviceDescriptor(device_id, _decode(info.model), led_points))
        return tuple(descriptions)

    def get_led_positions(self, device_id: str, *, expected_count: int = 0) -> tuple[LedPoint, ...]:
        self._require_connected()
        maximum = max(1, min(CORSAIR_DEVICE_LEDCOUNT_MAX, expected_count or CORSAIR_DEVICE_LEDCOUNT_MAX))
        positions = (CorsairLedPosition * maximum)()
        count = ctypes.c_int(0)
        result = int(
            self._dll.CorsairGetLedPositions(
                str(device_id).encode("utf-8"), maximum, positions, ctypes.byref(count)
            )
        )
        self._check(result, f"read LED positions for {device_id}")
        return tuple(
            LedPoint(int(positions[index].id), float(positions[index].cx), float(positions[index].cy))
            for index in range(max(0, min(maximum, int(count.value))))
        )

    def set_led_colors(self, device_id: str, colors: dict[int, RgbColor]) -> None:
        self._require_connected()
        if not colors:
            return
        ordered = sorted(colors.items())
        payload = (CorsairLedColor * len(ordered))(
            *(
                CorsairLedColor(
                    int(led_id),
                    max(0, min(255, int(color[0]))),
                    max(0, min(255, int(color[1]))),
                    max(0, min(255, int(color[2]))),
                    255,
                )
                for led_id, color in ordered
            )
        )
        result = int(self._dll.CorsairSetLedColors(str(device_id).encode("utf-8"), len(ordered), payload))
        self._check(result, f"write LED colors for {device_id}")

    def clear_device(self, device: DeviceDescriptor) -> None:
        self.set_led_colors(device.device_id, {point.led_id: (0, 0, 0) for point in device.led_points})

    def _require_connected(self) -> None:
        if not self._connected:
            raise IcueSdkError("iCUE SDK is not connected.")

    @staticmethod
    def _check(result: int, operation: str) -> None:
        if result != CE_SUCCESS:
            raise IcueSdkError(f"Could not {operation}: {_ERROR_NAMES.get(result, f'error {result}')}")
