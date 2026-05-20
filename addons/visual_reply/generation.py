from __future__ import annotations

import asyncio
import base64
import copy
import inspect
import io
import json
import os
import queue
import random
import threading
import time
import uuid
import urllib.parse
import urllib.request
from pathlib import Path

from openai import OpenAI
from PIL import Image, PngImagePlugin

from addons.visual_reply import runtime_config, state
from addons.visual_reply.providers import default_model_for_provider
from core import speech_text, text_tags


def output_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "runtime" / "visual_replies"


def api_key(runtime) -> str:
    return runtime.api_key()


def base_url(runtime) -> str:
    return runtime.base_url()


def provider(runtime) -> str:
    return runtime.provider()


def enabled(runtime) -> bool:
    return runtime.enabled()


def generation_available(runtime) -> bool:
    return runtime.generation_available()


def model_name(runtime) -> str:
    return runtime.model_name()


def image_size(runtime) -> str:
    return runtime.image_size()


def xai_extra_body(runtime) -> dict[str, str]:
    return runtime.xai_extra_body()


def apply_style_anchor(runtime, prompt_text: str) -> str:
    return runtime.apply_style_anchor(prompt_text)


def client(runtime):
    if runtime.provider() == "comfyui":
        return ComfyUIVisualReplyClient(runtime)
    if runtime.provider() == "runware":
        return RunwareVisualReplyClient(api_key=runtime.api_key())
    client_kwargs = {"api_key": runtime.api_key() or "visual-reply"}
    runtime_base_url = runtime.base_url()
    if runtime_base_url:
        client_kwargs["base_url"] = runtime_base_url
    return OpenAI(**client_kwargs)


def _sanitize_story_visual_text(text: str) -> str:
    return speech_text.sanitize_assistant_text_for_speech(
        text,
        preserve_emotion_tags=False,
        strip_visual_tail=runtime_config.strip_visual_reply_tail,
        visual_reply_tag_re=runtime_config.VISUAL_REPLY_TAG_RE,
        normalize_bracket_tag=text_tags.normalize_bracket_tag,
        is_sound_tag=text_tags.is_sound_tag,
        is_emotion_tag=lambda tag: text_tags.is_single_word_control_tag(tag) and not text_tags.is_sound_tag(tag),
    )


