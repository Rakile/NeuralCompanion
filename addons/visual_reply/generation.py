from __future__ import annotations

import asyncio
import base64
import inspect
import io
import queue
import threading
import time
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
            if self.runtime.provider() == "xai":
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
            if self.runtime.provider() == "xai":
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
