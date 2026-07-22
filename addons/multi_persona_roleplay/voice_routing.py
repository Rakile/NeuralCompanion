from __future__ import annotations

import json
import queue
import re
import threading
import time
from pathlib import Path
from typing import Any

from .models import AR_MODE, PersonaConfig, RoleplaySessionState, normalize_persona_id


VOICE_REFERENCE_BACKENDS = {"chatterbox", "chatterbox_multilingual", "pockettts", "pockettts_multilingual"}


def normalize_tts_backend(value: Any) -> str:
    text = str(value or "").strip().lower().replace("-", "_")
    aliases = {
        "pocket_tts": "pockettts",
        "pockettts_multilingual_tts": "pockettts_multilingual",
        "chatterbox_tts": "chatterbox",
        "chatterbox_multilingual_tts": "chatterbox_multilingual",
    }
    return aliases.get(text, text)


class PersonaVoiceRouter:
    def __init__(self, controller):
        self.controller = controller
        self._last_warning = ""
        self._pending_story_audio_cues: list[str] = []
        self._ar_stream_speaker_id = ""
        self._ar_stream_speaker_by_key: dict[str, str] = {}
        self._ar_stream_speaker_at_by_key: dict[str, float] = {}
        self._voice_route_debug_queue: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=128)
        self._voice_route_debug_thread_lock = threading.Lock()
        self._voice_route_debug_thread: threading.Thread | None = None

    def _voice_volume_percent(self) -> int:
        getter = getattr(self.controller, "mprc_voice_volume_percent", None)
        if callable(getter):
            try:
                return max(0, min(100, int(getter())))
            except Exception:
                return 100
        settings = getattr(self.controller, "settings", {})
        try:
            return max(0, min(100, int(settings.get("mprc_voice_volume", 100))))
        except Exception:
            return 100

    def effective_voice_config(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = dict(payload or {})
        controller = self.controller
        session: RoleplaySessionState = controller.session
        route_reason_override = str(payload.get("_route_reason_override") or "").strip()
        persona = self.persona_for_payload(payload)
        active_backend = normalize_tts_backend(payload.get("tts_backend") or controller.current_tts_backend())
        volume_percent = self._voice_volume_percent()
        result = {
            "enabled": False,
            "persona_id": getattr(persona, "id", ""),
            "display_name": getattr(persona, "display_name", ""),
            "backend": active_backend,
            "sample_path": "",
            "language": "",
            "volume": volume_percent / 100.0,
            "volume_percent": volume_percent,
            "supported": False,
            "warning": "",
            "route_reason": route_reason_override or str(payload.get("_route_reason") or ""),
        }
        if persona is None or not session.enabled:
            return result
        voice = persona.voice
        if not voice.enabled:
            return result
        requested_backend = normalize_tts_backend(voice.backend)
        effective_backend = active_backend if requested_backend in {"", "inherit"} else requested_backend
        result["enabled"] = True
        result["backend"] = effective_backend
        result["language"] = str(voice.language or "").strip().lower()
        if effective_backend != active_backend:
            result["warning"] = (
                f"{persona.display_name} is configured for {effective_backend}, but the active NC TTS backend "
                f"is {active_backend or 'unknown'}. Keeping the active backend."
            )
            result["backend"] = active_backend
            return self._warn_once(result)
        if active_backend not in VOICE_REFERENCE_BACKENDS:
            result["warning"] = f"The active TTS backend '{active_backend or 'unknown'}' does not support voice samples."
            return self._warn_once(result)
        sample_path = str(voice.sample_path or "").strip()
        if not sample_path:
            result["warning"] = f"{persona.display_name} voice is enabled, but no voice sample path is set."
            return self._warn_once(result)
        resolved = self._resolve_sample_path(sample_path)
        if not resolved:
            result["warning"] = f"Voice sample not found for {persona.display_name}: {sample_path}"
            return self._warn_once(result)
        result["sample_path"] = resolved
        result["supported"] = True
        result["warning"] = ""
        return result

    def persona_for_payload(self, payload: dict[str, Any] | None = None) -> PersonaConfig | None:
        payload = payload if isinstance(payload, dict) else dict(payload or {})
        session: RoleplaySessionState = self.controller.session
        explicit = (
            payload.get("persona_id")
            or payload.get("speaker_id")
            or payload.get("current_speaker_id")
            or ""
        )
        persona = self._resolve_persona(explicit)
        if persona is not None:
            payload["_route_reason"] = "explicit_persona"
            return persona

        speaker = self.detect_speaker(str(payload.get("text") or ""))
        if speaker is not None:
            payload["_route_reason"] = "text_speaker_label"
            return speaker

        if self._is_alternative_reality():
            streaming_persona = self._ar_stream_persona(payload)
            if streaming_persona is not None:
                payload["_route_reason"] = "ar_stream_speaker"
                return streaming_persona
            persona = self._narrator_persona()
            if persona is not None:
                payload["_route_reason"] = "ar_narrator_default"
                return persona

        if session.mode != "Single active persona":
            persona = self._resolve_persona(session.current_speaker_id)
            if persona is not None:
                payload["_route_reason"] = "current_speaker"
                return persona

        payload["_route_reason"] = "active_persona"
        return self.controller.active_persona()

    def split_text_by_persona(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = dict(payload or {})
        text = str(payload.get("text") or "")
        previous_debug_events = getattr(self, "_voice_route_debug_events", None)
        self._voice_route_debug_events = []

        def finish(result: dict[str, Any]) -> dict[str, Any]:
            try:
                self._write_voice_route_debug(payload, text, result, list(getattr(self, "_voice_route_debug_events", []) or []))
            finally:
                self._voice_route_debug_events = previous_debug_events
            return result

        self._voice_route_debug(
            "start",
            streaming=bool(payload.get("streaming", False)),
            stream_start=bool(payload.get("stream_start", False)),
            stream_source_index=payload.get("stream_source_index", ""),
            stream_key=self._ar_stream_key(payload) if bool(payload.get("streaming", False)) else "",
            enabled=bool(self.controller.session.enabled),
            mode=str(getattr(self.controller.session, "mode", "") or ""),
            text_excerpt=self._voice_route_log_excerpt(text),
        )
        if not text.strip():
            return finish({"segments": []})
        if not self.controller.session.enabled:
            text, audio_changed, story_audio_cues = self.controller.strip_story_audio_for_tts(
                text,
                streaming=bool(payload.get("streaming", False)),
                collect_cues=True,
            )
            if not text.strip():
                return finish({"segments": [], "suppress_original": bool(audio_changed)})
            if audio_changed:
                return finish({
                    "segments": [{"text": text, "story_audio_cues": list(story_audio_cues or [])}],
                    "suppress_original": True,
                })
            return finish({"segments": []})
        text, audio_changed = self._prepare_story_audio_text_for_routing(
            text,
            streaming=bool(payload.get("streaming", False)),
        )
        if not text.strip():
            return finish({"segments": [], "suppress_original": bool(audio_changed)})
        streaming = bool(payload.get("streaming", False))
        stream_start = bool(payload.get("stream_start", False))
        if self._is_alternative_reality():
            if streaming:
                if stream_start or self._stream_source_index_is_start(payload):
                    self._set_ar_stream_speaker(payload, "")
                else:
                    self._expire_stale_ar_stream_speaker(payload)
            text = self._strip_assistant_prefix_before_ar_tag(text)
            text = self._normalize_ar_story_tags(text)
        explicit_persona = self._explicit_persona_for_payload(payload)
        if explicit_persona is not None:
            segment_text = self._strip_known_speaker_labels_for_explicit_route(text)
            if not segment_text.strip():
                return finish({"segments": [], "suppress_original": bool(audio_changed)})
            route_payload = dict(payload)
            route_payload["text"] = segment_text
            route_payload["persona_id"] = explicit_persona.id
            route_payload["_route_reason_override"] = "explicit_persona"
            route = self.effective_voice_config(route_payload)
            if self._is_alternative_reality() and streaming:
                self._set_ar_stream_speaker(payload, explicit_persona.id)
            return finish(
                {
                    "segments": [
                        {
                            "text": segment_text,
                            "persona_id": explicit_persona.id,
                            "display_name": explicit_persona.display_name,
                            "voice_path": str(route.get("sample_path") or "") if route.get("supported") else "",
                            "voice_volume": route.get("volume", 1.0),
                            "voice_volume_percent": route.get("volume_percent", 100),
                            "voice_route": route,
                            "story_audio_cues": self._consume_pending_story_audio_cues(),
                        }
                    ],
                    "suppress_original": True,
                }
            )
        creator = getattr(self.controller, "ensure_personas_from_assistant_text", None)
        if callable(creator):
            try:
                creator(text, source="voice_route")
            except Exception as exc:
                logger = getattr(self.controller.context, "logger", None)
                if logger is not None:
                    logger.warning("[MPRC] Auto persona creation during voice routing failed: %s", exc)

        default_payload = {key: value for key, value in payload.items() if key != "text"}
        if self._is_alternative_reality():
            stream_persona = self._ar_stream_persona(payload)
            narrator_persona = self._narrator_persona()
            default_persona = stream_persona or narrator_persona or self.persona_for_payload(default_payload)
            if stream_persona is not None:
                default_reason = "ar_stream_speaker"
            elif narrator_persona is not None:
                default_reason = "ar_narrator_default"
            else:
                default_reason = str(default_payload.get("_route_reason") or "active_persona")
        else:
            default_persona = self.persona_for_payload(default_payload)
            default_reason = str(default_payload.get("_route_reason") or "current_speaker")
        current_persona = default_persona
        current_reason = default_reason
        segments: list[dict[str, Any]] = []
        current_lines: list[str] = []
        saw_label = False

        def append_segment(persona: PersonaConfig, segment_text: str, *, route_reason: str = "", story_cues: list[str] | None = None) -> None:
            segment_text = str(segment_text or "").strip()
            if not segment_text:
                return
            route_payload = dict(payload)
            route_payload["text"] = segment_text
            route_payload["persona_id"] = persona.id
            if route_reason:
                route_payload["_route_reason_override"] = route_reason
            route = self.effective_voice_config(route_payload)
            self._voice_route_debug(
                "append_segment",
                persona_id=persona.id,
                display_name=persona.display_name,
                text_excerpt=self._voice_route_log_excerpt(segment_text),
                voice_supported=bool(route.get("supported")),
                voice_path=Path(str(route.get("sample_path") or "")).name if route.get("sample_path") else "",
                route_reason=str(route.get("route_reason") or ""),
                warning=str(route.get("warning") or ""),
            )
            if self._is_alternative_reality() and bool(payload.get("streaming", False)):
                self._set_ar_stream_speaker(payload, persona.id)
            segments.append(
                {
                    "text": segment_text,
                    "persona_id": persona.id,
                    "display_name": persona.display_name,
                    "voice_path": str(route.get("sample_path") or "") if route.get("supported") else "",
                    "voice_volume": route.get("volume", 1.0),
                    "voice_volume_percent": route.get("volume_percent", 100),
                    "voice_route": route,
                    "story_audio_cues": list(story_cues or []),
                }
            )

        def flush() -> None:
            nonlocal current_lines, current_persona, current_reason
            segment_text = "\n".join(current_lines).strip()
            current_lines = []
            if not segment_text:
                return
            persona = current_persona or default_persona or self.controller.active_persona()
            if persona is None:
                return
            story_cues = self._consume_pending_story_audio_cues()
            explicit_speaker_label = bool(current_reason == "text_speaker_label")
            split_fragments = self._split_ar_character_dialogue(
                segment_text,
                persona,
                explicit_speaker_label=explicit_speaker_label,
            )
            self._voice_route_debug(
                "flush",
                base_persona_id=persona.id,
                text_excerpt=self._voice_route_log_excerpt(segment_text),
                split_fragments=len(split_fragments or []),
            )
            if split_fragments:
                for index, (fragment_persona, fragment_text) in enumerate(split_fragments):
                    fragment_reason = current_reason if fragment_persona.id == persona.id else "text_speaker_label"
                    append_segment(fragment_persona, fragment_text, route_reason=fragment_reason, story_cues=story_cues if index == 0 else [])
                return
            append_segment(persona, segment_text, route_reason=current_reason, story_cues=story_cues)

        for raw_line in text.splitlines():
            audio_body = self._handle_story_audio_line(raw_line, current_lines=current_lines, flush=flush)
            if audio_body is not None:
                audio_changed = True
                if audio_body.strip():
                    raw_line = audio_body
                else:
                    continue
            speaker, body, matched = self._split_speaker_prefix(raw_line)
            if matched:
                flush()
                saw_label = True
                if speaker is not None:
                    self._voice_route_debug(
                        "speaker_label",
                        label_excerpt=self._voice_route_log_excerpt(raw_line),
                        speaker_id=speaker.id,
                        display_name=speaker.display_name,
                    )
                    current_persona = speaker
                    current_reason = "text_speaker_label"
                    self.controller.session.current_speaker_id = speaker.id
                    if self._is_alternative_reality():
                        self._set_ar_stream_speaker(payload, speaker.id)
                else:
                    self._voice_route_debug("unresolved_speaker_label", label_excerpt=self._voice_route_log_excerpt(raw_line))
                    narrator_fallback = self._narrator_persona() if self._is_alternative_reality() else None
                    current_persona = narrator_fallback or default_persona or self.controller.active_persona()
                    current_reason = "ar_narrator_default" if narrator_fallback is not None else default_reason
                    if self._is_alternative_reality():
                        self._set_ar_stream_speaker(payload, getattr(current_persona, "id", ""))
                    self._warn_unresolved_speaker(raw_line)
                if body.strip():
                    current_lines.append(body)
                continue
            current_lines.append(raw_line)
        flush()

        if not saw_label:
            if segments:
                return finish({"segments": segments, "suppress_original": True})
            if self._is_alternative_reality():
                persona = default_persona or self.controller.active_persona()
                if persona is None:
                    return finish({"segments": [], "suppress_original": bool(audio_changed)})
                route_payload = dict(payload)
                route_payload["text"] = text
                route_payload["persona_id"] = persona.id
                route_payload["_route_reason_override"] = default_reason
                route = self.effective_voice_config(route_payload)
                return finish({
                    "segments": [
                        {
                            "text": text,
                            "persona_id": persona.id,
                            "display_name": persona.display_name,
                            "voice_path": str(route.get("sample_path") or "") if route.get("supported") else "",
                            "voice_volume": route.get("volume", 1.0),
                            "voice_volume_percent": route.get("volume_percent", 100),
                            "voice_route": route,
                            "story_audio_cues": self._consume_pending_story_audio_cues(),
                        }
                    ],
                    "suppress_original": True,
                })
            if audio_changed and segments:
                return finish({"segments": segments, "suppress_original": True})
            if audio_changed:
                persona = default_persona or self.controller.active_persona()
                if persona is None:
                    return finish({"segments": [], "suppress_original": True})
                route_payload = dict(payload)
                route_payload["text"] = text
                route_payload["persona_id"] = persona.id
                route_payload["_route_reason_override"] = default_reason
                route = self.effective_voice_config(route_payload)
                return finish({
                    "segments": [
                        {
                            "text": text,
                            "persona_id": persona.id,
                            "display_name": persona.display_name,
                            "voice_path": str(route.get("sample_path") or "") if route.get("supported") else "",
                            "voice_volume": route.get("volume", 1.0),
                            "voice_volume_percent": route.get("volume_percent", 100),
                            "voice_route": route,
                            "story_audio_cues": self._consume_pending_story_audio_cues(),
                        }
                    ],
                    "suppress_original": True,
                })
            return finish({"segments": [], "suppress_original": False})
        return finish({"segments": segments, "suppress_original": True})

    def _prepare_story_audio_text_for_routing(self, text: str, *, streaming: bool) -> tuple[str, bool]:
        value = str(text or "")
        changed = False
        if streaming:
            value = str(getattr(self.controller, "_story_audio_pending_text", "") or "") + value
            self.controller._story_audio_pending_text = ""
            splitter = getattr(self.controller, "_split_pending_story_audio_tag", None)
            if callable(splitter):
                value, pending = splitter(value)
                if pending:
                    self.controller._story_audio_pending_text = pending
                    changed = True
                    if not value.strip():
                        return "", True
        else:
            self.controller._story_audio_pending_text = ""
            self.controller._story_audio_block_active = False
        return value, changed

    def _handle_story_audio_line(self, raw_line: str, *, current_lines: list[str], flush) -> str | None:
        line = str(raw_line or "")
        audio_command = re.match(
            r"^\s*\[(AMBIENCE|AMBIENT|MUSIC|FX|SFX|STINGER|AUDIO|SOUND)(?:\s*:\s*([^\]]+))?\]\s*(.*)$",
            line,
            re.IGNORECASE,
        )
        section = re.match(r"^\s*\[(NARRATOR|CHOICES)\]\s*(.*)$", line, re.IGNORECASE)
        character = re.match(r"^\s*\[CHARACTER\s*:\s*([^\]]+)\]\s*(.*)$", line, re.IGNORECASE)
        if section or character:
            self.controller._story_audio_block_active = False
            return None
        if audio_command:
            kind = str(audio_command.group(1) or "").strip().upper()
            cue_name = str(audio_command.group(2) or "").strip()
            body = str(audio_command.group(3) or "").strip()
            if kind not in {"AMBIENCE", "AMBIENT"} and current_lines:
                flush()
            self._queue_story_audio_text(cue_name or body, kind=kind, warn_unmatched=bool(cue_name))
            self.controller._story_audio_block_active = not bool(cue_name)
            return body

        if bool(getattr(self.controller, "_story_audio_block_active", False)):
            cue_ids = self._story_audio_ids_for_text(line, warn_unmatched=False)
            if cue_ids or not line.strip():
                self._queue_pending_story_audio_cues(cue_ids, kind="AUDIO")
                return ""
            if line.lstrip().startswith(("*", "-", "•")) and re.search(
                r"\b(?:file|ready|ambience|ambient|music|stinger|fx|sfx|audiofx|audio|sound)\b",
                line,
                re.IGNORECASE,
            ):
                self._queue_pending_story_audio_cues(cue_ids, kind="AUDIO")
                return ""
            self.controller._story_audio_block_active = False

        stripped = self._strip_inline_story_audio_tags_for_routing(line, current_lines=current_lines, flush=flush)
        if stripped != line:
            return stripped
        return None

    def _strip_inline_story_audio_tags_for_routing(self, line: str, *, current_lines: list[str], flush) -> str:
        text = str(line or "")
        pattern = re.compile(
            r"\[(AMBIENCE|AMBIENT|MUSIC|FX|SFX|STINGER|AUDIO|SOUND)\s*:\s*([^\]]+)\]",
            re.IGNORECASE,
        )
        if not pattern.search(text):
            return text
        output: list[str] = []
        cursor = 0
        for match in pattern.finditer(text):
            before = text[cursor : match.start()]
            if before:
                output.append(before)
            kind = str(match.group(1) or "").strip().upper()
            cue_text = str(match.group(2) or "").strip()
            if kind not in {"AMBIENCE", "AMBIENT"}:
                pending_text = "".join(output).strip()
                if pending_text:
                    current_lines.append(pending_text)
                    output = []
                if current_lines:
                    flush()
            self._queue_story_audio_text(cue_text, kind=kind, warn_unmatched=True)
            cursor = match.end()
        tail = text[cursor:]
        if tail:
            output.append(tail)
        return "".join(output).strip()

    def _queue_story_audio_text(self, cue_text: str, *, kind: str, warn_unmatched: bool) -> None:
        cue_ids = self._story_audio_ids_for_text(cue_text, warn_unmatched=warn_unmatched)
        self._queue_pending_story_audio_cues(cue_ids, kind=kind)

    def _story_audio_ids_for_text(self, cue_text: str, *, warn_unmatched: bool) -> list[str]:
        resolver = getattr(self.controller, "_story_audio_cue_ids", None)
        cue_ids = list(resolver(cue_text) if callable(resolver) else [])
        if not cue_ids and warn_unmatched:
            logger = getattr(self.controller.context, "logger", None)
            if logger is not None:
                logger.warning("[AR_MODE] Ignored unmatched ambience tag: %s", str(cue_text or "").strip()[:160])
            recorder = getattr(self.controller, "_record_story_event", None)
            if callable(recorder):
                try:
                    recorder(
                        f"sound skipped: no matching AudioFX for '{str(cue_text or '').strip()[:120]}'",
                        severity="warning",
                        kind="audiofx",
                        persist=True,
                    )
                except Exception:
                    pass
        return [str(cue_id or "").strip() for cue_id in cue_ids if str(cue_id or "").strip()]

    def _queue_pending_story_audio_cues(self, cue_ids: list[str], *, kind: str) -> None:
        if not cue_ids:
            return
        existing = {str(cue_id or "").lower() for cue_id in self._pending_story_audio_cues}
        fresh = [cue_id for cue_id in cue_ids if str(cue_id or "").lower() not in existing]
        if not fresh:
            return
        if str(kind or "").strip().upper() in {"AMBIENCE", "AMBIENT"}:
            self._pending_story_audio_cues = fresh + self._pending_story_audio_cues
        else:
            self._pending_story_audio_cues.extend(fresh)

    def _normalize_ar_story_tags(self, text: str) -> str:
        value = str(text or "")
        return re.sub(
            r"(?<!^)(?<!\n)\s*(\[(?:CHARACTER\s*:\s*[^\]]+|NARRATOR|CHOICES|AMBIENCE\s*:\s*[^\]]+|AMBIENT\s*:\s*[^\]]+|MUSIC\s*:\s*[^\]]+|FX\s*:\s*[^\]]+|SFX\s*:\s*[^\]]+|STINGER\s*:\s*[^\]]+|AUDIO\s*:\s*[^\]]+|SOUND\s*:\s*[^\]]+)\])",
            r"\n\1",
            value,
            flags=re.IGNORECASE,
        )

    @staticmethod
    def _strip_assistant_prefix_before_ar_tag(text: str) -> str:
        return re.sub(
            r"(?im)^\s*(?:[^\w\[]+\s*)?(?:assistant|ai|bot)\s*:\s*(?=\[(?:CHARACTER\s*:[^\]]+|NARRATOR|CHOICES|AMBIENCE(?:\s*:[^\]]+)?|AMBIENT(?:\s*:[^\]]+)?|MUSIC\s*:[^\]]+|FX\s*:[^\]]+|SFX\s*:[^\]]+|STINGER\s*:[^\]]+|AUDIO\s*:[^\]]+|SOUND\s*:[^\]]+)\])",
            "",
            str(text or ""),
        )

    def _split_ar_character_dialogue(
        self,
        text: str,
        persona: PersonaConfig,
        *,
        explicit_speaker_label: bool = False,
    ) -> list[tuple[PersonaConfig, str]]:
        narrator = self._narrator_persona() or self.controller.active_persona()
        if narrator is None or not self._is_alternative_reality():
            return []
        value = str(text or "").strip()
        if not value:
            return []
        matches = list(re.finditer(r'"[^"\n]*(?:"|$)|“[^”\n]*(?:”|$)', value))
        if persona.id == narrator.id:
            quoted = self._split_ar_narrator_attributed_dialogue(value, narrator, matches)
            if quoted:
                return quoted
            return self._split_ar_narrator_unquoted_attributed_dialogue(value, narrator)
        if not matches:
            if (
                explicit_speaker_label
                and not self._is_direction_only_dialogue(value)
                and self._looks_like_character_direct_speech(value, persona)
            ):
                return [(persona, value)]
            target = persona if self._looks_like_character_direct_speech(value, persona) else narrator
            return [(target, value)]
        fragments: list[tuple[PersonaConfig, str]] = []
        cursor = 0
        for match in matches:
            before = value[cursor : match.start()].strip()
            dialogue = match.group(0).strip()
            if before:
                if re.fullmatch(r"(?:\[[^\]]{1,40}\]\s*)+", before):
                    dialogue = f"{before} {dialogue}".strip()
                else:
                    fragments.append((narrator, before))
            if dialogue:
                if not self._is_direction_only_dialogue(dialogue):
                    fragments.append((persona, dialogue))
            cursor = match.end()
        after = value[cursor:].strip()
        if after:
            target = persona if self._looks_like_character_direct_speech(after, persona) else narrator
            fragments.append((target, after))
        return [(fragment_persona, fragment_text) for fragment_persona, fragment_text in fragments if fragment_text.strip()]

    def _split_ar_narrator_attributed_dialogue(
        self,
        value: str,
        narrator: PersonaConfig,
        matches: list[re.Match[str]],
    ) -> list[tuple[PersonaConfig, str]]:
        if not matches:
            return []
        fragments: list[tuple[PersonaConfig, str]] = []
        cursor = 0
        any_character_dialogue = False
        previous_speaker: PersonaConfig | None = None
        for match in matches:
            before = value[cursor : match.start()].strip()
            label_speaker, before_without_label = self._split_trailing_inline_dialogue_label(before, narrator)
            if before_without_label:
                fragments.append((narrator, before_without_label))
            elif before and label_speaker is None:
                fragments.append((narrator, before))
            dialogue = match.group(0).strip()
            speaker = label_speaker or self._infer_attributed_dialogue_speaker(
                value[max(0, cursor) : match.start()],
                value[match.end() : min(len(value), match.end() + 240)],
                previous_speaker,
                narrator,
            )
            if speaker is not None:
                any_character_dialogue = True
                previous_speaker = speaker
                fragments.append((speaker, dialogue))
            elif dialogue:
                fragments.append((narrator, dialogue))
            cursor = match.end()
        after = value[cursor:].strip()
        if after:
            fragments.append((narrator, after))
        if not any_character_dialogue:
            return []
        return [(fragment_persona, fragment_text) for fragment_persona, fragment_text in fragments if fragment_text.strip()]

    def _split_trailing_inline_dialogue_label(
        self,
        text: str,
        narrator: PersonaConfig,
    ) -> tuple[PersonaConfig | None, str]:
        value = str(text or "").strip()
        if not value:
            return None, ""
        for persona, names in self._dialogue_speaker_name_candidates(narrator):
            for name in names:
                match = re.search(r"\b" + re.escape(name) + r"\b\s*:\s*$", value, re.IGNORECASE)
                if match:
                    return persona, value[: match.start()].strip()
        return None, value

    def _split_ar_narrator_unquoted_attributed_dialogue(
        self,
        value: str,
        narrator: PersonaConfig,
    ) -> list[tuple[PersonaConfig, str]]:
        text = str(value or "").strip()
        if not text:
            return []
        fragments: list[tuple[PersonaConfig, str]] = []
        cursor = 0
        any_character_dialogue = False
        for match, speaker in self._iter_unquoted_attributed_dialogue_matches(text, narrator):
            if match.start() < cursor:
                continue
            speech_start = match.end()
            speech_end = self._unquoted_dialogue_end(text, speech_start)
            speech = text[speech_start:speech_end].strip(" ,:-")
            if not speech or not self._looks_like_unquoted_attributed_speech(speech, speaker):
                continue
            before = text[cursor : match.start()].strip()
            if before:
                fragments.append((narrator, before))
            any_character_dialogue = True
            fragments.append((speaker, speech))
            cursor = speech_end
        after = text[cursor:].strip()
        if after:
            fragments.append((narrator, after))
        if not any_character_dialogue:
            return []
        return [(fragment_persona, fragment_text) for fragment_persona, fragment_text in fragments if fragment_text.strip()]

    def _iter_unquoted_attributed_dialogue_matches(
        self,
        text: str,
        narrator: PersonaConfig,
    ) -> list[tuple[re.Match[str], PersonaConfig]]:
        results: list[tuple[re.Match[str], PersonaConfig]] = []
        verbs = self._dialogue_attribution_verbs()
        for persona, names in self._dialogue_speaker_name_candidates(narrator):
            for name in names:
                escaped = re.escape(name)
                pattern = re.compile(
                    r"\b"
                    + escaped
                    + r"\b(?:\s+\w+){0,3}\s+(?:"
                    + verbs
                    + r")\b(?:\s+\w+){0,4}\s*[,:\-]\s*",
                    re.IGNORECASE,
                )
                for match in pattern.finditer(text):
                    results.append((match, persona))
        return sorted(results, key=lambda item: item[0].start())

    @staticmethod
    def _unquoted_dialogue_end(text: str, start: int) -> int:
        value = str(text or "")
        for match in re.finditer(r"[.!?](?=\s|$)", value[max(0, int(start)) :]):
            return max(0, int(start)) + match.end()
        return len(value)

    def _looks_like_unquoted_attributed_speech(self, text: str, persona: PersonaConfig) -> bool:
        value = str(text or "").strip()
        if not value or self._is_direction_only_dialogue(value):
            return False
        if self._looks_like_character_direct_speech(value, persona):
            return True
        if self._starts_like_third_person_narration(value, persona):
            return False
        return bool(re.search(r"[.!?]$", value)) and len(value) <= 180

    def _infer_attributed_dialogue_speaker(
        self,
        before: str,
        after: str,
        previous_speaker: PersonaConfig | None,
        narrator: PersonaConfig,
    ) -> PersonaConfig | None:
        after_text = str(after or "")[:240]
        before_text = str(before or "")[-240:]
        after_label_speaker = self._leading_inline_dialogue_label(after_text, narrator)
        if after_label_speaker is not None:
            self._voice_route_debug(
                "attributed_dialogue",
                reason="speaker_label_after_quote",
                speaker_id=after_label_speaker.id,
                display_name=after_label_speaker.display_name,
                after_excerpt=self._voice_route_log_excerpt(after_text),
            )
            return after_label_speaker
        for persona, names in self._dialogue_speaker_name_candidates(narrator):
            if self._context_names_dialogue_speaker(after_text, names, after_quote=True):
                self._voice_route_debug(
                    "attributed_dialogue",
                    reason="name_after_quote",
                    speaker_id=persona.id,
                    display_name=persona.display_name,
                    after_excerpt=self._voice_route_log_excerpt(after_text),
                )
                return persona
        if self._context_uses_dialogue_pronoun(after_text, after_quote=True):
            speaker = previous_speaker or self._recent_named_persona_from_context(before_text, narrator)
            self._voice_route_debug(
                "attributed_dialogue",
                reason="pronoun_after_quote",
                speaker_id=getattr(speaker, "id", ""),
                display_name=getattr(speaker, "display_name", ""),
                previous_speaker_id=getattr(previous_speaker, "id", ""),
                before_excerpt=self._voice_route_log_excerpt(before_text),
                after_excerpt=self._voice_route_log_excerpt(after_text),
            )
            return speaker
        for persona, names in self._dialogue_speaker_name_candidates(narrator):
            if self._context_names_dialogue_speaker(before_text, names, after_quote=False):
                self._voice_route_debug(
                    "attributed_dialogue",
                    reason="name_before_quote",
                    speaker_id=persona.id,
                    display_name=persona.display_name,
                    before_excerpt=self._voice_route_log_excerpt(before_text),
                )
                return persona
        if self._context_uses_dialogue_pronoun(before_text, after_quote=False):
            speaker = previous_speaker or self._recent_named_persona_from_context(before_text, narrator)
            self._voice_route_debug(
                "attributed_dialogue",
                reason="pronoun_before_quote",
                speaker_id=getattr(speaker, "id", ""),
                display_name=getattr(speaker, "display_name", ""),
                previous_speaker_id=getattr(previous_speaker, "id", ""),
                before_excerpt=self._voice_route_log_excerpt(before_text),
            )
            return speaker
        self._voice_route_debug(
            "attributed_dialogue",
            reason="no_speaker_match",
            before_excerpt=self._voice_route_log_excerpt(before_text),
            after_excerpt=self._voice_route_log_excerpt(after_text),
        )
        return None

    def _leading_inline_dialogue_label(
        self,
        text: str,
        narrator: PersonaConfig,
    ) -> PersonaConfig | None:
        value = str(text or "")
        if not value.strip():
            return None
        for persona, names in self._dialogue_speaker_name_candidates(narrator):
            for name in names:
                if re.match(r"^\s*[,.;:!?-]*\s*" + re.escape(name) + r"\b\s*:\s*(?=[\"'])", value, re.IGNORECASE):
                    return persona
        return None

    def _recent_named_persona_from_context(self, context: str, narrator: PersonaConfig) -> PersonaConfig | None:
        text = str(context or "")[-360:]
        best_index = -1
        best_persona: PersonaConfig | None = None
        for persona, names in self._dialogue_speaker_name_candidates(narrator):
            for name in names:
                pattern = r"\b" + re.escape(name) + r"(?:\b|'s\b)"
                for match in re.finditer(pattern, text, re.IGNORECASE):
                    if match.start() > best_index:
                        best_index = match.start()
                        best_persona = persona
        return best_persona

    def _dialogue_speaker_name_candidates(self, narrator: PersonaConfig) -> list[tuple[PersonaConfig, list[str]]]:
        raw_candidates: list[tuple[PersonaConfig, list[str]]] = []
        name_owners: dict[str, set[str]] = {}
        for persona in self._routing_personas():
            if persona.id == narrator.id:
                continue
            raw_names = [
                str(persona.display_name or "").strip(),
                str(persona.id or "").replace("_", " ").strip(),
            ]
            first_name = raw_names[0].split(" ", 1)[0].strip() if raw_names[0] else ""
            if len(first_name) >= 2:
                raw_names.append(first_name)
            names = sorted({name for name in raw_names if len(name) >= 2}, key=len, reverse=True)
            if names:
                raw_candidates.append((persona, names))
                for name in names:
                    name_owners.setdefault(name.lower(), set()).add(persona.id)
        return [
            (persona, [name for name in names if len(name_owners.get(name.lower(), set())) == 1])
            for persona, names in raw_candidates
            if any(len(name_owners.get(name.lower(), set())) == 1 for name in names)
        ]

    @staticmethod
    def _dialogue_attribution_verbs() -> str:
        return (
            r"says?|said|asks?|asked|answers?|answered|replies?|replied|responds?|responded|"
            r"murmurs?|murmured|mutters?|muttered|whispers?|whispered|calls?|called|"
            r"continues?|continued|adds?|added|pauses?|paused|teases?|teased|remarks?|remarked|"
            r"offers?|offered|snaps?|snapped|grumbles?|grumbled|laughs?|laughed|smiles?|smiled|sighs?|sighed|"
            r"barks?|barked|bellows?|bellowed|blurts?|blurted|booms?|boomed|cackles?|cackled|"
            r"chuckles?|chuckled|cries?|cried|declares?|declared|demands?|demanded|drawls?|drawled|"
            r"exclaims?|exclaimed|gasps?|gasped|giggles?|giggled|groans?|groaned|growls?|growled|"
            r"grunts?|grunted|hisses?|hissed|insists?|insisted|purrs?|purred|rasps?|rasped|"
            r"roars?|roared|scoffs?|scoffed|shouts?|shouted|snarls?|snarled|warns?|warned|yells?|yelled"
        )

    def _context_names_dialogue_speaker(self, context: str, names: list[str], *, after_quote: bool) -> bool:
        text = str(context or "")
        if not text.strip():
            return False
        verbs = self._dialogue_attribution_verbs()
        for name in names:
            escaped = re.escape(name)
            if after_quote:
                if re.match(r"^\s*[,.;:!?-]*\s*" + escaped + r"\b(?:\s+\w+){0,3}\s+(?:" + verbs + r")\b", text, re.IGNORECASE):
                    return True
                if re.match(r"^\s*[,.;:!?-]*\s*(?:" + verbs + r")\s+" + escaped + r"\b", text, re.IGNORECASE):
                    return True
            else:
                tail = text[-220:]
                if re.search(r"\b" + escaped + r"\b(?:\s+\w+){0,6}\s+(?:" + verbs + r")\b[^\n]*$", tail, re.IGNORECASE):
                    return True
                if re.search(r"\b" + escaped + r"\b[^.!?\n]{0,220}$", tail, re.IGNORECASE):
                    return True
        return False

    def _context_uses_dialogue_pronoun(self, context: str, *, after_quote: bool) -> bool:
        text = str(context or "").strip()
        if not text:
            return False
        verbs = self._dialogue_attribution_verbs()
        if after_quote:
            return bool(re.match(r"^[,.;:!?-]*\s*(?:he|she|they)\s+(?:" + verbs + r")\b", text, re.IGNORECASE))
        return bool(re.search(r"\b(?:he|she|they)\s+(?:" + verbs + r")\b[^\n]*$", text[-180:], re.IGNORECASE))

    @staticmethod
    def _is_direction_only_dialogue(text: str) -> bool:
        value = str(text or "").strip().strip('"“”').strip()
        return bool(re.fullmatch(r"\[[^\]]{1,40}\]", value))

    def _looks_like_character_direct_speech(self, text: str, persona: PersonaConfig) -> bool:
        value = str(text or "").strip()
        if not value:
            return False
        visible = re.sub(r"^\s*(?:\[[^\]]{1,40}\]\s*)+", "", value).strip()
        if not visible:
            return False
        if visible.startswith(('"', "'", "“", "‘")):
            return True
        first_person_anywhere = re.search(r"(?i)\b(?:i|i'm|im|i.ve|i've|i.ll|i'll|i.d|i'd|me|my|mine|we|we're|we.ve|we've|we.ll|we'll|us|our|ours)\b", visible)
        if first_person_anywhere:
            return True
        if self._starts_like_third_person_narration(visible, persona):
            return False
        first_person = re.match(
            r"(?i)^(?:i|i'm|im|i’ve|i've|i’ll|i'll|i’d|i'd|me|my|mine|we|we're|we’ve|we've|we’ll|we'll|our|ours)\b",
            visible,
        )
        if first_person:
            return True
        if re.search(r"(?i)\b(?:you|your|yours|cutie|darling|boss|partner|traveler|mortal|honey|friend)\b", visible):
            return True
        if re.search(r"[?!]", visible):
            return True
        if re.match(r"(?i)^(?:yes|no|yeah|yep|nah|hey|hello|well|oh|ah|mmm|mm|hmm|listen|look|come here|shut up|great|fine|okay|ok)\b", visible):
            return True
        if len(visible) <= 90 and not re.search(r"(?i)\b(?:steps|leans|turns|walks|moves|stares|grins|smiles|laughs|cackles|grunts|sighs|gestures|points|watches|looks|frowns|snarls|tail|eyes|hands|voice)\b", visible):
            return True
        return False

    def _starts_like_third_person_narration(self, text: str, persona: PersonaConfig) -> bool:
        visible = str(text or "").strip()
        if not visible:
            return False
        persona_names = {
            normalize_persona_id(persona.id).replace("_", " "),
            str(persona.display_name or "").strip().lower(),
        }
        first_name = str(persona.display_name or "").strip().split(" ", 1)[0].lower()
        if first_name:
            persona_names.add(first_name)
        lower = visible.lower()
        for name in persona_names:
            name = str(name or "").strip()
            if name and re.match(r"^" + re.escape(name) + r"(?:\b|['’]s\b)", lower):
                return True
        if re.match(r"(?i)^(?:he|she|they|it|his|her|hers|their|theirs|its|the|a|an)\b", visible):
            return True
        if re.match(r"(?i)^(?:leaning|turning|stepping|walking|moving|watching|grinning|smiling|laughing|cackling|staring|gesturing|pointing|squinting|snarling|sighing)\b", visible):
            return True
        return False

    def _consume_pending_story_audio_cues(self) -> list[str]:
        cues = []
        seen = set()
        for cue_id in list(self._pending_story_audio_cues or []):
            key = str(cue_id or "").strip().lower()
            if key and key not in seen:
                cues.append(str(cue_id))
                seen.add(key)
        self._pending_story_audio_cues = []
        return cues

    def detect_speaker(self, text: str) -> PersonaConfig | None:
        for raw_line in str(text or "").splitlines():
            if not raw_line.strip():
                continue
            speaker, _body, matched = self._split_speaker_prefix(raw_line)
            if matched:
                return speaker
            return None
        return None

    def _split_speaker_prefix(self, line: str) -> tuple[PersonaConfig | None, str, bool]:
        text = str(line or "")
        assistant_prefixed = re.match(
            r"^\s*(?:[^\w\[]+\s*)?(?:assistant|ai|bot)\s*:\s*(\[(?:CHARACTER\s*:[^\]]+|NARRATOR|CHOICES|AMBIENCE(?:\s*:[^\]]+)?|AMBIENT(?:\s*:[^\]]+)?|MUSIC\s*:[^\]]+|FX\s*:[^\]]+|SFX\s*:[^\]]+|STINGER\s*:[^\]]+|AUDIO\s*:[^\]]+|SOUND\s*:[^\]]+)\].*)$",
            text,
            re.IGNORECASE,
        )
        if assistant_prefixed:
            text = assistant_prefixed.group(1)
        ar_character = re.match(r"^\s*\[CHARACTER\s*:\s*([^\]]+)\]\s*(.*)$", text, re.IGNORECASE)
        if ar_character:
            persona = self._resolve_persona(ar_character.group(1))
            if persona is None:
                persona = self._ensure_character_persona(ar_character.group(1), text)
            return persona, ar_character.group(2), True

        ar_section = re.match(r"^\s*\[(NARRATOR|AMBIENCE|CHOICES)\]\s*(.*)$", text, re.IGNORECASE)
        if ar_section:
            return self._narrator_persona() or self.controller.active_persona(), ar_section.group(2), True

        bracket_label = re.match(r"^\s*\[([^\]]{1,120})\]\s*(.*)$", text)
        if bracket_label:
            label_text = bracket_label.group(1).strip()
            candidate_name = label_text.split(":", 1)[0].strip()
            persona = self._resolve_persona(candidate_name) or self._resolve_persona(label_text)
            if persona is not None:
                return persona, bracket_label.group(2), True

        leading_tags = ""
        remaining = text
        while True:
            if re.match(r"^\s*\[(?:persona|speaker)\s*:", remaining, re.IGNORECASE):
                break
            if re.match(r"^\s*\[CHARACTER\s*:", remaining, re.IGNORECASE):
                break
            tag = re.match(r"^\s*(\[[^\]]+\])\s*(.*)$", remaining)
            if not tag:
                break
            leading_tags += tag.group(1).strip() + " "
            remaining = tag.group(2)

        ar_character = re.match(r"^\s*\[CHARACTER\s*:\s*([^\]]+)\]\s*(.*)$", remaining, re.IGNORECASE)
        if ar_character:
            persona = self._resolve_persona(ar_character.group(1))
            if persona is None:
                persona = self._ensure_character_persona(ar_character.group(1), remaining)
            return persona, (leading_tags + ar_character.group(2)).strip(), True

        ar_section = re.match(r"^\s*\[(NARRATOR|AMBIENCE|CHOICES)\]\s*(.*)$", remaining, re.IGNORECASE)
        if ar_section:
            return self._narrator_persona() or self.controller.active_persona(), (leading_tags + ar_section.group(2)).strip(), True

        control = re.match(r"^\s*\[(?:persona|speaker)\s*:\s*([^\]]+)\]\s*(.*)$", remaining, re.IGNORECASE)
        if control:
            return self._resolve_persona(control.group(1)), (leading_tags + control.group(2)).strip(), True

        label = re.match(r"^\s*(?:\*\*)?([A-Za-z][A-Za-z0-9 _.'-]{0,80})(?:\*\*)?\s*:\s*(.*)$", remaining)
        if label:
            persona = self._resolve_persona(label.group(1))
            if persona is None and self._is_alternative_reality() and self._looks_like_dialogue(label.group(2)):
                persona = self._ensure_character_persona(label.group(1), remaining)
            if persona is not None:
                body = label.group(2)
                return persona, (leading_tags + body).strip(), True
        if not self._is_alternative_reality():
            persona = self._resolve_persona_line_prefix(remaining)
            if persona is not None:
                return persona, (leading_tags + remaining).strip(), True
        return None, text, False

    def _explicit_persona_for_payload(self, payload: dict[str, Any] | None) -> PersonaConfig | None:
        data = payload if isinstance(payload, dict) else {}
        explicit = data.get("persona_id") or data.get("speaker_id") or data.get("current_speaker_id") or ""
        return self._resolve_persona(explicit)

    def _strip_known_speaker_labels_for_explicit_route(self, text: str) -> str:
        lines = []
        for raw_line in str(text or "").splitlines():
            line = str(raw_line or "")
            assistant_prefixed = re.match(
                r"^\s*(?:[^\w\[]+\s*)?(?:assistant|ai|bot)\s*:\s*(\[(?:CHARACTER\s*:[^\]]+|NARRATOR|CHOICES)\].*)$",
                line,
                re.IGNORECASE,
            )
            if assistant_prefixed:
                line = assistant_prefixed.group(1)
            character = re.match(r"^\s*\[CHARACTER\s*:\s*([^\]]+)\]\s*(.*)$", line, re.IGNORECASE)
            if character:
                if str(character.group(2) or "").strip():
                    lines.append(str(character.group(2) or "").strip())
                continue
            section = re.match(r"^\s*\[(NARRATOR|CHOICES)\]\s*(.*)$", line, re.IGNORECASE)
            if section:
                if str(section.group(2) or "").strip():
                    lines.append(str(section.group(2) or "").strip())
                continue
            control = re.match(r"^\s*\[(?:persona|speaker)\s*:\s*([^\]]+)\]\s*(.*)$", line, re.IGNORECASE)
            if control and self._resolve_persona(control.group(1)) is not None:
                if str(control.group(2) or "").strip():
                    lines.append(str(control.group(2) or "").strip())
                continue
            bracket_label = re.match(r"^\s*\[([^\]]{1,120})\]\s*(.*)$", line)
            if bracket_label and self._resolve_persona(bracket_label.group(1).split(":", 1)[0].strip()) is not None:
                if str(bracket_label.group(2) or "").strip():
                    lines.append(str(bracket_label.group(2) or "").strip())
                continue
            lines.append(line)
        return "\n".join(lines).strip()

    def _ensure_character_persona(self, name: str, context_text: str) -> PersonaConfig | None:
        creator = getattr(self.controller, "ensure_persona_for_character_label", None)
        if not callable(creator):
            return None
        try:
            return creator(name, context_text=context_text, source="voice_route", save=True)
        except Exception as exc:
            logger = getattr(self.controller.context, "logger", None)
            if logger is not None:
                logger.warning("[MPRC] Could not create persona for speaker %s: %s", name, exc)
            return None

    @staticmethod
    def _looks_like_dialogue(text: str) -> bool:
        value = str(text or "").strip()
        if not value:
            return False
        if value.startswith(('"', "'", "“", "‘")):
            return True
        return bool(re.match(r"^(?:\[[^\]]{1,40}\]\s*)?[\"'“‘]", value))

    def _resolve_persona_line_prefix(self, value: str) -> PersonaConfig | None:
        text = str(value or "").lstrip()
        if not text:
            return None
        candidates: list[tuple[str, PersonaConfig]] = []
        first_token_owner: dict[str, PersonaConfig | None] = {}
        for persona in self.controller.personas:
            if not bool(getattr(persona, "enabled", True)):
                continue
            names = [
                str(persona.display_name or "").strip(),
                str(persona.id or "").replace("_", " ").strip(),
            ]
            for name in names:
                if len(name) >= 3:
                    candidates.append((name, persona))
            first = re.split(r"\s+", names[0].strip(), maxsplit=1)[0] if names and names[0].strip() else ""
            first_key = first.lower()
            if len(first) >= 3 and first_key not in {"the", "and", "but"}:
                if first_key in first_token_owner and first_token_owner[first_key] is not persona:
                    first_token_owner[first_key] = None
                else:
                    first_token_owner[first_key] = persona
        for first, persona in first_token_owner.items():
            if persona is not None:
                candidates.append((first, persona))
        candidates.sort(key=lambda item: len(item[0]), reverse=True)
        for name, persona in candidates:
            pattern = r"^\s*(?:\*\*)?" + re.escape(name) + r"(?:\*\*)?(?=\s|['’]s\b|[,.;:!?—-])"
            if re.match(pattern, text, re.IGNORECASE):
                return persona
        return None

    def _resolve_persona(self, value: Any) -> PersonaConfig | None:
        wanted = str(value or "").strip()
        if not wanted:
            return None
        normalized = normalize_persona_id(wanted)
        enabled_personas = self._enabled_personas()
        for persona in enabled_personas:
            if persona.id == normalized:
                return persona
        alias_resolver = getattr(self.controller, "resolve_story_persona_alias", None)
        if callable(alias_resolver):
            try:
                persona = alias_resolver(wanted)
            except Exception:
                persona = None
            if persona is not None and bool(getattr(persona, "enabled", True)):
                return persona
        routing_personas = self._routing_personas(enabled_personas)
        lowered = wanted.lower()
        for persona in routing_personas:
            names = {
                str(persona.display_name or "").strip().lower(),
                str(persona.role or "").strip().lower(),
            }
            if lowered in names:
                return persona
        fuzzy = self._resolve_persona_fuzzy(wanted, personas=routing_personas)
        if fuzzy is not None:
            return fuzzy
        return None

    def _enabled_personas(self) -> list[PersonaConfig]:
        return [persona for persona in self.controller.personas if bool(getattr(persona, "enabled", True))]

    def _routing_personas(self, enabled_personas: list[PersonaConfig] | None = None) -> list[PersonaConfig]:
        enabled = list(enabled_personas if enabled_personas is not None else self._enabled_personas())
        if not self._is_alternative_reality():
            return enabled
        linked_getter = getattr(self.controller, "_current_linked_persona_ids", None)
        if not callable(linked_getter):
            return enabled
        try:
            linked_ids = [normalize_persona_id(item) for item in list(linked_getter() or []) if str(item or "").strip()]
        except Exception:
            return enabled
        if not linked_ids:
            return enabled
        by_id = {persona.id: persona for persona in enabled}
        linked = [by_id[persona_id] for persona_id in linked_ids if persona_id in by_id]
        return linked or enabled

    def _resolve_persona_fuzzy(
        self,
        value: str,
        *,
        personas: list[PersonaConfig] | None = None,
    ) -> PersonaConfig | None:
        wanted_norm = normalize_persona_id(value)
        wanted_tokens = self._identity_tokens(value)
        if not wanted_norm or not wanted_tokens:
            return None
        scored: list[tuple[float, PersonaConfig]] = []
        for persona in list(personas if personas is not None else self._enabled_personas()):
            candidates = [
                persona.id,
                persona.display_name,
                persona.role,
                persona.behavior_mode,
            ]
            candidates.extend(list(persona.tags or []))
            best = 0.0
            for candidate in candidates:
                candidate_text = str(candidate or "").strip()
                if not candidate_text:
                    continue
                candidate_norm = normalize_persona_id(candidate_text)
                candidate_tokens = self._identity_tokens(candidate_text)
                if not candidate_norm or not candidate_tokens:
                    continue
                if wanted_norm == candidate_norm:
                    best = max(best, 100.0)
                elif wanted_norm.endswith("_" + candidate_norm) or candidate_norm.endswith("_" + wanted_norm):
                    best = max(best, 88.0)
                elif len(candidate_norm) >= 4 and f"_{candidate_norm}_" in f"_{wanted_norm}_":
                    best = max(best, 82.0)
                else:
                    overlap = len(wanted_tokens & candidate_tokens)
                    if overlap:
                        jaccard = overlap / max(1, len(wanted_tokens | candidate_tokens))
                        if candidate_tokens <= wanted_tokens or wanted_tokens <= candidate_tokens:
                            best = max(best, 76.0 + min(10.0, overlap))
                        else:
                            best = max(best, 60.0 * jaccard)
            if best >= 72.0:
                scored.append((best, persona))
        if not scored:
            return None
        scored.sort(key=lambda item: item[0], reverse=True)
        if len(scored) > 1 and scored[0][0] == scored[1][0]:
            return None
        return scored[0][1]

    @staticmethod
    def _identity_tokens(value: Any) -> set[str]:
        stop = {"the", "a", "an", "mr", "mrs", "ms", "dr", "sir", "lady", "lord"}
        return {
            token
            for token in re.findall(r"[a-z0-9]+", str(value or "").lower())
            if len(token) >= 2 and token not in stop
        }

    def _warn_unresolved_speaker(self, line: str) -> None:
        logger = getattr(self.controller.context, "logger", None)
        if logger is None:
            return
        label = str(line or "").strip()[:120]
        logger.warning("MPRC could not resolve speaker label for voice routing: %s", label)

    def _narrator_persona(self) -> PersonaConfig | None:
        selected = getattr(self.controller, "selected_narrator_persona", lambda: None)()
        if selected is not None and bool(getattr(selected, "enabled", True)):
            return selected
        routing_personas = self._routing_personas()
        for persona in routing_personas:
            if persona.display_name.strip().lower() == "story narrator":
                return persona
        for persona in routing_personas:
            text = " ".join([persona.id, persona.role, persona.behavior_mode, ",".join(persona.tags)]).lower()
            if "narrator" in text:
                return persona
        return None

    def _ar_stream_persona(self, payload: dict[str, Any] | None = None) -> PersonaConfig | None:
        if not bool((payload or {}).get("streaming", False)):
            return None
        key = self._ar_stream_key(payload)
        speaker_id = str(self._ar_stream_speaker_by_key.get(key) or self._ar_stream_speaker_id or "").strip()
        if not speaker_id:
            return None
        return self._resolve_persona(speaker_id)

    def _set_ar_stream_speaker(self, payload: dict[str, Any] | None, speaker_id: str) -> None:
        key = self._ar_stream_key(payload)
        value = str(speaker_id or "").strip()
        self._ar_stream_speaker_id = value
        if value:
            self._ar_stream_speaker_by_key[key] = value
            self._ar_stream_speaker_at_by_key[key] = time.time()
        else:
            self._ar_stream_speaker_by_key.pop(key, None)
            self._ar_stream_speaker_at_by_key.pop(key, None)

    def _clear_ar_stream_speaker_state(self) -> None:
        self._ar_stream_speaker_id = ""
        self._ar_stream_speaker_by_key.clear()
        self._ar_stream_speaker_at_by_key.clear()

    def _expire_stale_ar_stream_speaker(self, payload: dict[str, Any] | None, *, max_age_seconds: float = 12.0) -> None:
        key = self._ar_stream_key(payload)
        updated_at = float(self._ar_stream_speaker_at_by_key.get(key, 0.0) or 0.0)
        if updated_at and time.time() - updated_at <= max_age_seconds:
            return
        if key in self._ar_stream_speaker_by_key:
            self._ar_stream_speaker_by_key.pop(key, None)
            self._ar_stream_speaker_at_by_key.pop(key, None)
            if key == "__default__":
                self._ar_stream_speaker_id = ""

    @staticmethod
    def _stream_source_index_is_start(payload: dict[str, Any] | None) -> bool:
        if not isinstance(payload, dict) or "stream_source_index" not in payload:
            return False
        try:
            return int(payload.get("stream_source_index")) == 0
        except Exception:
            return str(payload.get("stream_source_index") or "").strip() == "0"

    @staticmethod
    def _ar_stream_key(payload: dict[str, Any] | None) -> str:
        data = payload if isinstance(payload, dict) else {}
        for key in (
            "response_id",
            "tts_response_id",
            "stream_id",
            "source_id",
            "request_id",
            "generation_id",
            "conversation_id",
        ):
            value = str(data.get(key) or "").strip()
            if value:
                return f"{key}:{value}"
        return "__default__"

    def _is_alternative_reality(self) -> bool:
        return str(getattr(self.controller.session, "mode", "") or "").strip().lower() == AR_MODE.lower()

    def _voice_route_debug(self, event: str, **payload: Any) -> None:
        events = getattr(self, "_voice_route_debug_events", None)
        if not isinstance(events, list):
            return
        record = {"event": str(event or "").strip() or "event"}
        for key, value in dict(payload or {}).items():
            if isinstance(value, Path):
                value = str(value)
            elif not isinstance(value, (str, int, float, bool, type(None), list, tuple, dict)):
                value = str(value)
            record[str(key)] = value
        events.append(record)

    def _write_voice_route_debug(
        self,
        payload: dict[str, Any],
        input_text: str,
        result: dict[str, Any],
        events: list[dict[str, Any]],
    ) -> None:
        try:
            segments = []
            for index, segment in enumerate(list((result or {}).get("segments") or [])):
                if not isinstance(segment, dict):
                    continue
                route = dict(segment.get("voice_route") or {}) if isinstance(segment.get("voice_route"), dict) else {}
                voice_path = str(segment.get("voice_path") or route.get("sample_path") or "")
                segments.append(
                    {
                        "index": index,
                        "persona_id": str(segment.get("persona_id") or ""),
                        "display_name": str(segment.get("display_name") or ""),
                        "voice_file": Path(voice_path).name if voice_path else "",
                        "voice_supported": bool(route.get("supported")),
                        "route_reason": str(route.get("route_reason") or ""),
                        "warning": str(route.get("warning") or ""),
                        "text_excerpt": self._voice_route_log_excerpt(segment.get("text", "")),
                    }
                )
            entry = {
                "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                "streaming": bool((payload or {}).get("streaming", False)),
                "stream_start": bool((payload or {}).get("stream_start", False)),
                "stream_source_index": (payload or {}).get("stream_source_index", ""),
                "suppress_original": bool((result or {}).get("suppress_original", False)),
                "input_excerpt": self._voice_route_log_excerpt(input_text, limit=360),
                "segments": segments,
                "events": list(events or [])[-120:],
            }
            self._queue_voice_route_debug_entry(entry)
        except Exception as exc:
            self._log_voice_route_debug_failure(exc)

    def _queue_voice_route_debug_entry(self, entry: dict[str, Any]) -> None:
        try:
            self._voice_route_debug_queue.put_nowait(dict(entry or {}))
        except queue.Full:
            return
        with self._voice_route_debug_thread_lock:
            worker = self._voice_route_debug_thread
            if worker is not None and worker.is_alive():
                return
            worker = threading.Thread(
                target=self._voice_route_debug_worker,
                name="MprcVoiceRouteDebugWriter",
                daemon=True,
            )
            self._voice_route_debug_thread = worker
            worker.start()

    def _voice_route_debug_worker(self) -> None:
        while True:
            try:
                entry = self._voice_route_debug_queue.get(timeout=0.25)
            except queue.Empty:
                with self._voice_route_debug_thread_lock:
                    if self._voice_route_debug_queue.empty():
                        self._voice_route_debug_thread = None
                        return
                continue
            try:
                self._append_voice_route_debug_entry(entry)
            finally:
                self._voice_route_debug_queue.task_done()

    def _append_voice_route_debug_entry(self, entry: dict[str, Any]) -> None:
        try:
            path = self._voice_route_log_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.exists() and path.stat().st_size > 2_000_000:
                archive = path.with_suffix(path.suffix + ".1")
                try:
                    if archive.exists():
                        archive.unlink()
                    path.replace(archive)
                except Exception:
                    pass
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception as exc:
            self._log_voice_route_debug_failure(exc)

    def _log_voice_route_debug_failure(self, exc: Exception) -> None:
        logger = getattr(self.controller.context, "logger", None)
        if logger is not None:
            try:
                logger.warning("[MPRC] Voice route debug logging failed: %s", exc)
            except Exception:
                pass

    def _voice_route_log_path(self) -> Path:
        app_root = Path(getattr(self.controller.context, "app_root", Path.cwd()))
        return app_root / "runtime" / "logs" / "mprc_voice_routing.log"

    @staticmethod
    def _voice_route_log_excerpt(value: Any, *, limit: int = 220) -> str:
        text = re.sub(r"\s+", " ", str(value or "")).strip()
        if len(text) <= limit:
            return text
        return text[: max(0, limit - 1)].rstrip() + "…"

    def _resolve_sample_path(self, sample_path: str) -> str:
        raw = str(sample_path or "").strip()
        if not raw:
            return ""
        path = Path(raw)
        candidates = [path]
        if not path.is_absolute():
            app_root = Path(getattr(self.controller.context, "app_root", Path.cwd()))
            candidates.extend([app_root / raw, app_root / "voices" / path.name])
        for candidate in candidates:
            try:
                if candidate.exists():
                    return str(candidate.resolve())
            except Exception:
                continue
        return ""

    def _warn_once(self, result: dict[str, Any]) -> dict[str, Any]:
        warning = str(result.get("warning") or "")
        if warning and warning != self._last_warning:
            logger = getattr(self.controller.context, "logger", None)
            if logger is not None:
                logger.warning(warning)
            recorder = getattr(self.controller, "_record_story_event", None)
            if callable(recorder):
                try:
                    recorder(f"voice skipped: {warning}", severity="warning", kind="voice", persist=True)
                except Exception:
                    pass
            self._last_warning = warning
        return result