class VisualReplyGenerationService:
    def __init__(self, runtime, *, output_dir: Path):
        self.runtime = runtime
        self.output_dir = Path(output_dir)
        self._request_lock = threading.Lock()
        self._request_counter = 0
        self._story_queue = queue.Queue()
        self._story_queue_lock = threading.Lock()
        self._story_worker_started = False
        self._story_session_lock = threading.Lock()
        self._story_session_counter = 0
        self._story_active_session = 0

    def next_request_id(self):
        with self._request_lock:
            self._request_counter += 1
            return f"visual_{int(time.time())}_{self._request_counter}"

    def begin_story_session(self):
        with self._story_session_lock:
            self._story_session_counter += 1
            self._story_active_session = self._story_session_counter
            return self._story_active_session

    def clear_story_queue(self):
        try:
            while True:
                self._story_queue.get_nowait()
        except queue.Empty:
            pass

    def enqueue_story_generation(self, prompt: str, *, source_text: str = "", session_id: int | None = None, request_id: str | None = None):
        prompt_text = str(prompt or "").strip()
        if not prompt_text:
            return False
        if not self.runtime.story_mode_enabled() or not self.runtime.generation_available():
            return False
        self._ensure_story_worker()
        active_session = int(session_id or 0)
        if active_session <= 0:
            with self._story_session_lock:
                active_session = int(self._story_active_session or 0)
        if active_session <= 0:
            active_session = self.begin_story_session()
        self._story_queue.put(
            {
                "session_id": active_session,
                "prompt": prompt_text,
                "source_text": str(source_text or ""),
                "request_id": str(request_id or "").strip(),
            }
        )
        return True

    def _ensure_story_worker(self):
        if self._story_worker_started:
            return
        with self._story_queue_lock:
            if self._story_worker_started:
                return

            def _worker():
                while True:
                    item = self._story_queue.get()
                    if item is None:
                        continue
                    try:
                        session_id = int(item.get("session_id", 0) or 0)
                        with self._story_session_lock:
                            active_session = int(self._story_active_session or 0)
                        if session_id <= 0 or session_id != active_session:
                            continue
                        prompt_text = str(item.get("prompt", "") or "").strip()
                        if not prompt_text or not self.runtime.enabled() or not self.runtime.generation_available():
                            continue
                        request_id = str(item.get("request_id", "") or "").strip() or self.next_request_id()
                        self.perform_generation(
                            prompt_text,
                            source_text=str(item.get("source_text", "") or ""),
                            request_id=request_id,
                            keep_current_image=True,
                        )
                    except Exception as exc:
                        print(f"⚠️ [VisualReply] Story worker failed: {exc}")

            threading.Thread(target=_worker, daemon=True).start()
            self._story_worker_started = True

    def perform_generation(
        self,
        prompt_text: str,
        *,
        source_text: str = "",
        request_id: str | None = None,
        keep_current_image: bool = False,
    ):
        prompt_text = str(prompt_text or "").strip()
        if not prompt_text or not self.runtime.enabled():
            return False
        request_id = str(request_id or "").strip() or self.next_request_id()
        if not self.runtime.generation_available():
            if self.runtime.provider() == "comfyui":
                detail = "Set a ComfyUI server URL and workflow JSON path to enable ComfyUI visual replies."
            elif self.runtime.provider() == "xai":
                detail = "Set XAI_API_KEY (or NC_VISUAL_REPLY_XAI_API_KEY / NC_VISUAL_REPLY_XAI_BASE_URL) to enable Grok visual replies."
            elif self.runtime.provider() == "runware":
                detail = "Set RUNWARE_API_KEY (or NC_VISUAL_REPLY_RUNWARE_API_KEY) to enable Runware visual replies."
            else:
                detail = "Set OPENAI_API_KEY (or NC_VISUAL_REPLY_API_KEY / NC_VISUAL_REPLY_BASE_URL) to enable visual replies."
            state.set_current_visual_reply_data(
                {
                    "status": "error",
                    "status_text": "Visual Reply unavailable",
                    "detail_text": detail,
                    "image_path": "",
                    "caption": prompt_text,
                    "request_id": request_id,
                    "updated_at": time.time(),
                }
            )
            print(f"⚠️ [VisualReply] {detail}")
            return False

        current_state = dict(getattr(state, "current_visual_reply_data", {}) or {})
        current_image_path = str(current_state.get("image_path", "") or "").strip()
        preserve_visible_image = bool(keep_current_image and current_image_path)
        published_loading_state = False
        if not preserve_visible_image:
            state.set_current_visual_reply_data(
                {
                    "status": "loading",
                    "status_text": "Visual Reply generating...",
                    "detail_text": "Preparing story image..." if keep_current_image else prompt_text,
                    "image_path": "",
                    "caption": prompt_text,
                    "request_id": request_id,
                    "keep_current_image": bool(keep_current_image),
                    "updated_at": time.time(),
                }
            )
            published_loading_state = True
        print(f"🖼️ [VisualReply] Requested: {prompt_text}")

        try:
            client = self.runtime_client()
            request_kwargs = {
                "model": self.runtime.model_name(),
                "prompt": self.runtime.apply_style_anchor(prompt_text),
            }
            if self.runtime.provider() == "comfyui":
                request_kwargs["size"] = self.runtime.image_size()
                request_kwargs["negative_prompt"] = self.runtime.comfyui_negative_prompt()
            elif self.runtime.provider() == "xai":
                request_kwargs["response_format"] = "b64_json"
                request_kwargs["extra_body"] = self.runtime.xai_extra_body()
            elif self.runtime.provider() == "runware":
                request_kwargs["size"] = self.runtime.image_size()
                request_kwargs["response_format"] = "base64Data"
            else:
                request_kwargs["size"] = self.runtime.image_size()
            response = client.images.generate(**request_kwargs)
            output_path = self.write_image_from_response(response, self.output_dir / request_id)
            current_request_id = str(getattr(state, "current_visual_reply_data", {}).get("request_id", "") or "")
            if published_loading_state and current_request_id and current_request_id != request_id:
                return True
            state.set_current_visual_reply_data(
                {
                    "status": "ready",
                    "status_text": "Visual Reply",
                    "detail_text": source_text[:240],
                    "image_path": str(output_path),
                    "caption": prompt_text,
                    "request_id": request_id,
                    "updated_at": time.time(),
                }
            )
            print(f"🖼️ [VisualReply] Ready: {output_path}")
            return True
        except Exception as exc:
            current_request_id = str(getattr(state, "current_visual_reply_data", {}).get("request_id", "") or "")
            if published_loading_state and current_request_id and current_request_id != request_id:
                return False
            detail = str(exc) or repr(exc)
            state.set_current_visual_reply_data(
                {
                    "status": "error",
                    "status_text": "Visual Reply failed",
                    "detail_text": detail,
                    "image_path": "",
                    "caption": prompt_text,
                    "request_id": request_id,
                    "updated_at": time.time(),
                }
            )
            print(f"⚠️ [VisualReply] Generation failed: {detail}")
            return False

    def runtime_client(self):
        return client(self.runtime)

    def story_style_guide_from_text(self, story_text: str, continuity_strength: float = 0.8) -> str:
        story_prompt = _sanitize_story_visual_text(story_text)
        story_prompt = runtime_config.normalize_prompt_text(story_prompt)
        strength = max(0.0, min(1.0, float(continuity_strength or 0.0)))
        continuity_parts = []
        if strength >= 0.05:
            continuity_parts.append("Keep a consistent visual language across this entire story sequence.")
        if strength >= 0.2:
            continuity_parts.append("Treat recurring people and places as the same cast and world from image to image.")
        if strength >= 0.4:
            continuity_parts.append("Keep recurring characters with the same face, hair, body type, age, outfit silhouette, and key accessories unless the story explicitly changes them.")
        if strength >= 0.6:
            continuity_parts.append("Keep recurring locations recognizable with the same architecture, props, palette, weather, and lighting direction unless the story explicitly changes them.")
        if strength >= 0.8:
            continuity_parts.append("Do not redesign characters, reset outfits, or relocate scenes between shots unless the story explicitly says that a change happened.")
        if strength >= 0.95:
            continuity_parts.append("Use each new image like the next shot from the same film, preserving continuity as aggressively as possible.")
        continuity = " ".join(continuity_parts).strip()
        if not story_prompt:
            return continuity
        if len(story_prompt) > 420:
            story_prompt = story_prompt[:420].rstrip(" \t\r\n,;:.-")
        if not continuity:
            return f"Story context: {story_prompt}"
        return f"{continuity} Story context: {story_prompt}"

    def story_prompt_from_text(self, prompt_text: str, emotion: str = "", story_style_guide: str = "") -> str:
        prompt = _sanitize_story_visual_text(prompt_text)
        prompt = runtime_config.normalize_prompt_text(prompt)
        if not prompt:
            return ""
        prefix = "Story illustration"
        mood = str(emotion or "").strip().lower()
        if mood and mood != "neutral":
            prefix = f"{prefix}, {mood} mood"
        prompt = f"{prefix}: {prompt}"
        guide = str(story_style_guide or "").strip()
        if guide:
            prompt = f"{prompt}. {guide}"
        style_suffix = self.runtime.story_theme_suffix()
        if style_suffix:
            prompt = f"{prompt}. {style_suffix}"
        if len(prompt) > 760:
            prompt = prompt[:760].rstrip(" \t\r\n,;:.-")
        return prompt

    @staticmethod
    def item_value(item, key):
        if isinstance(item, dict):
            return item.get(key)
        return getattr(item, key, None)

    @staticmethod
    def image_format_and_extension(raw_bytes: bytes):
        try:
            with Image.open(io.BytesIO(raw_bytes)) as image:
                fmt = str(image.format or "").strip().lower()
        except Exception:
            fmt = ""
        extension = {
            "jpeg": "jpg",
            "jpg": "jpg",
            "png": "png",
            "webp": "webp",
            "bmp": "bmp",
        }.get(fmt, "png")
        return fmt, extension

    @classmethod
    def extension_for_bytes(cls, raw_bytes: bytes) -> str:
        _, extension = cls.image_format_and_extension(raw_bytes)
        return extension

    @staticmethod
    def write_caption_comment(image: Image.Image, output_path: Path, prompt_text: str, fmt: str):
        prompt = str(prompt_text or "").strip()
        save_kwargs = {}
        normalized_fmt = str(fmt or "").strip().lower()
        if normalized_fmt == "png":
            pnginfo = PngImagePlugin.PngInfo()
            if prompt:
                pnginfo.add_text("Comment", prompt)
            save_kwargs["pnginfo"] = pnginfo
            save_kwargs["format"] = "PNG"
        elif normalized_fmt in {"jpeg", "jpg"}:
            if image.mode not in {"RGB", "L"}:
                image = image.convert("RGB")
            if prompt:
                save_kwargs["comment"] = prompt.encode("utf-8", "replace")
            save_kwargs["format"] = "JPEG"
            save_kwargs["quality"] = 95
            save_kwargs["optimize"] = True
        elif normalized_fmt == "webp":
            save_kwargs["format"] = "WEBP"
            if prompt:
                save_kwargs["comment"] = prompt.encode("utf-8", "replace")
        elif normalized_fmt == "bmp":
            save_kwargs["format"] = "BMP"
        else:
            save_kwargs["format"] = image.format or "PNG"
        image.save(output_path, **save_kwargs)
        return output_path

    def write_image_from_response(self, response, output_base_path: Path):
        data_items = getattr(response, "data", None)
        if data_items is None and isinstance(response, dict):
            data_items = response.get("data")
        if not data_items:
            raise RuntimeError("Image API returned no image data.")
        first_item = data_items[0]
        b64_payload = (
            self.item_value(first_item, "b64_json")
            or self.item_value(first_item, "base64")
            or self.item_value(first_item, "imageBase64Data")
        )
        data_uri = self.item_value(first_item, "imageDataURI")
        image_url = self.item_value(first_item, "url") or self.item_value(first_item, "imageURL")
        prompt_text = ""
        try:
            prompt_text = str(getattr(state, "current_visual_reply_data", {}).get("caption", "") or "").strip()
        except Exception:
            prompt_text = ""
        output_base_path.parent.mkdir(parents=True, exist_ok=True)
        if data_uri and not b64_payload:
            data_uri_text = str(data_uri or "")
            if "," in data_uri_text:
                b64_payload = data_uri_text.split(",", 1)[1]
        if b64_payload:
            raw_bytes = base64.b64decode(b64_payload)
            fmt, extension = self.image_format_and_extension(raw_bytes)
            output_path = output_base_path.with_suffix(f".{extension}")
            with Image.open(io.BytesIO(raw_bytes)) as image:
                image.load()
                self.write_caption_comment(image, output_path, prompt_text, fmt)
            return output_path
        if image_url:
            with urllib.request.urlopen(str(image_url)) as response_stream:
                raw_bytes = response_stream.read()
            fmt, extension = self.image_format_and_extension(raw_bytes)
            output_path = output_base_path.with_suffix(f".{extension}")
            with Image.open(io.BytesIO(raw_bytes)) as image:
                image.load()
                self.write_caption_comment(image, output_path, prompt_text, fmt)
            return output_path
        raise RuntimeError("Image API response did not include b64_json or url.")


