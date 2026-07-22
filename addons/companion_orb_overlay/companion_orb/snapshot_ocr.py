from __future__ import annotations

import csv
import inspect
import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any


def _normalize_text(value) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip().lower()
    return re.sub(r"[^a-z0-9_./: -]+", "", text)


def _tokens(value) -> set[str]:
    return set(re.findall(r"[a-z0-9_./:-]{3,}", _normalize_text(value)))


def _screen_bounds(image_bounds, image_size, screen_bounds) -> list[int]:
    try:
        ix, iy, iw, ih = [float(value) for value in image_bounds]
        image_w, image_h = [float(value) for value in image_size]
        left, top, width, height = [float(value) for value in screen_bounds]
    except Exception:
        return []
    if image_w <= 0 or image_h <= 0 or width <= 0 or height <= 0:
        return []
    return [
        int(round(left + ix * (width / image_w))),
        int(round(top + iy * (height / image_h))),
        max(1, int(round(iw * (width / image_w)))),
        max(1, int(round(ih * (height / image_h)))),
    ]


def _region(text, image_bounds, image_size, screen_bounds, *, confidence=0.0, backend="", kind="text") -> dict[str, Any]:
    image_values = [int(round(float(value))) for value in image_bounds]
    return {
        "text": str(text or "").strip(),
        "normalized_text": _normalize_text(text),
        "confidence": float(confidence or 0.0),
        "image_bounds": image_values,
        "screen_bounds": _screen_bounds(image_values, image_size, screen_bounds),
        "backend": str(backend or ""),
        "kind": str(kind or "text"),
    }


def _screen_region(text, bounds, *, confidence=0.0, backend="", kind="text") -> dict[str, Any]:
    try:
        screen_values = [int(round(float(value))) for value in list(bounds or [])[:4]]
    except Exception:
        screen_values = []
    if len(screen_values) != 4 or screen_values[2] <= 0 or screen_values[3] <= 0:
        screen_values = []
    return {
        "text": str(text or "").strip(),
        "normalized_text": _normalize_text(text),
        "confidence": float(confidence or 0.0),
        "image_bounds": [],
        "screen_bounds": screen_values,
        "backend": str(backend or ""),
        "kind": str(kind or "text"),
    }


def _intersects(left, right) -> bool:
    try:
        ax, ay, aw, ah = [int(value) for value in list(left or [])[:4]]
        bx, by, bw, bh = [int(value) for value in list(right or [])[:4]]
    except Exception:
        return False
    if aw <= 0 or ah <= 0 or bw <= 0 or bh <= 0:
        return False
    return not (ax + aw <= bx or bx + bw <= ax or ay + ah <= by or by + bh <= ay)


def _clip_bounds(bounds, clip) -> list[int]:
    try:
        ax, ay, aw, ah = [int(value) for value in list(bounds or [])[:4]]
        bx, by, bw, bh = [int(value) for value in list(clip or [])[:4]]
    except Exception:
        return []
    left = max(ax, bx)
    top = max(ay, by)
    right = min(ax + aw, bx + bw)
    bottom = min(ay + ah, by + bh)
    if right <= left or bottom <= top:
        return []
    return [left, top, right - left, bottom - top]


