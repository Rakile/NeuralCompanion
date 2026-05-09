from __future__ import annotations

import base64
import io
import queue
import threading
import time
import urllib.request
from pathlib import Path

from openai import OpenAI
from PIL import Image, PngImagePlugin

from addons.visual_reply import runtime_config, state
from core import speech_text


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
            client_kwargs = {"api_key": self.runtime.api_key() or "visual-reply"}
            base_url = self.runtime.base_url()
            if base_url:
                client_kwargs["base_url"] = base_url
            client = OpenAI(**client_kwargs)
            request_kwargs = {
                "model": self.runtime.model_name(),
                "prompt": self.runtime.apply_style_anchor(prompt_text),
            }
            if self.runtime.provider() == "xai":
                request_kwargs["response_format"] = "b64_json"
                request_kwargs["extra_body"] = self.runtime.xai_extra_body()
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

    def story_style_guide_from_text(self, story_text: str, continuity_strength: float = 0.8) -> str:
        story_prompt = speech_text.sanitize_assistant_text_for_speech(story_text, preserve_emotion_tags=False)
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
        prompt = speech_text.sanitize_assistant_text_for_speech(prompt_text, preserve_emotion_tags=False)
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
        b64_payload = self.item_value(first_item, "b64_json") or self.item_value(first_item, "base64")
        image_url = self.item_value(first_item, "url")
        prompt_text = ""
        try:
            prompt_text = str(getattr(state, "current_visual_reply_data", {}).get("caption", "") or "").strip()
        except Exception:
            prompt_text = ""
        output_base_path.parent.mkdir(parents=True, exist_ok=True)
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