def _parse_size(size_text: str) -> tuple[int, int]:
    size = str(size_text or "1024x1024").strip().lower().replace(" ", "")
    if size == "auto":
        size = "1024x1024"
    if "x" not in size:
        return 1024, 1024
    left, right = size.split("x", 1)
    try:
        width = max(64, int(left))
        height = max(64, int(right))
    except Exception:
        return 1024, 1024
    return width, height


def _run_async_blocking(coro):
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    result = {}

    def _runner():
        try:
            result["value"] = asyncio.run(coro)
        except BaseException as exc:
            result["error"] = exc

    worker = threading.Thread(target=_runner, daemon=True)
    worker.start()
    worker.join()
    if "error" in result:
        raise result["error"]
    return result.get("value")


class _RunwareImages:
    def __init__(self, owner):
        self._owner = owner

    def generate(self, **kwargs):
        return self._owner.generate(**kwargs)


def _runware_image_value(image, key: str):
    value = getattr(image, key, None)
    if value is None and isinstance(image, dict):
        value = image.get(key)
    return value


class RunwareVisualReplyClient:
    def __init__(self, *, api_key: str):
        self.api_key = str(api_key or "").strip()
        self.images = _RunwareImages(self)

    def generate(self, **kwargs):
        if not self.api_key:
            raise RuntimeError("Set RUNWARE_API_KEY or NC_VISUAL_REPLY_RUNWARE_API_KEY to enable Runware visual replies.")
        try:
            from runware import IImageInference, Runware
        except Exception as exc:
            raise RuntimeError("Install the runware Python package to enable Runware visual replies.") from exc

        prompt = str(kwargs.get("prompt") or "").strip()
        if not prompt:
            raise RuntimeError("Runware image generation requires a prompt.")
        width, height = _parse_size(str(kwargs.get("size") or "1024x1024"))
        runware_default_model = default_model_for_provider("runware")
        model = str(kwargs.get("model") or runware_default_model).strip() or runware_default_model

        async def _generate():
            runware = Runware(api_key=self.api_key)
            await runware.connect()
            try:
                request = IImageInference(
                    positivePrompt=prompt,
                    model=model,
                    width=width,
                    height=height,
                    outputType="base64Data",
                    outputFormat="PNG",
                    numberResults=1,
                    includeCost=True,
                )
                return await runware.imageInference(requestImage=request)
            finally:
                disconnect = getattr(runware, "disconnect", None)
                if callable(disconnect):
                    disconnect_result = disconnect()
                    if inspect.isawaitable(disconnect_result):
                        await disconnect_result

        images = _run_async_blocking(_generate()) or []
        data = []
        for image in images:
            data.append(
                {
                    "b64_json": _runware_image_value(image, "imageBase64Data"),
                    "url": _runware_image_value(image, "imageURL"),
                    "cost": _runware_image_value(image, "cost"),
                }
            )
        return {"data": data}