def _extract_with_win32_window_text(screen_bounds, *, max_regions: int) -> list[dict[str, Any]]:
    try:
        import win32gui
    except Exception:
        return []
    try:
        target_bounds = [int(value) for value in list(screen_bounds or [])[:4]]
    except Exception:
        return []
    if len(target_bounds) != 4 or target_bounds[2] <= 0 or target_bounds[3] <= 0:
        return []
    regions: list[dict[str, Any]] = []
    seen: set[tuple[str, tuple[int, int, int, int]]] = set()

    def add_region(text, bounds, *, kind):
        cleaned = re.sub(r"\s+", " ", str(text or "")).strip()
        if len(cleaned) < 2:
            return
        clipped = _clip_bounds(bounds, target_bounds)
        if not clipped:
            return
        key = (_normalize_text(cleaned)[:180], tuple(clipped))
        if key in seen:
            return
        seen.add(key)
        regions.append(_screen_region(cleaned, clipped, confidence=0.55, backend="win32_window_text", kind=kind))

    def rect_to_bounds(hwnd):
        try:
            left, top, right, bottom = win32gui.GetWindowRect(hwnd)
        except Exception:
            return []
        width = int(right - left)
        height = int(bottom - top)
        if width <= 0 or height <= 0:
            return []
        return [int(left), int(top), width, height]

    def visit_child(hwnd, _param):
        if len(regions) >= max_regions:
            return False
        try:
            if not win32gui.IsWindowVisible(hwnd):
                return True
        except Exception:
            return True
        bounds = rect_to_bounds(hwnd)
        if not bounds or not _intersects(bounds, target_bounds):
            return True
        try:
            text = win32gui.GetWindowText(hwnd)
        except Exception:
            text = ""
        add_region(text, bounds, kind="control_text")
        return True

    def visit_window(hwnd, _param):
        if len(regions) >= max_regions:
            return False
        try:
            if not win32gui.IsWindowVisible(hwnd) or win32gui.IsIconic(hwnd):
                return True
        except Exception:
            return True
        bounds = rect_to_bounds(hwnd)
        if not bounds or not _intersects(bounds, target_bounds):
            return True
        try:
            title = win32gui.GetWindowText(hwnd)
        except Exception:
            title = ""
        add_region(title, bounds, kind="window_title")
        try:
            win32gui.EnumChildWindows(hwnd, visit_child, None)
        except Exception:
            pass
        return len(regions) < max_regions

    try:
        win32gui.EnumWindows(visit_window, None)
    except Exception:
        return []
    return regions[:max_regions]


def extract_window_text_regions(screen_bounds, *, max_regions: int = 80) -> list[dict[str, Any]]:
    """Return text exposed by Windows controls in the selected screen bounds."""
    try:
        return _extract_with_win32_window_text(screen_bounds, max_regions=max(1, int(max_regions or 80)))
    except Exception:
        return []


def readable_text_from_regions(regions) -> str:
    """Convert OCR/window-text regions into stable readable text."""
    lines: list[tuple[int, int, str]] = []
    seen: set[str] = set()
    try:
        region_items = list(regions or [])
    except Exception:
        return ""
    for item in region_items:
        if not isinstance(item, dict):
            continue
        text = re.sub(r"\s+", " ", str(item.get("text") or "")).strip()
        if not text:
            continue
        key = re.sub(r"\s+", " ", text).strip().casefold() or _normalize_text(text)
        if not key or key in seen:
            continue
        seen.add(key)
        bounds = item.get("screen_bounds") or []
        try:
            x_value = int(bounds[0])
            y_value = int(bounds[1])
        except Exception:
            x_value = 0
            y_value = len(lines)
        lines.append((y_value, x_value, text))
    lines.sort(key=lambda row: (row[0], row[1]))
    return "\n".join(text for _y, _x, text in lines).strip()


def _merge_bounds(bounds_list) -> list[int]:
    values = []
    for bounds in bounds_list:
        try:
            x, y, w, h = [int(value) for value in bounds]
        except Exception:
            continue
        if w > 0 and h > 0:
            values.append((x, y, x + w, y + h))
    if not values:
        return []
    return [
        min(item[0] for item in values),
        min(item[1] for item in values),
        max(item[2] for item in values) - min(item[0] for item in values),
        max(item[3] for item in values) - min(item[1] for item in values),
    ]


def _parse_tesseract_tsv(tsv_text: str, image_size, screen_bounds) -> list[dict[str, Any]]:
    rows = list(csv.DictReader(str(tsv_text or "").splitlines(), delimiter="\t"))
    words = []
    lines: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for row in rows:
        text = str(row.get("text") or "").strip()
        if not text:
            continue
        try:
            conf = float(row.get("conf", 0) or 0)
            bounds = [int(row.get("left", 0) or 0), int(row.get("top", 0) or 0), int(row.get("width", 0) or 0), int(row.get("height", 0) or 0)]
        except Exception:
            continue
        if bounds[2] <= 1 or bounds[3] <= 1:
            continue
        word = _region(text, bounds, image_size, screen_bounds, confidence=conf, backend="tesseract", kind="word")
        words.append(word)
        key = (str(row.get("block_num") or ""), str(row.get("par_num") or ""), str(row.get("line_num") or ""))
        lines.setdefault(key, []).append(word)
    line_regions = []
    for line_words in lines.values():
        merged = _merge_bounds(item.get("image_bounds") for item in line_words)
        text = " ".join(str(item.get("text") or "").strip() for item in sorted(line_words, key=lambda item: item.get("image_bounds", [0])[0]))
        if merged and text:
            confidence = sum(float(item.get("confidence", 0.0) or 0.0) for item in line_words) / max(1, len(line_words))
            line_regions.append(_region(text, merged, image_size, screen_bounds, confidence=confidence, backend="tesseract", kind="line"))
    return [item for item in line_regions + words if item.get("screen_bounds")]


