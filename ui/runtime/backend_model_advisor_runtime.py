import re
import subprocess
import threading

from PySide6 import QtCore

try:
    from pynvml import (
        nvmlInit,
        nvmlShutdown,
        nvmlDeviceGetHandleByIndex,
        nvmlDeviceGetMemoryInfo,
    )
except Exception:
    nvmlInit = None
    nvmlShutdown = None
    nvmlDeviceGetHandleByIndex = None
    nvmlDeviceGetMemoryInfo = None


MODEL_ADVISOR_STREAM_OVERHEAD_GIB = 0.5
MODEL_ADVISOR_SAFETY_MARGIN_GIB = 1.5


def _engine():
    import engine

    return engine


class BackendModelAdvisorRuntimeMixin:
    """GPU/model-budget advisor and LM Studio estimate helpers."""
    def _detected_gpu_vram_gib(self):
        try:
            if nvmlInit and nvmlDeviceGetHandleByIndex and nvmlDeviceGetMemoryInfo:
                nvmlInit()
                try:
                    handle = nvmlDeviceGetHandleByIndex(0)
                    info = nvmlDeviceGetMemoryInfo(handle)
                    return float(info.total) / (1024 ** 3)
                finally:
                    if nvmlShutdown:
                        nvmlShutdown()
        except Exception:
            pass
        try:
            result = subprocess.run(
                [
                    "nvidia-smi",
                    "--query-gpu=memory.total",
                    "--format=csv,noheader,nounits",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=5,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if result.returncode == 0:
                lines = [line.strip() for line in (result.stdout or "").splitlines() if line.strip()]
                if lines:
                    return float(lines[0]) / 1024.0
        except Exception:
            pass
        try:
            if hasattr(engine, "torch") and _engine().torch.cuda.is_available():
                props = _engine().torch.cuda.get_device_properties(0)
                return float(props.total_memory) / (1024 ** 3)
        except Exception:
            pass
        return None

    def _current_gpu_memory_snapshot_gib(self):
        try:
            if nvmlInit and nvmlDeviceGetHandleByIndex and nvmlDeviceGetMemoryInfo:
                nvmlInit()
                try:
                    handle = nvmlDeviceGetHandleByIndex(0)
                    info = nvmlDeviceGetMemoryInfo(handle)
                    return {
                        "total_gib": float(info.total) / (1024 ** 3),
                        "free_gib": float(info.free) / (1024 ** 3),
                        "used_gib": float(info.used) / (1024 ** 3),
                        "source": "nvml",
                    }
                finally:
                    if nvmlShutdown:
                        nvmlShutdown()
        except Exception:
            pass
        try:
            result = subprocess.run(
                [
                    "nvidia-smi",
                    "--query-gpu=memory.used,memory.free,memory.total",
                    "--format=csv,noheader,nounits",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=5,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if result.returncode == 0:
                lines = [line.strip() for line in (result.stdout or "").splitlines() if line.strip()]
                if lines:
                    first = lines[0]
                    parts = [part.strip() for part in first.split(",")]
                    if len(parts) >= 3:
                        used_mib = float(parts[0])
                        free_mib = float(parts[1])
                        total_mib = float(parts[2])
                        return {
                            "total_gib": total_mib / 1024.0,
                            "free_gib": free_mib / 1024.0,
                            "used_gib": used_mib / 1024.0,
                            "source": "nvidia-smi",
                        }
        except Exception:
            pass
        try:
            if hasattr(engine, "torch") and _engine().torch.cuda.is_available():
                free_bytes, total_bytes = _engine().torch.cuda.mem_get_info()
                free_gib = float(free_bytes) / (1024 ** 3)
                total_gib = float(total_bytes) / (1024 ** 3)
                used_gib = max(0.0, total_gib - free_gib)
                return {
                    "total_gib": total_gib,
                    "free_gib": free_gib,
                    "used_gib": used_gib,
                    "source": "torch",
                }
        except Exception:
            pass
        total = self._detected_gpu_vram_gib()
        if total is None:
            return None
        return {
            "total_gib": total,
            "free_gib": None,
            "used_gib": None,
            "source": "total_only",
        }

    def _estimate_setup_increment_gib(self):
        avatar_mode = self._current_avatar_mode_value() if hasattr(self, "engine_combo") else "musetalk"
        tts_backend = self._current_tts_backend_value()

        budget = self._invoke_addon_service_capability(
            "avatar_provider_registry",
            "runtime.estimate_overhead_gib",
            {"backend": self, "runtime_config": getattr(_engine(), "RUNTIME_CONFIG", {})},
            default=None,
            provider_id=avatar_mode,
        )
        if budget is None:
            budget = 6.5 if avatar_mode == "musetalk" else (1.0 if avatar_mode == "vam" else 0.8 if avatar_mode == "vseeface" else 0.0)
        budget = float(budget or 0.0)

        tts_budget = self._invoke_addon_service_capability(
            "tts_backend_service",
            "runtime.estimate_overhead_gib",
            {"backend": self, "runtime_config": getattr(_engine(), "RUNTIME_CONFIG", {})},
            default=None,
            backend_id=tts_backend,
        )
        if tts_budget is None:
            tts_budget = 5.2 if tts_backend == "chatterbox" else (2.0 if tts_backend == "pockettts" else 0.1)
        budget += float(tts_budget or 0.0)
        if hasattr(self, "stream_mode_combo") and self.stream_mode_combo.currentText() == "On":
            budget += MODEL_ADVISOR_STREAM_OVERHEAD_GIB
        return budget

    def _recommended_model_budget_gib(self):
        snapshot = self._current_gpu_memory_snapshot_gib()
        if not snapshot:
            return None, None, None, None, None
        total = float(snapshot.get("total_gib") or 0.0)
        used_now = snapshot.get("used_gib")
        setup_increment = self._estimate_setup_increment_gib()
        safety_margin = MODEL_ADVISOR_SAFETY_MARGIN_GIB
        projected_pre_llm_total = None
        if used_now is not None:
            if bool(self.thread and self.thread.is_alive()):
                projected_pre_llm_total = float(used_now)
            else:
                projected_pre_llm_total = float(used_now) + float(setup_increment)
        if projected_pre_llm_total is not None:
            remaining = max(0.5, total - projected_pre_llm_total - safety_margin)
        else:
            remaining = max(0.5, total - float(setup_increment) - safety_margin)
        return snapshot, remaining, setup_increment, projected_pre_llm_total, safety_margin

    def _parse_lms_estimate_output(self, output):
        text = str(output or "")
        gpu_match = re.search(r"Estimated GPU Memory:\s*([0-9.]+)\s*GiB", text, re.IGNORECASE)
        total_match = re.search(r"Estimated Total Memory:\s*([0-9.]+)\s*GiB", text, re.IGNORECASE)
        return {
            "gpu_gib": float(gpu_match.group(1)) if gpu_match else None,
            "total_gib": float(total_match.group(1)) if total_match else None,
            "raw": text.strip(),
        }

    def request_model_estimate(self, model_name):
        model_name = str(model_name or "").strip()
        if self._is_model_catalog_placeholder(model_name):
            return
        if model_name in self._model_estimate_cache or self._model_estimate_in_flight:
            return
        self._model_estimate_in_flight = True

        def worker():
            payload = {"model": model_name, "estimate": None}
            try:
                result = subprocess.run(
                    ["lms", "load", "--estimate-only", model_name],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=30,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                if result.returncode == 0:
                    payload["estimate"] = self._parse_lms_estimate_output((result.stdout or "") + "\n" + (result.stderr or ""))
                else:
                    payload["estimate"] = {"gpu_gib": None, "total_gib": None, "raw": (result.stdout or "") + "\n" + (result.stderr or "")}
            except Exception as exc:
                payload["estimate"] = {"gpu_gib": None, "total_gib": None, "raw": str(exc)}
            with self._model_estimate_lock:
                self._pending_model_estimate = payload
            QtCore.QMetaObject.invokeMethod(self, "_apply_pending_model_estimate", QtCore.Qt.QueuedConnection)

        threading.Thread(target=worker, daemon=True).start()

    def request_model_context_estimates(self, model_name):
        model_name = str(model_name or "").strip()
        if self._is_model_catalog_placeholder(model_name):
            return
        if model_name in self._model_context_estimate_cache or self._model_context_estimate_in_flight:
            return
        self._model_context_estimate_in_flight = True

        def worker():
            context_lengths = [4096, 8192, 16384, 32768]
            samples = []
            for context_length in context_lengths:
                try:
                    result = subprocess.run(
                        ["lms", "load", "--estimate-only", model_name, "--context-length", str(context_length)],
                        capture_output=True,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                        timeout=30,
                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                    )
                    combined = (result.stdout or "") + "\n" + (result.stderr or "")
                    estimate = self._parse_lms_estimate_output(combined)
                    if result.returncode == 0 and estimate.get("gpu_gib") is not None:
                        samples.append({"context_length": context_length, "gpu_gib": float(estimate["gpu_gib"])})
                except Exception:
                    continue
            with self._model_context_estimate_lock:
                self._pending_model_context_estimate = {"model": model_name, "samples": samples}
            QtCore.QMetaObject.invokeMethod(self, "_apply_pending_model_context_estimate", QtCore.Qt.QueuedConnection)

        threading.Thread(target=worker, daemon=True).start()

    def request_single_context_estimate(self, model_name, context_length):
        model_name = str(model_name or "").strip()
        try:
            context_length = int(context_length)
        except Exception:
            return
        if self._is_model_catalog_placeholder(model_name):
            return
        cache_key = (model_name, context_length)
        if cache_key in self._model_single_context_estimate_cache or self._single_context_estimate_in_flight:
            return
        self._single_context_estimate_in_flight = True

        def worker():
            payload = {"model": model_name, "context_length": context_length, "estimate": None}
            try:
                result = subprocess.run(
                    ["lms", "load", "--estimate-only", model_name, "--context-length", str(context_length)],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=30,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                combined = (result.stdout or "") + "\n" + (result.stderr or "")
                estimate = self._parse_lms_estimate_output(combined)
                payload["estimate"] = estimate if result.returncode == 0 else {"gpu_gib": None, "total_gib": None, "raw": combined}
            except Exception as exc:
                payload["estimate"] = {"gpu_gib": None, "total_gib": None, "raw": str(exc)}
            with self._single_context_estimate_lock:
                self._pending_single_context_estimate = payload
            QtCore.QMetaObject.invokeMethod(self, "_apply_pending_single_context_estimate", QtCore.Qt.QueuedConnection)

        threading.Thread(target=worker, daemon=True).start()

    @QtCore.Slot()
    def _apply_pending_model_estimate(self):
        with self._model_estimate_lock:
            payload = dict(self._pending_model_estimate or {})
            self._pending_model_estimate = None
        self._model_estimate_in_flight = False
        model_name = str(payload.get("model") or "").strip()
        estimate = payload.get("estimate")
        if model_name:
            self._model_estimate_cache[model_name] = estimate
        self.update_model_budget_hint()

    @QtCore.Slot()
    def _apply_pending_model_context_estimate(self):
        with self._model_context_estimate_lock:
            payload = dict(self._pending_model_context_estimate or {})
            self._pending_model_context_estimate = None
        self._model_context_estimate_in_flight = False
        model_name = str(payload.get("model") or "").strip()
        samples = list(payload.get("samples") or [])
        if model_name:
            self._model_context_estimate_cache[model_name] = samples
        self.update_model_budget_hint()

    @QtCore.Slot()
    def _apply_pending_single_context_estimate(self):
        with self._single_context_estimate_lock:
            payload = dict(self._pending_single_context_estimate or {})
            self._pending_single_context_estimate = None
        self._single_context_estimate_in_flight = False
        model_name = str(payload.get("model") or "").strip()
        context_length = int(payload.get("context_length") or 0)
        estimate = payload.get("estimate")
        if model_name and context_length > 0:
            self._model_single_context_estimate_cache[(model_name, context_length)] = estimate
        self.update_model_budget_hint()

    def update_model_budget_hint(self):
        if not hasattr(self, "model_budget_label") or not hasattr(self, "model_combo"):
            return
        snapshot, suggested_budget, setup_increment, projected_pre_llm_total, safety_margin = self._recommended_model_budget_gib()
        model_name = str(self.model_combo.currentText() or "").strip()
        provider = self._current_chat_provider_value()
        stats_lines = []
        high_baseline_warning = ""
        available_total_vram = None
        if snapshot is not None:
            total_vram = float(snapshot.get("total_gib") or 0.0)
            available_total_vram = total_vram
            free_now = snapshot.get("free_gib")
            used_now = snapshot.get("used_gib")
            stats_lines.append(f"Total VRAM: {total_vram:.1f} GiB")
            if free_now is not None and used_now is not None:
                used_text = f"{used_now:.1f} GiB"
                if used_now >= 3.0:
                    used_text = f"<span style=\"color:#ff8f8f; font-weight:700;\">{used_text}</span>"
                    high_baseline_warning = (
                        "<span style=\"color:#ff6b6b; font-weight:800;\">"
                        "Baseline GPU usage is already quite high. "
                        "For the most reliable estimate, close other GPU-heavy applications and unload any already loaded LM Studio models."
                        "</span>"
                    )
                stats_lines.append(f"In use VRAM: {used_text}")
            else:
                stats_lines.append("In use VRAM: unavailable")
        else:
            stats_lines.append("Total VRAM: unavailable")
            stats_lines.append("In use VRAM: unavailable")

        if not model_name or model_name in {"Scanning...", "No Models", "Error: Check LM Studio", "Error: Check OpenAI", "Error: Check xAI / Grok", "No Vision Models"}:
            summary = self._format_model_advisor_bubbles(stats_lines, [], high_baseline_warning)
            if high_baseline_warning:
                summary += ""
            self.model_budget_label.setText(summary)
            return

        if provider != "lmstudio":
            remote_label = self._chat_provider_label_from_value(provider)
            summary = self._format_model_advisor_bubbles(
                stats_lines,
                [
                    f"Selected chat provider: {remote_label}.",
                    f"Remote model: {model_name}",
                    "Local LM Studio VRAM estimates do not apply to hosted providers.",
                ],
                "",
            )
            self.model_budget_label.setText(summary)
            return

        estimate = self._model_estimate_cache.get(model_name)
        if estimate is None:
            self.request_model_estimate(model_name)
            self.request_model_context_estimates(model_name)
            summary = self._format_model_advisor_bubbles(
                stats_lines,
                [f"Checking LM Studio estimate for '{model_name}'..."],
                high_baseline_warning,
            )
            self.model_budget_label.setText(summary)
            return

        gpu_gib = estimate.get("gpu_gib") if isinstance(estimate, dict) else None
        if gpu_gib is None:
            summary = self._format_model_advisor_bubbles(
                stats_lines,
                [f"LM Studio estimate for '{model_name}' is unavailable."],
                high_baseline_warning,
            )
            self.model_budget_label.setText(summary)
            return

        context_samples = self._model_context_estimate_cache.get(model_name)
        if context_samples is None:
            self.request_model_context_estimates(model_name)

        recommended_context = None
        estimate_lines = []
        if suggested_budget is not None and context_samples:
            for sample in sorted(context_samples, key=lambda item: int(item.get("context_length", 0) or 0)):
                if float(sample.get("gpu_gib", 0.0) or 0.0) <= suggested_budget:
                    recommended_context = int(sample.get("context_length", 0) or 0)
        if recommended_context and hasattr(self, "model_context_input") and not self._advisor_context_manual_override:
            current_context_value = int(self.model_context_input.value())
            if current_context_value != int(recommended_context):
                self._advisor_context_updating = True
                try:
                    self.model_context_input.setValue(int(recommended_context))
                finally:
                    self._advisor_context_updating = False

        verdict = "Comfortable for the current setup."
        if suggested_budget is not None:
            delta = gpu_gib - suggested_budget
            if delta > 0.75:
                verdict = "Likely beyond the recommended budget."
            elif delta > 0.15:
                verdict = "Slightly above the recommended budget."
            elif delta > -0.4:
                verdict = "Tight but workable."
            elif delta > -1.0:
                verdict = "Should fit, but still high-pressure."

        chosen_context = int(self.model_context_input.value()) if hasattr(self, "model_context_input") else int(recommended_context or 8192)
        exact_context_estimate = None
        if context_samples:
            matching_sample = next(
                (sample for sample in context_samples if int(sample.get("context_length", 0) or 0) == chosen_context),
                None,
            )
            if matching_sample is not None:
                exact_context_estimate = float(matching_sample.get("gpu_gib", 0.0) or 0.0)
        if exact_context_estimate is None:
            cached_exact = self._model_single_context_estimate_cache.get((model_name, chosen_context))
            if isinstance(cached_exact, dict) and cached_exact.get("gpu_gib") is not None:
                exact_context_estimate = float(cached_exact.get("gpu_gib") or 0.0)
            elif chosen_context > 0:
                self.request_single_context_estimate(model_name, chosen_context)

        exact_context_pending = exact_context_estimate is None
        if exact_context_estimate is not None:
            estimated_total_for_context = (
                float(projected_pre_llm_total or 0.0) + float(exact_context_estimate)
                if projected_pre_llm_total is not None
                else float(exact_context_estimate)
            )
        else:
            estimated_total_for_context = (
                float(projected_pre_llm_total or 0.0) + float(gpu_gib)
                if projected_pre_llm_total is not None
                else float(gpu_gib)
            )

        if exact_context_pending:
            estimate_lines.append("Estimated VRAM usage with current settings: checking selected context window...")
            if recommended_context:
                estimate_lines.append(f"- Recommended max context window: {recommended_context:,} tokens")
            else:
                estimate_lines.append("- Recommended max context window: checking...")
        elif available_total_vram is not None and estimated_total_for_context > available_total_vram:
            estimate_lines.append(
                f"Estimated VRAM usage with current settings: {estimated_total_for_context:.1f} GiB "
                f"<span style=\"color:#ff8f8f; font-weight:700;\">(more than available)</span>"
            )
        else:
            estimate_lines.append("Estimated VRAM usage with current settings:")
            estimate_lines.append(
                f"- {chosen_context:,} token context window: {estimated_total_for_context:.1f} GiB"
            )
            if recommended_context:
                estimate_lines.append(f"- Recommended max context window: {recommended_context:,} tokens")
            elif context_samples is None or exact_context_estimate is None:
                estimate_lines.append("- Recommended max context window: checking...")
        estimate_lines.append(f"Assessment: {verdict}")
        summary = self._format_model_advisor_bubbles(stats_lines, estimate_lines, high_baseline_warning)
        self.model_budget_label.setText(summary)

    def _format_model_advisor_bubbles(self, stats_lines, estimate_lines, warning_html=""):
        def bubble(lines, background, border):
            if not lines:
                return ""
            return (
                f"<div style=\"margin:0 0 8px 0; padding:8px 10px; "
                f"background:{background}; border:1px solid {border}; border-radius:8px;\">"
                + "<br>".join(lines)
                + "</div>"
            )

        parts = [
            bubble(stats_lines, "#111924", "#243243"),
            bubble(estimate_lines, "#101722", "#2b3950"),
        ]
        if warning_html:
            parts.append(
                f"<div style=\"margin:0 0 8px 0; padding:8px 10px; "
                f"background:#2a1214; border:1px solid #7a2f36; border-radius:8px;\">{warning_html}</div>"
            )
        return "".join(part for part in parts if part)