def _json_request(url: str, *, method: str = "GET", payload: dict | None = None, timeout: float = 30.0):
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(str(url), data=data, headers=headers, method=method)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read()
    if not raw:
        return {}
    return json.loads(raw.decode("utf-8", "replace"))


def _read_binary_url(url: str, *, timeout: float = 30.0) -> bytes:
    with urllib.request.urlopen(str(url), timeout=timeout) as response:
        return response.read()


def _normalize_comfyui_base_url(value: str) -> str:
    text = str(value or "").strip() or "http://127.0.0.1:8188"
    text = text.rstrip("/")
    if not text.lower().startswith(("http://", "https://")):
        text = f"http://{text}"
    return text


def _candidate_comfyui_roots() -> list[Path]:
    roots = []
    for env_name in ("NC_COMFYUI_ROOT", "COMFYUI_ROOT", "COMFYUI_PATH"):
        value = str(os.environ.get(env_name, "") or "").strip()
        if value:
            roots.append(Path(value))
    roots.extend(
        [
            Path.cwd(),
            Path(__file__).resolve().parents[2],
            Path("D:/tools/ComfyUI"),
            Path("H:/ComfyUI"),
            Path("C:/ComfyUI"),
            Path("/mnt/d/tools/ComfyUI"),
            Path("/mnt/h/ComfyUI"),
        ]
    )
    seen = set()
    result = []
    for root in roots:
        key = str(root)
        if key in seen:
            continue
        seen.add(key)
        result.append(root)
    return result