def _extract_with_pytesseract(image_path: Path, image_size, screen_bounds) -> list[dict[str, Any]]:
    try:
        import pytesseract
        from pytesseract import Output
    except Exception:
        return []
    try:
        from PIL import Image

        image = Image.open(image_path)
        parameters = inspect.signature(pytesseract.image_to_data).parameters
        kwargs: dict[str, Any] = {"output_type": Output.DICT}
        if "timeout" in parameters or any(
            parameter.kind == inspect.Parameter.VAR_KEYWORD
            for parameter in parameters.values()
        ):
            kwargs["timeout"] = 4.0
        data = pytesseract.image_to_data(image, **kwargs)
    except Exception:
        return []
    rows = []
    count = len(data.get("text", []) or [])
    for index in range(count):
        rows.append(
            {
                "text": data.get("text", [""])[index],
                "conf": data.get("conf", [0])[index],
                "left": data.get("left", [0])[index],
                "top": data.get("top", [0])[index],
                "width": data.get("width", [0])[index],
                "height": data.get("height", [0])[index],
                "block_num": data.get("block_num", [""])[index],
                "par_num": data.get("par_num", [""])[index],
                "line_num": data.get("line_num", [""])[index],
            }
        )
    output = "\n".join(["text\tconf\tleft\ttop\twidth\theight\tblock_num\tpar_num\tline_num"] + [
        "\t".join(str(row.get(key, "")) for key in ("text", "conf", "left", "top", "width", "height", "block_num", "par_num", "line_num"))
        for row in rows
    ])
    return _parse_tesseract_tsv(output, image_size, screen_bounds)