def _resolve_comfyui_workflow_path(path_text: str) -> Path:
    raw = str(path_text or "").strip().strip('"')
    if not raw:
        raise RuntimeError("ComfyUI workflow path is empty.")
    expanded = os.path.expandvars(os.path.expanduser(raw))
    path = Path(expanded)
    if path.is_file():
        return path
    if not path.is_absolute():
        for root in _candidate_comfyui_roots():
            candidate = root / expanded
            if candidate.is_file():
                return candidate
    raise RuntimeError(f"ComfyUI workflow JSON was not found: {raw}")


def _parse_workflow_json(path: Path) -> dict:
    try:
        with Path(path).open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except Exception as exc:
        raise RuntimeError(f"Could not read ComfyUI workflow JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("ComfyUI workflow JSON must be an object.")
    return payload


def _widget_input_names(node: dict) -> list[str]:
    names = []
    for item in list(node.get("inputs") or []):
        if not isinstance(item, dict):
            continue
        if item.get("link") is not None:
            continue
        widget = item.get("widget")
        if isinstance(widget, dict) and str(widget.get("name") or "").strip():
            names.append(str(widget.get("name")).strip())
    return names


def _widget_values_for_names(node: dict, names: list[str]) -> list:
    values = list(node.get("widgets_values") or [])
    if not values:
        return []
    if "seed" in names and len(values) == len(names) + 1:
        maybe_control = str(values[1] or "").strip().lower() if len(values) > 1 else ""
        if maybe_control in {"fixed", "randomize", "increment", "decrement"}:
            values = [values[0], *values[2:]]
    return values


def _convert_comfyui_ui_workflow(payload: dict) -> dict:
    nodes = payload.get("nodes")
    links = payload.get("links")
    if not isinstance(nodes, list) or not isinstance(links, list):
        return payload

    link_map = {}
    for link in links:
        if not isinstance(link, list) or len(link) < 5:
            continue
        try:
            link_id = int(link[0])
            source_node = str(link[1])
            source_slot = int(link[2])
        except Exception:
            continue
        link_map[link_id] = [source_node, source_slot]

    api = {}
    for node in nodes:
        if not isinstance(node, dict):
            continue
        node_id = str(node.get("id") or "").strip()
        class_type = str(node.get("type") or "").strip()
        if not node_id or not class_type:
            continue
        inputs = {}
        for item in list(node.get("inputs") or []):
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            if not name:
                continue
            link_id = item.get("link")
            if link_id is not None:
                try:
                    link_key = int(link_id)
                except Exception:
                    link_key = None
                if link_key in link_map:
                    inputs[name] = list(link_map[link_key])
        widget_names = _widget_input_names(node)
        widget_values = _widget_values_for_names(node, widget_names)
        for index, name in enumerate(widget_names):
            if index < len(widget_values):
                inputs[name] = widget_values[index]
        api[node_id] = {
            "class_type": class_type,
            "inputs": inputs,
        }
    if not api:
        raise RuntimeError("ComfyUI UI workflow did not contain any usable nodes.")
    return api


def _is_api_workflow(payload: dict) -> bool:
    if not payload:
        return False
    for value in payload.values():
        if not isinstance(value, dict) or "class_type" not in value:
            return False
    return True


def _as_comfyui_api_workflow(payload: dict) -> dict:
    if _is_api_workflow(payload):
        return copy.deepcopy(payload)
    return _convert_comfyui_ui_workflow(payload)


def _parse_size_for_comfyui(size_text: str) -> tuple[int, int]:
    width, height = _parse_size(size_text)
    return int(width), int(height)


def _first_node_id_by_class(workflow: dict, class_names: set[str]) -> str:
    for node_id, node in workflow.items():
        class_type = str((node or {}).get("class_type") or "")
        if class_type in class_names:
            return str(node_id)
    return ""


def _first_node_id_containing(workflow: dict, needle: str) -> str:
    needle = str(needle or "").lower()
    for node_id, node in workflow.items():
        class_type = str((node or {}).get("class_type") or "").lower()
        if needle and needle in class_type:
            return str(node_id)
    return ""


def _linked_node_id(workflow: dict, node_id: str, input_name: str) -> str:
    node = workflow.get(str(node_id), {})
    value = dict(node.get("inputs") or {}).get(str(input_name))
    if isinstance(value, (list, tuple)) and value:
        return str(value[0])
    return ""


def _set_node_input(workflow: dict, node_id: str, input_name: str, value) -> bool:
    node = workflow.get(str(node_id))
    if not isinstance(node, dict):
        return False
    inputs = node.setdefault("inputs", {})
    if not isinstance(inputs, dict):
        inputs = {}
        node["inputs"] = inputs
    inputs[str(input_name)] = value
    return True


def _find_comfyui_prompt_nodes(workflow: dict) -> tuple[str, str, str, str]:
    ksampler_id = _first_node_id_by_class(workflow, {"KSampler", "KSamplerAdvanced"}) or _first_node_id_containing(workflow, "ksampler")
    positive_id = _linked_node_id(workflow, ksampler_id, "positive") if ksampler_id else ""
    negative_id = _linked_node_id(workflow, ksampler_id, "negative") if ksampler_id else ""
    latent_id = _linked_node_id(workflow, ksampler_id, "latent_image") if ksampler_id else ""
    if not positive_id:
        clip_nodes = [
            str(node_id)
            for node_id, node in workflow.items()
            if str((node or {}).get("class_type") or "") == "CLIPTextEncode"
        ]
        positive_id = clip_nodes[0] if clip_nodes else ""
        negative_id = negative_id or (clip_nodes[1] if len(clip_nodes) > 1 else "")
    if not latent_id:
        latent_id = _first_node_id_by_class(workflow, {"EmptyLatentImage"})
    return ksampler_id, positive_id, negative_id, latent_id


def _inject_comfyui_inputs(workflow: dict, *, prompt: str, negative_prompt: str, size: str, filename_prefix: str):
    ksampler_id, positive_id, negative_id, latent_id = _find_comfyui_prompt_nodes(workflow)
    if not positive_id:
        raise RuntimeError("Could not find a positive prompt node in the ComfyUI workflow.")
    _set_node_input(workflow, positive_id, "text", prompt)
    if negative_prompt and negative_id:
        _set_node_input(workflow, negative_id, "text", negative_prompt)
    width, height = _parse_size_for_comfyui(size)
    if latent_id:
        _set_node_input(workflow, latent_id, "width", width)
        _set_node_input(workflow, latent_id, "height", height)
        _set_node_input(workflow, latent_id, "batch_size", 1)
    if ksampler_id and "seed" in dict(workflow.get(ksampler_id, {}).get("inputs") or {}):
        _set_node_input(workflow, ksampler_id, "seed", random.randint(0, 2**63 - 1))
    save_id = _first_node_id_by_class(workflow, {"SaveImage"})
    if save_id:
        _set_node_input(workflow, save_id, "filename_prefix", filename_prefix)
    return workflow


def _history_images(history_payload: dict, prompt_id: str) -> list[dict]:
    prompt_data = history_payload.get(prompt_id) if isinstance(history_payload, dict) else None
    if not isinstance(prompt_data, dict):
        prompt_data = history_payload if isinstance(history_payload, dict) else {}
    outputs = prompt_data.get("outputs", {})
    images = []
    if isinstance(outputs, dict):
        for output in outputs.values():
            if not isinstance(output, dict):
                continue
            for image in list(output.get("images") or []):
                if isinstance(image, dict):
                    images.append(image)
    return images


class ComfyUIVisualReplyClient:
    def __init__(self, runtime):
        self.runtime = runtime
        self.images = _RunwareImages(self)
        self.client_id = uuid.uuid4().hex

    def _workflow(self) -> dict:
        path = _resolve_comfyui_workflow_path(self.runtime.workflow_path())
        payload = _parse_workflow_json(path)
        return _as_comfyui_api_workflow(payload)

    def _queue_prompt(self, workflow: dict, *, timeout: float) -> str:
        base_url = _normalize_comfyui_base_url(self.runtime.base_url())
        response = _json_request(
            f"{base_url}/prompt",
            method="POST",
            payload={"prompt": workflow, "client_id": self.client_id},
            timeout=min(30.0, max(5.0, timeout)),
        )
        node_errors = response.get("node_errors")
        if node_errors:
            raise RuntimeError(f"ComfyUI rejected the workflow: {node_errors}")
        prompt_id = str(response.get("prompt_id") or "").strip()
        if not prompt_id:
            raise RuntimeError(f"ComfyUI did not return a prompt_id: {response}")
        return prompt_id

    def _wait_for_image(self, prompt_id: str, *, timeout: float) -> bytes:
        base_url = _normalize_comfyui_base_url(self.runtime.base_url())
        deadline = time.time() + max(5.0, float(timeout or 180.0))
        last_error = ""
        while time.time() < deadline:
            try:
                history = _json_request(f"{base_url}/history/{urllib.parse.quote(prompt_id)}", timeout=10.0)
                images = _history_images(history, prompt_id)
                if images:
                    image = images[-1]
                    query = urllib.parse.urlencode(
                        {
                            "filename": str(image.get("filename") or ""),
                            "subfolder": str(image.get("subfolder") or ""),
                            "type": str(image.get("type") or "output"),
                        }
                    )
                    return _read_binary_url(f"{base_url}/view?{query}", timeout=30.0)
            except Exception as exc:
                last_error = str(exc) or repr(exc)
            time.sleep(0.8)
        raise RuntimeError(f"Timed out waiting for ComfyUI image output.{(' Last error: ' + last_error) if last_error else ''}")

    def _request_cleanup(self):
        mode = str(getattr(self.runtime, "comfyui_cleanup_mode", lambda: "keep_cache")() or "keep_cache").strip().lower()
        if mode == "keep_cache":
            return
        payload = {}
        if mode == "free_memory":
            payload = {"free_memory": True}
        elif mode == "unload_models":
            payload = {"unload_models": True, "free_memory": True}
        if not payload:
            return
        base_url = _normalize_comfyui_base_url(self.runtime.base_url())
        try:
            _json_request(f"{base_url}/free", method="POST", payload=payload, timeout=10.0)
            print(f"🧹 [VisualReply] Requested ComfyUI cleanup: {mode}")
        except Exception as exc:
            print(f"⚠️ [VisualReply] ComfyUI cleanup request failed: {exc}")

    def generate(self, **kwargs):
        prompt = str(kwargs.get("prompt") or "").strip()
        if not prompt:
            raise RuntimeError("ComfyUI image generation requires a prompt.")
        timeout = self.runtime.comfyui_timeout_seconds()
        workflow = self._workflow()
        workflow = _inject_comfyui_inputs(
            workflow,
            prompt=prompt,
            negative_prompt=str(kwargs.get("negative_prompt") or ""),
            size=str(kwargs.get("size") or "1024x1024"),
            filename_prefix="NeuralCompanion",
        )
        prompt_id = self._queue_prompt(workflow, timeout=timeout)
        raw_bytes = self._wait_for_image(prompt_id, timeout=timeout)
        self._request_cleanup()
        return {"data": [{"b64_json": base64.b64encode(raw_bytes).decode("ascii")}]}