def _extract_with_tesseract_exe(image_path: Path, image_size, screen_bounds) -> list[dict[str, Any]]:
    executable = shutil.which("tesseract")
    if not executable:
        return []
    try:
        result = subprocess.run(
            [executable, str(image_path), "stdout", "--psm", "6", "tsv"],
            capture_output=True,
            text=True,
            timeout=6,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except Exception:
        return []
    if result.returncode != 0 or not result.stdout:
        return []
    return _parse_tesseract_tsv(result.stdout, image_size, screen_bounds)


def _extract_text_regions_with_cv2(image_path: Path, image_size, screen_bounds, *, max_regions: int) -> list[dict[str, Any]]:
    try:
        import cv2
        import numpy as np
    except Exception:
        return []
    image = cv2.imread(str(image_path))
    if image is None:
        return []
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    variants = []
    for mode in (cv2.THRESH_BINARY, cv2.THRESH_BINARY_INV):
        try:
            _threshold, binary = cv2.threshold(gray, 0, 255, mode | cv2.THRESH_OTSU)
            variants.append(binary)
        except Exception:
            pass
    boxes = []
    for binary in variants:
        kernel_w = max(8, int(image.shape[1] / 90))
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (kernel_w, 3))
        connected = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel, iterations=1)
        contours, _hierarchy = cv2.findContours(connected, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for contour in contours:
            x, y, w, h = cv2.boundingRect(contour)
            area = int(w * h)
            if w < 14 or h < 6 or area < 80:
                continue
            if h > image.shape[0] * 0.18 or w > image.shape[1] * 0.92:
                continue
            density = float(np.count_nonzero(binary[y : y + h, x : x + w])) / max(1.0, float(area))
            if density < 0.035 or density > 0.88:
                continue
            boxes.append([int(x), int(y), int(w), int(h)])
    boxes = _merge_overlapping_boxes(boxes)
    boxes = sorted(boxes, key=lambda item: (item[1], item[0]))[:max_regions]
    return [
        _region("", bounds, image_size, screen_bounds, confidence=0.0, backend="opencv_text_regions", kind="text_region")
        for bounds in boxes
    ]


def _merge_overlapping_boxes(boxes) -> list[list[int]]:
    pending = [list(item) for item in boxes]
    changed = True
    while changed:
        changed = False
        merged = []
        used = [False] * len(pending)
        for index, left_box in enumerate(pending):
            if used[index]:
                continue
            current = list(left_box)
            used[index] = True
            for other_index, right_box in enumerate(pending):
                if used[other_index]:
                    continue
                if _boxes_touch(current, right_box):
                    current = _merge_bounds([current, right_box])
                    used[other_index] = True
                    changed = True
            merged.append(current)
        pending = merged
    return pending


def _boxes_touch(left, right) -> bool:
    lx, ly, lw, lh = [int(value) for value in left]
    rx, ry, rw, rh = [int(value) for value in right]
    pad_x = max(6, min(lw, rw) // 2)
    pad_y = max(3, min(lh, rh) // 2)
    return not (
        lx + lw + pad_x < rx
        or rx + rw + pad_x < lx
        or ly + lh + pad_y < ry
        or ry + rh + pad_y < ly
    )


def extract_snapshot_regions(image_path, *, screen_bounds=None, max_regions: int = 80) -> dict[str, Any]:
    path = Path(str(image_path or ""))
    if not path.exists():
        return {"regions": [], "text": "", "backend": "missing"}
    try:
        from PIL import Image

        with Image.open(path) as image:
            image_size = [int(image.width), int(image.height)]
    except Exception:
        return {"regions": [], "text": "", "backend": "unreadable"}
    bounds = list(screen_bounds or [0, 0, image_size[0], image_size[1]])
    regions = _extract_with_pytesseract(path, image_size, bounds)
    backend = "pytesseract"
    if not regions:
        regions = _extract_with_tesseract_exe(path, image_size, bounds)
        backend = "tesseract" if regions else backend
    if not regions:
        regions = _extract_with_win32_window_text(bounds, max_regions=max_regions)
        backend = "win32_window_text" if regions else backend
    if not regions:
        regions = _extract_text_regions_with_cv2(path, image_size, bounds, max_regions=max_regions)
        backend = "opencv_text_regions" if regions else "none"
    text = " ".join(item.get("text", "") for item in regions if item.get("text"))
    return {
        "regions": regions[:max_regions],
        "text": re.sub(r"\s+", " ", text).strip(),
        "backend": backend,
        "image_size": image_size,
        "screen_bounds": bounds,
    }


def write_sidecar(image_path, ocr_result: dict[str, Any]) -> str:
    path = Path(str(image_path or ""))
    if not path.exists():
        return ""
    sidecar = path.with_suffix(".ocr.json")
    try:
        sidecar.write_text(json.dumps(dict(ocr_result or {}), indent=2), encoding="utf-8")
        return str(sidecar)
    except Exception:
        return ""


def best_region_for_text(text, regions, *, fallback_bounds=None) -> dict[str, Any]:
    comment = _normalize_text(text)
    comment_tokens = _tokens(comment)
    best = None
    best_score = 0.0
    best_text_region = None
    best_text_region_area = 0.0
    for region in list(regions or []):
        bounds = region.get("screen_bounds") or []
        if not bounds:
            continue
        try:
            area = float(bounds[2]) * float(bounds[3])
        except Exception:
            area = 0.0
        if not region.get("text") and str(region.get("kind") or "") == "text_region" and area > best_text_region_area:
            best_text_region = dict(region)
            best_text_region_area = area
        region_text = _normalize_text(region.get("text", ""))
        score = 0.0
        if region_text:
            if region_text and region_text in comment:
                score += 12.0 + min(8.0, len(region_text) / 10.0)
            overlap = comment_tokens.intersection(_tokens(region_text))
            score += float(len(overlap)) * 4.0
            if comment and comment in region_text:
                score += 8.0
        else:
            score += 0.2
        score += min(2.0, area / 80000.0)
        if score > best_score:
            best = dict(region)
            best_score = score
    if best and best.get("text"):
        best["match_score"] = best_score
        return best
    if best_text_region and not fallback_bounds and not comment_tokens:
        best_text_region["match_score"] = best_text_region_area / 80000.0
        return best_text_region
    if fallback_bounds:
        return {
            "text": "",
            "normalized_text": "",
            "screen_bounds": list(fallback_bounds),
            "backend": "fallback",
            "kind": "fallback",
            "match_score": 0.0,
        }
    return {}
