import json
import json
import math
import os
import platform
import re
import statistics
import threading
import time
import uuid
from copy import deepcopy


RUNTIME_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "runtime"))
SESSION_PATH = os.path.join(RUNTIME_DIR, "dry_run_session.json")
PROFILES_PATH = os.path.join(RUNTIME_DIR, "dry_run_profiles.json")
LOG_PATH = os.path.join(RUNTIME_DIR, "DryRun_log.txt")
PERFORMANCE_PROFILES_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "performance_profiles"))

DEFAULT_TARGET_SAMPLES = 0
RECOMMENDED_CONFIDENCE = 0.85
AUTO_STABLE_ROUNDS_REQUIRED = 2
MAX_AUTO_ROUNDS = 16
MAX_AUTO_SAMPLES = 60
STREAM_SAFE_HEADROOM_MS = 600.0
STREAM_LATER_CHUNK_GRAVITY_TARGET = 85.0

TRACKED_CONFIG_KEYS = (
    "avatar_mode",
    "stream_mode",
    "tts_backend",
    "musetalk_vram_mode",
    "model_name",
    "temperature",
    "top_p",
    "top_k",
    "min_p",
    "repeat_penalty",
    "limit_response_length",
    "max_response_tokens",
    "chunk_target_chars",
    "chunk_max_chars",
    "musetalk_chunk_target_chars",
    "musetalk_chunk_max_chars",
    "musetalk_quickstart_1_target_chars",
    "musetalk_quickstart_1_max_chars",
    "musetalk_quickstart_2_target_chars",
    "musetalk_quickstart_2_max_chars",
    "stream_chunk_target_chars",
    "stream_chunk_max_chars",
    "stream_first_chunk_min_chars",
    "stream_force_flush_seconds",
    "stream_force_flush_later_seconds",
)

_lock = threading.Lock()
_session = None
_replies = {}
AUTO_REPLY_PROMPTS = (
    "Interesting, what happens next? Please continue with a few more sentences.",
    "Then what happens after that? Keep going for a little while.",
    "Can you continue the thought in a few more sentences?",
    "Tell me a bit more and carry the idea forward.",
    "What happens after that? Keep the answer flowing naturally.",
    "Go on and develop that a little further.",
)


def _ensure_runtime_dir():
    os.makedirs(RUNTIME_DIR, exist_ok=True)
    os.makedirs(PERFORMANCE_PROFILES_DIR, exist_ok=True)


def _load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except Exception:
        return deepcopy(default)


def _save_json(path, payload):
    _ensure_runtime_dir()
    last_error = None
    for attempt in range(5):
        temp_path = f"{path}.{threading.get_ident()}.{attempt}.tmp"
        try:
            with open(temp_path, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2, ensure_ascii=True)
            os.replace(temp_path, path)
            return
        except Exception as exc:
            last_error = exc
            try:
                if os.path.exists(temp_path):
                    os.remove(temp_path)
            except Exception:
                pass
            time.sleep(0.05 * (attempt + 1))
    raise last_error


def _append_log(message):
    try:
        _ensure_runtime_dir()
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        with open(LOG_PATH, "a", encoding="utf-8") as handle:
            handle.write(f"{timestamp} {message}\n")
    except Exception:
        pass


def log_event(message):
    _append_log(str(message))


def _hardware_fingerprint():
    return {
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "python": platform.python_version(),
        "cpu_count": os.cpu_count() or 0,
    }


def _build_profile_key(config):
    avatar = str(config.get("avatar_mode", "unknown") or "unknown").lower()
    stream = "stream" if bool(config.get("stream_mode", False)) else "nonstream"
    backend = str(config.get("tts_backend", "chatterbox") or "chatterbox").lower()
    return f"{avatar}:{stream}:{backend}"


def _snapshot_config(runtime_config):
    return {key: runtime_config.get(key) for key in TRACKED_CONFIG_KEYS}


def _safe_slug(value):
    text = str(value or "").strip().lower()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return text.strip("_") or "profile"


def _bounded_int(value, minimum, maximum):
    return max(minimum, min(maximum, int(round(value))))


def _bounded_float(value, minimum, maximum):
    return round(max(minimum, min(maximum, float(value))), 2)


def _safe_mean(values):
    values = [float(v) for v in values if v is not None]
    if not values:
        return None
    return sum(values) / len(values)


def _coefficient_of_variation(values):
    values = [float(v) for v in values if v is not None]
    if len(values) < 2:
        return 0.0
    mean_value = _safe_mean(values)
    if not mean_value:
        return 0.0
    try:
        return statistics.pstdev(values) / abs(mean_value)
    except Exception:
        return 0.0


def _derive_summary(observations):
    if not observations:
        return {}
    return {
        "sample_count": len(observations),
        "avg_buffer_wait_ms": _safe_mean(obs.get("first_chunk_buffer_wait_ms") for obs in observations),
        "avg_first_audio_chunk_ms": _safe_mean(obs.get("first_audio_chunk_latency_ms") for obs in observations),
        "avg_audio_start_ms": _safe_mean(obs.get("first_chunk_audio_start_latency_ms") for obs in observations),
        "avg_render_ready_ms": _safe_mean(obs.get("first_chunk_render_ready_ms") for obs in observations),
        "avg_spf_ms": _safe_mean(obs.get("first_chunk_spf_ms") for obs in observations),
        "avg_plan_sync_ms": _safe_mean(obs.get("first_chunk_plan_sync_ms") for obs in observations),
        "avg_idle_sync_ms": _safe_mean(obs.get("first_chunk_idle_sync_ms") for obs in observations),
        "avg_followup_headroom_ms": _safe_mean(obs.get("avg_followup_headroom_ms") for obs in observations),
        "min_followup_headroom_ms": _safe_mean(obs.get("min_followup_headroom_ms") for obs in observations),
        "avg_chunk_quality": _safe_mean(obs.get("avg_chunk_quality") for obs in observations),
        "avg_chunk_chars": _safe_mean(obs.get("avg_chunk_chars") for obs in observations),
    }


def summarize_observations(observations):
    return _derive_summary(observations)


def _score_observation(observation):
    if not observation:
        return None
    config_snapshot = dict(observation.get("config_snapshot") or {})
    latency_score = 0.0
    weights = 0.0
    for key, weight in (
        ("first_audio_chunk_latency_ms", 0.40),
        ("first_chunk_buffer_wait_ms", 0.35),
        ("first_chunk_spf_ms", 0.10),
        ("first_chunk_audio_start_latency_ms", 0.15),
    ):
        value = observation.get(key)
        if value is None:
            continue
        latency_score += float(value) * weight
        weights += weight
    if weights <= 0:
        return None
    latency_score = latency_score / weights

    headroom_ms = observation.get("avg_followup_headroom_ms")
    headroom_score = 0.0
    if headroom_ms is not None:
        headroom_ms = float(headroom_ms)
        if headroom_ms < 0:
            headroom_score += abs(headroom_ms) * 1.5
        else:
            headroom_score -= min(headroom_ms, STREAM_SAFE_HEADROOM_MS) * 0.25

    avg_quality = float(observation.get("avg_chunk_quality", 0.8) or 0.8)
    quality_penalty = (1.0 - max(0.0, min(1.0, avg_quality))) * 400.0

    bloat_score = 0.0
    config_target = float(
        config_snapshot.get(
            "stream_chunk_target_chars",
            STREAM_LATER_CHUNK_GRAVITY_TARGET,
        )
        or STREAM_LATER_CHUNK_GRAVITY_TARGET
    )
    bloat_score += max(0.0, config_target - STREAM_LATER_CHUNK_GRAVITY_TARGET) * 0.5

    avg_chars = float(observation.get("avg_chunk_chars", 80.0) or 80.0)
    if avg_chars > 120.0:
        bloat_score += (avg_chars - 120.0) * 2.0

    score = latency_score + headroom_score + quality_penalty + bloat_score
    return round(score, 2)


def _score_candidate(observations):
    scores = [_score_observation(obs) for obs in observations or []]
    scores = [score for score in scores if score is not None]
    if not scores:
        return None
    return round(sum(scores) / len(scores), 2)


def _build_stream_candidates(target_samples):
    return _build_stream_startup_candidates({})


def _build_stream_startup_candidates(base):
    anchor = [
        {
            "stream_chunk_target_chars": 85,
            "stream_chunk_max_chars": 170,
            "stream_first_chunk_min_chars": 15,
            "stream_force_flush_seconds": 0.6,
            "stream_force_flush_later_seconds": 2.5,
            "musetalk_quickstart_1_target_chars": 80,
            "musetalk_quickstart_1_max_chars": 160,
            "musetalk_quickstart_2_target_chars": 120,
            "musetalk_quickstart_2_max_chars": 220,
        },
        {
            "stream_chunk_target_chars": 85,
            "stream_chunk_max_chars": 170,
            "stream_first_chunk_min_chars": 22,
            "stream_force_flush_seconds": 0.9,
            "stream_force_flush_later_seconds": 2.5,
            "musetalk_quickstart_1_target_chars": 100,
            "musetalk_quickstart_1_max_chars": 190,
            "musetalk_quickstart_2_target_chars": 120,
            "musetalk_quickstart_2_max_chars": 220,
        },
        {
            "stream_chunk_target_chars": 85,
            "stream_chunk_max_chars": 170,
            "stream_first_chunk_min_chars": 30,
            "stream_force_flush_seconds": 1.2,
            "stream_force_flush_later_seconds": 2.5,
            "musetalk_quickstart_1_target_chars": 130,
            "musetalk_quickstart_1_max_chars": 240,
            "musetalk_quickstart_2_target_chars": 120,
            "musetalk_quickstart_2_max_chars": 220,
        },
        {
            "stream_chunk_target_chars": 85,
            "stream_chunk_max_chars": 170,
            "stream_first_chunk_min_chars": 40,
            "stream_force_flush_seconds": 1.5,
            "stream_force_flush_later_seconds": 2.5,
            "musetalk_quickstart_1_target_chars": 160,
            "musetalk_quickstart_1_max_chars": 280,
            "musetalk_quickstart_2_target_chars": 120,
            "musetalk_quickstart_2_max_chars": 220,
        },
    ]
    return anchor


def _build_stream_steady_candidates(base):
    base = dict(base or {})
    startup_first_min = int(base.get("stream_first_chunk_min_chars", 30) or 30)
    startup_flush_first = float(base.get("stream_force_flush_seconds", 1.2) or 1.2)
    qs1_target = int(base.get("musetalk_quickstart_1_target_chars", 130) or 130)
    qs1_max = int(base.get("musetalk_quickstart_1_max_chars", 240) or 240)
    anchor = [
        {
            "stream_chunk_target_chars": 60,
            "stream_chunk_max_chars": 120,
            "stream_first_chunk_min_chars": startup_first_min,
            "stream_force_flush_seconds": startup_flush_first,
            "stream_force_flush_later_seconds": 1.5,
            "musetalk_quickstart_1_target_chars": qs1_target,
            "musetalk_quickstart_1_max_chars": qs1_max,
            "musetalk_quickstart_2_target_chars": 90,
            "musetalk_quickstart_2_max_chars": 170,
        },
        {
            "stream_chunk_target_chars": 85,
            "stream_chunk_max_chars": 170,
            "stream_first_chunk_min_chars": startup_first_min,
            "stream_force_flush_seconds": startup_flush_first,
            "stream_force_flush_later_seconds": 2.0,
            "musetalk_quickstart_1_target_chars": qs1_target,
            "musetalk_quickstart_1_max_chars": qs1_max,
            "musetalk_quickstart_2_target_chars": 120,
            "musetalk_quickstart_2_max_chars": 220,
        },
        {
            "stream_chunk_target_chars": 110,
            "stream_chunk_max_chars": 200,
            "stream_first_chunk_min_chars": startup_first_min,
            "stream_force_flush_seconds": startup_flush_first,
            "stream_force_flush_later_seconds": 2.5,
            "musetalk_quickstart_1_target_chars": qs1_target,
            "musetalk_quickstart_1_max_chars": qs1_max,
            "musetalk_quickstart_2_target_chars": 150,
            "musetalk_quickstart_2_max_chars": 250,
        },
        {
            "stream_chunk_target_chars": 130,
            "stream_chunk_max_chars": 240,
            "stream_first_chunk_min_chars": startup_first_min,
            "stream_force_flush_seconds": startup_flush_first,
            "stream_force_flush_later_seconds": 3.0,
            "musetalk_quickstart_1_target_chars": qs1_target,
            "musetalk_quickstart_1_max_chars": qs1_max,
            "musetalk_quickstart_2_target_chars": 170,
            "musetalk_quickstart_2_max_chars": 280,
        },
    ]
    return anchor


def _build_nonstream_candidates(target_samples):
    count = max(3, int(target_samples or 4))
    anchor = [
        {
            "musetalk_chunk_target_chars": 70,
            "musetalk_chunk_max_chars": 140,
            "musetalk_quickstart_1_target_chars": 150,
            "musetalk_quickstart_1_max_chars": 280,
            "musetalk_quickstart_2_target_chars": 110,
            "musetalk_quickstart_2_max_chars": 210,
        },
        {
            "musetalk_chunk_target_chars": 90,
            "musetalk_chunk_max_chars": 180,
            "musetalk_quickstart_1_target_chars": 160,
            "musetalk_quickstart_1_max_chars": 300,
            "musetalk_quickstart_2_target_chars": 120,
            "musetalk_quickstart_2_max_chars": 220,
        },
        {
            "musetalk_chunk_target_chars": 110,
            "musetalk_chunk_max_chars": 220,
            "musetalk_quickstart_1_target_chars": 170,
            "musetalk_quickstart_1_max_chars": 320,
            "musetalk_quickstart_2_target_chars": 130,
            "musetalk_quickstart_2_max_chars": 240,
        },
        {
            "musetalk_chunk_target_chars": 130,
            "musetalk_chunk_max_chars": 260,
            "musetalk_quickstart_1_target_chars": 180,
            "musetalk_quickstart_1_max_chars": 340,
            "musetalk_quickstart_2_target_chars": 140,
            "musetalk_quickstart_2_max_chars": 260,
        },
    ]
    if count <= len(anchor):
        return anchor[:count]
    candidates = list(anchor)
    while len(candidates) < count:
        last = dict(candidates[-1])
        last["musetalk_chunk_target_chars"] = _bounded_int(last["musetalk_chunk_target_chars"] + 10, 60, 220)
        last["musetalk_chunk_max_chars"] = _bounded_int(last["musetalk_chunk_max_chars"] + 20, 80, 320)
        last["musetalk_quickstart_1_target_chars"] = _bounded_int(last["musetalk_quickstart_1_target_chars"] + 10, 60, 260)
        last["musetalk_quickstart_1_max_chars"] = _bounded_int(last["musetalk_quickstart_1_max_chars"] + 20, 80, 360)
        last["musetalk_quickstart_2_target_chars"] = _bounded_int(last["musetalk_quickstart_2_target_chars"] + 10, 60, 240)
        last["musetalk_quickstart_2_max_chars"] = _bounded_int(last["musetalk_quickstart_2_max_chars"] + 20, 80, 320)
        candidates.append(last)
    return candidates


def _build_candidate_plan(snapshot, target_samples):
    if bool(snapshot.get("stream_mode", False)):
        raw_candidates = _build_stream_startup_candidates(snapshot)
    else:
        raw_candidates = _build_nonstream_candidates(target_samples)
    plan = []
    for index, candidate in enumerate(raw_candidates):
        merged = dict(snapshot or {})
        merged.update(candidate)
        plan.append(
            {
                "index": index,
                "label": f"Candidate {index + 1}",
                "settings": merged,
                "observations": [],
                "score": None,
            }
        )
    return plan


def _build_refined_candidate_plan(snapshot, best_settings, round_index):
    base = dict(snapshot or {})
    base.update(best_settings or {})
    if bool(base.get("stream_mode", False)):
        target = int(base.get("stream_chunk_target_chars", 85) or 85)
        maximum = int(base.get("stream_chunk_max_chars", 170) or 170)
        first_min = int(base.get("stream_first_chunk_min_chars", 28) or 28)
        flush_first = float(base.get("stream_force_flush_seconds", 1.2) or 1.2)
        flush_later = float(base.get("stream_force_flush_later_seconds", 2.5) or 2.5)
        qs1_target = int(base.get("musetalk_quickstart_1_target_chars", 130) or 130)
        qs1_max = int(base.get("musetalk_quickstart_1_max_chars", 240) or 240)
        qs2_target = int(base.get("musetalk_quickstart_2_target_chars", 120) or 120)
        qs2_max = int(base.get("musetalk_quickstart_2_max_chars", 220) or 220)
        deltas = [(-10, -20, -3, -0.2, -0.4), (0, 0, 0, 0.0, 0.0), (10, 20, 3, 0.2, 0.4)]
        candidates = []
        for idx, (dt, dm, df, dff, dfl) in enumerate(deltas):
            merged = dict(base)
            merged["stream_chunk_target_chars"] = _bounded_int(target + dt, 50, 180)
            merged["stream_chunk_max_chars"] = _bounded_int(maximum + dm, 100, 320)
            merged["stream_first_chunk_min_chars"] = _bounded_int(first_min + df, 10, 80)
            merged["stream_force_flush_seconds"] = _bounded_float(flush_first + dff, 0.2, 2.5)
            merged["stream_force_flush_later_seconds"] = _bounded_float(flush_later + dfl, 1.2, 4.0)
            merged["musetalk_quickstart_1_target_chars"] = _bounded_int(qs1_target + dt, 60, 260)
            merged["musetalk_quickstart_1_max_chars"] = _bounded_int(qs1_max + dm, 80, 360)
            merged["musetalk_quickstart_2_target_chars"] = _bounded_int(qs2_target + dt, 60, 240)
            merged["musetalk_quickstart_2_max_chars"] = _bounded_int(qs2_max + dm, 80, 320)
            candidates.append(
                {
                    "index": idx,
                    "label": f"Refined {round_index}.{idx + 1}",
                    "settings": merged,
                    "observations": [],
                    "score": None,
                }
            )
        return candidates
    target = int(base.get("musetalk_chunk_target_chars", 110) or 110)
    maximum = int(base.get("musetalk_chunk_max_chars", 220) or 220)
    deltas = [(-10, -20), (0, 0), (10, 20)]
    candidates = []
    for idx, (dt, dm) in enumerate(deltas):
        merged = dict(base)
        merged["musetalk_chunk_target_chars"] = _bounded_int(target + dt, 60, 220)
        merged["musetalk_chunk_max_chars"] = _bounded_int(maximum + dm, 80, 320)
        candidates.append(
            {
                "index": idx,
                "label": f"Refined {round_index}.{idx + 1}",
                "settings": merged,
                "observations": [],
                "score": None,
            }
        )
    return candidates


def _build_recommendation(snapshot, observations):
    recommendation = {
        "settings": dict(snapshot or {}),
        "notes": [],
    }
    if not observations:
        recommendation["notes"].append("No reply samples captured yet.")
        return recommendation

    summary = _derive_summary(observations)
    settings = recommendation["settings"]
    stream_mode = bool(settings.get("stream_mode", False))
    backend = str(settings.get("tts_backend", "chatterbox") or "chatterbox").lower()

    avg_buffer_wait = summary.get("avg_buffer_wait_ms") or 0.0
    avg_first_audio_chunk = summary.get("avg_first_audio_chunk_ms") or 0.0
    avg_render_ready = summary.get("avg_render_ready_ms") or 0.0
    avg_spf = summary.get("avg_spf_ms") or 0.0

    if stream_mode:
        if backend == "chatterbox" and avg_spf > 120.0:
            settings["tts_backend"] = "pockettts"
            recommendation["notes"].append("PocketTTS looks friendlier to MuseTalk on this hardware in stream mode.")
        if avg_buffer_wait > 7000.0 or avg_spf > 120.0:
            settings["stream_chunk_target_chars"] = _bounded_int(
                (settings.get("stream_chunk_target_chars", 85) or 85) + 10, 40, 220
            )
            settings["stream_chunk_max_chars"] = _bounded_int(
                (settings.get("stream_chunk_max_chars", 170) or 170) + 20, 60, 320
            )
            settings["musetalk_quickstart_1_target_chars"] = _bounded_int(
                (settings.get("musetalk_quickstart_1_target_chars", 170) or 170) + 10, 60, 260
            )
            settings["musetalk_quickstart_1_max_chars"] = _bounded_int(
                (settings.get("musetalk_quickstart_1_max_chars", 320) or 320) + 20, 80, 360
            )
            settings["musetalk_quickstart_2_target_chars"] = _bounded_int(
                (settings.get("musetalk_quickstart_2_target_chars", 130) or 130) + 10, 60, 240
            )
            settings["musetalk_quickstart_2_max_chars"] = _bounded_int(
                (settings.get("musetalk_quickstart_2_max_chars", 240) or 240) + 20, 80, 320
            )
            recommendation["notes"].append("Larger stream chunks should help MuseTalk warm into a steadier visual run.")
        elif avg_buffer_wait < 3500.0 and avg_first_audio_chunk > 1800.0:
            settings["stream_chunk_target_chars"] = _bounded_int(
                (settings.get("stream_chunk_target_chars", 85) or 85) - 8, 40, 220
            )
            settings["stream_chunk_max_chars"] = _bounded_int(
                (settings.get("stream_chunk_max_chars", 170) or 170) - 12, 60, 320
            )
            settings["musetalk_quickstart_1_target_chars"] = _bounded_int(
                (settings.get("musetalk_quickstart_1_target_chars", 170) or 170) - 8, 60, 260
            )
            settings["musetalk_quickstart_1_max_chars"] = _bounded_int(
                (settings.get("musetalk_quickstart_1_max_chars", 320) or 320) - 12, 80, 360
            )
            settings["musetalk_quickstart_2_target_chars"] = _bounded_int(
                (settings.get("musetalk_quickstart_2_target_chars", 130) or 130) - 8, 60, 240
            )
            settings["musetalk_quickstart_2_max_chars"] = _bounded_int(
                (settings.get("musetalk_quickstart_2_max_chars", 240) or 240) - 12, 80, 320
            )
            recommendation["notes"].append("Startup is visually healthy enough that slightly smaller stream chunks may speak earlier.")
        if avg_first_audio_chunk > 2200.0:
            settings["stream_force_flush_seconds"] = _bounded_float(
                (settings.get("stream_force_flush_seconds", 0.9) or 0.9) - 0.1, 0.2, 2.5
            )
            settings["stream_force_flush_later_seconds"] = _bounded_float(
                (settings.get("stream_force_flush_later_seconds", 1.4) or 1.4) - 0.1, 0.3, 3.0
            )
            recommendation["notes"].append("Earlier flush pressure should reduce time-to-first-voice.")
        if avg_render_ready > 0 and avg_render_ready < 5000.0 and avg_first_audio_chunk > 1600.0:
            settings["stream_first_chunk_min_chars"] = _bounded_int(
                (settings.get("stream_first_chunk_min_chars", 28) or 28) - 4, 10, 80
            )
    else:
        if avg_buffer_wait > 7000.0 or avg_spf > 120.0:
            settings["musetalk_chunk_target_chars"] = _bounded_int(
                (settings.get("musetalk_chunk_target_chars", 110) or 110) + 10, 60, 220
            )
            settings["musetalk_chunk_max_chars"] = _bounded_int(
                (settings.get("musetalk_chunk_max_chars", 220) or 220) + 20, 80, 320
            )
            settings["musetalk_quickstart_1_target_chars"] = _bounded_int(
                (settings.get("musetalk_quickstart_1_target_chars", 170) or 170) + 10, 60, 260
            )
            settings["musetalk_quickstart_1_max_chars"] = _bounded_int(
                (settings.get("musetalk_quickstart_1_max_chars", 320) or 320) + 20, 80, 360
            )
            settings["musetalk_quickstart_2_target_chars"] = _bounded_int(
                (settings.get("musetalk_quickstart_2_target_chars", 130) or 130) + 10, 60, 240
            )
            settings["musetalk_quickstart_2_max_chars"] = _bounded_int(
                (settings.get("musetalk_quickstart_2_max_chars", 240) or 240) + 20, 80, 320
            )
            recommendation["notes"].append("Non-stream MuseTalk appears to benefit from slightly larger visual chunks on this setup.")

    if not recommendation["notes"]:
        recommendation["notes"].append("Current settings already look well-balanced for the captured samples.")
    return recommendation


def _build_candidate_recommendation(snapshot, candidate_plan):
    if not candidate_plan:
        return _build_recommendation(snapshot, [])
    best = None
    scored = [candidate for candidate in candidate_plan if candidate.get("score") is not None]
    if scored:
        best = min(scored, key=lambda candidate: float(candidate.get("score") or 1e12))
    else:
        best = candidate_plan[0]
    notes = [
        "Dry Run searched from very eager chunking toward more stable chunking and chose the best measured balance.",
    ]
    if best.get("score") is not None:
        notes.append(f"Best candidate score: {float(best['score']):.1f} ms-equivalent startup cost.")
    return {
        "settings": dict(best.get("settings") or snapshot or {}),
        "notes": notes,
        "best_candidate_index": best.get("index"),
    }


def _best_candidate(candidate_plan):
    scored = [candidate for candidate in (candidate_plan or []) if candidate.get("score") is not None]
    if scored:
        return min(scored, key=lambda candidate: float(candidate.get("score") or 1e12))
    if candidate_plan:
        return candidate_plan[0]
    return None


def _compute_confidence(observations, target_samples):
    if not observations:
        return 0.0
    count_factor = min(1.0, len(observations) / max(int(target_samples or DEFAULT_TARGET_SAMPLES), 1))
    buffer_cv = _coefficient_of_variation(obs.get("first_chunk_buffer_wait_ms") for obs in observations)
    audio_cv = _coefficient_of_variation(obs.get("first_chunk_audio_start_latency_ms") for obs in observations)
    spf_cv = _coefficient_of_variation(obs.get("first_chunk_spf_ms") for obs in observations)
    variance_penalty = min(1.0, (buffer_cv + audio_cv + spf_cv) / 3.0)
    stability_factor = max(0.25, 1.0 - variance_penalty)
    return round(count_factor * stability_factor, 3)


def _compute_display_confidence(session_data):
    observations = session_data.get("observations", []) or []
    candidate_plan = session_data.get("candidate_plan", []) or []
    best_history = session_data.get("best_candidate_history", []) or []
    if not observations:
        return 0.0
    if session_data.get("auto_mode"):
        progress_factor = min(1.0, len(observations) / max(MAX_AUTO_SAMPLES, 1))
        repeated_best = 1.0 if len(best_history) >= AUTO_STABLE_ROUNDS_REQUIRED else min(1.0, len(best_history) / max(AUTO_STABLE_ROUNDS_REQUIRED, 1))
    else:
        target_samples = max(int(session_data.get("target_samples", DEFAULT_TARGET_SAMPLES) or 0), 1)
        progress_factor = min(1.0, len(observations) / target_samples)
        completed_candidates = sum(1 for candidate in candidate_plan if candidate.get("observations"))
        repeated_best = min(1.0, completed_candidates / max(len(candidate_plan), 1))

    score_values = [float(candidate.get("score")) for candidate in candidate_plan if candidate.get("score") is not None]
    if len(score_values) >= 2:
        spread = max(score_values) - min(score_values)
        score_clarity = min(1.0, max(0.0, spread / 1200.0))
    else:
        score_clarity = 0.5

    raw = 0.35 + (progress_factor * 0.35) + (repeated_best * 0.2) + (score_clarity * 0.1)
    return round(min(1.0, raw), 3)


def _persist_profile(session_data):
    payload = _load_json(PROFILES_PATH, {"profiles": {}, "history": []})
    profile_key = session_data.get("profile_key", "unknown")
    summary = _derive_summary(session_data.get("observations", []))
    payload["profiles"][profile_key] = {
        "hardware": session_data.get("hardware", {}),
        "updated_at": time.time(),
        "sample_count": len(session_data.get("observations", [])),
        "confidence": session_data.get("confidence", 0.0),
        "stability": session_data.get("stability", 0.0),
        "completion_reason": session_data.get("completion_reason", ""),
        "config_snapshot": session_data.get("config_snapshot", {}),
        "recommendation": session_data.get("recommendation", {}),
        "candidate_plan": session_data.get("candidate_plan", []),
        "summary": summary,
    }
    payload["history"].append(
        {
            "session_id": session_data.get("session_id"),
            "profile_key": profile_key,
            "ended_at": time.time(),
            "sample_count": len(session_data.get("observations", [])),
            "confidence": session_data.get("confidence", 0.0),
            "stability": session_data.get("stability", 0.0),
        }
    )
    payload["history"] = payload["history"][-32:]
    _save_json(PROFILES_PATH, payload)


def _materialize_profile_payload(profile_key, profile):
    profile = deepcopy(profile or {})
    config_snapshot = dict(profile.get("config_snapshot") or {})
    recommendation = dict(profile.get("recommendation") or {})
    effective_settings = dict(config_snapshot)
    effective_settings.update(dict(recommendation.get("settings") or {}))
    return {
        "profile_key": profile_key,
        "hardware": dict(profile.get("hardware") or {}),
        "updated_at": float(profile.get("updated_at", time.time()) or time.time()),
        "sample_count": int(profile.get("sample_count", 0) or 0),
        "confidence": float(profile.get("confidence", 0.0) or 0.0),
        "stability": float(profile.get("stability", 0.0) or 0.0),
        "completion_reason": str(profile.get("completion_reason", "") or ""),
        "config_snapshot": config_snapshot,
        "recommendation": recommendation,
        "summary": dict(profile.get("summary") or {}),
        "settings_to_apply": effective_settings,
    }


def suggest_profile_name(profile):
    payload = _materialize_profile_payload(profile.get("profile_key", "unknown"), profile)
    settings = payload.get("settings_to_apply", {})
    avatar = _safe_slug(settings.get("avatar_mode", "avatar"))
    stream = "stream" if bool(settings.get("stream_mode", False)) else "nonstream"
    backend = _safe_slug(settings.get("tts_backend", "tts"))
    vram = _safe_slug(settings.get("musetalk_vram_mode", "default"))
    stamp = time.strftime("%Y%m%d_%H%M", time.localtime(payload.get("updated_at", time.time())))
    return f"{avatar}_{stream}_{backend}_{vram}_{stamp}"


def list_performance_profiles():
    _ensure_runtime_dir()
    items = []
    for path in sorted(
        (os.path.join(PERFORMANCE_PROFILES_DIR, name) for name in os.listdir(PERFORMANCE_PROFILES_DIR)),
        key=lambda p: os.path.getmtime(p),
        reverse=True,
    ):
        if not path.lower().endswith(".json") or not os.path.isfile(path):
            continue
        payload = _load_json(path, {})
        name = os.path.splitext(os.path.basename(path))[0]
        items.append(
            {
                "name": name,
                "display_name": str(payload.get("display_name", payload.get("saved_name", name)) or name),
                "description": str(payload.get("description", "") or ""),
                "bundled": bool(payload.get("bundled", False)),
                "recommended": bool(payload.get("recommended", False)),
                "path": path,
                "updated_at": float(payload.get("updated_at", os.path.getmtime(path)) or os.path.getmtime(path)),
                "stream_mode": bool((payload.get("settings_to_apply") or {}).get("stream_mode", False)),
                "tts_backend": str((payload.get("settings_to_apply") or {}).get("tts_backend", "") or ""),
                "musetalk_vram_mode": str((payload.get("settings_to_apply") or {}).get("musetalk_vram_mode", "") or ""),
                "confidence": float(payload.get("confidence", 0.0) or 0.0),
                "stability": float(payload.get("stability", 0.0) or 0.0),
                "sample_count": int(payload.get("sample_count", 0) or 0),
            }
        )
    return items


def load_performance_profile(name):
    if not name:
        return None
    path = os.path.join(PERFORMANCE_PROFILES_DIR, f"{name}.json")
    if not os.path.exists(path):
        return None
    return _load_json(path, {})


def save_named_performance_profile(name, source_profile=None, settings_override=None):
    payload_source = source_profile or get_latest_profile()
    if not payload_source or not name:
        return None
    payload = _materialize_profile_payload(payload_source.get("profile_key", "unknown"), payload_source)
    override = dict(settings_override or {})
    if override:
        payload["config_snapshot"] = {**dict(payload.get("config_snapshot") or {}), **override}
        payload["settings_to_apply"] = {**dict(payload.get("settings_to_apply") or {}), **override}
    payload["saved_name"] = str(name)
    payload["saved_at"] = time.time()
    path = os.path.join(PERFORMANCE_PROFILES_DIR, f"{name}.json")
    _save_json(path, payload)
    _append_log(f"[DryRun] Performance profile saved name={name} path={path}")
    return path


def delete_performance_profile(name):
    if not name:
        return False
    path = os.path.join(PERFORMANCE_PROFILES_DIR, f"{name}.json")
    if not os.path.exists(path):
        return False
    os.remove(path)
    _append_log(f"[DryRun] Performance profile deleted name={name}")
    return True


def _serialize_session():
    serializable = {
        "session": _session,
        "active_replies": list(_replies.values()),
    }
    _save_json(SESSION_PATH, serializable)


def _update_reply_derived_metrics(reply):
    if not isinstance(reply, dict):
        return
    count = int(reply.get("followup_headroom_count", 0) or 0)
    total = float(reply.get("followup_headroom_sum_ms", 0.0) or 0.0)
    if count > 0:
        reply["avg_followup_headroom_ms"] = round(total / count, 1)
    quality_count = int(reply.get("chunk_quality_count", 0) or 0)
    quality_total = float(reply.get("chunk_quality_sum", 0.0) or 0.0)
    if quality_count > 0:
        reply["avg_chunk_quality"] = round(quality_total / quality_count, 3)
    chars_count = int(reply.get("chunk_chars_count", 0) or 0)
    chars_total = float(reply.get("chunk_chars_sum", 0.0) or 0.0)
    if chars_count > 0:
        reply["avg_chunk_chars"] = round(chars_total / chars_count, 1)


def _recompute_session_scores():
    global _session
    if _session is None:
        return
    candidate_plan = list(_session.get("candidate_plan", []) or [])
    for candidate in candidate_plan:
        candidate["score"] = _score_candidate(candidate.get("observations", []))
    _session["candidate_plan"] = candidate_plan
    best = _best_candidate(candidate_plan)
    completed_candidates = sum(1 for candidate in candidate_plan if candidate.get("observations"))
    _session["active_candidate_index"] = min(completed_candidates, max(len(candidate_plan) - 1, 0))
    _session["stability"] = _compute_confidence(
        _session.get("observations", []),
        len(candidate_plan) or max(int(_session.get("target_samples", DEFAULT_TARGET_SAMPLES) or 0), 1),
    )
    _session["confidence"] = max(
        float(_session.get("confidence", 0.0) or 0.0),
        _compute_display_confidence(_session),
    )
    _session["recommendation"] = _build_candidate_recommendation(
        _session.get("config_snapshot", {}),
        candidate_plan,
    )
    return best


def _ensure_live_session_loaded():
    global _session, _replies
    if _session is not None:
        return
    payload = _load_json(SESSION_PATH, {})
    session = payload.get("session")
    if session:
        _session = deepcopy(session)
        _replies = {
            item.get("reply_id"): dict(item)
            for item in (payload.get("active_replies") or [])
            if item.get("reply_id")
        }


def start_session(runtime_config, target_samples=DEFAULT_TARGET_SAMPLES, label="", auto_replies=False):
    global _session, _replies
    with _lock:
        snapshot = _snapshot_config(runtime_config)
        _session = {
            "active": True,
            "session_id": uuid.uuid4().hex[:10],
            "label": str(label or "").strip(),
            "started_at": time.time(),
            "target_samples": max(0, int(target_samples or DEFAULT_TARGET_SAMPLES)),
            "auto_mode": int(target_samples or DEFAULT_TARGET_SAMPLES) <= 0,
            "auto_replies": bool(auto_replies),
            "profile_key": _build_profile_key(snapshot),
            "hardware": _hardware_fingerprint(),
            "config_snapshot": snapshot,
            "observations": [],
            "candidate_plan": _build_candidate_plan(snapshot, target_samples),
            "active_candidate_index": 0,
            "search_round": 1,
            "search_phase": "startup" if bool(snapshot.get("stream_mode", False)) else "single",
            "best_candidate_history": [],
            "auto_reply_index": 0,
            "completion_reason": "",
            "recommendation": {"settings": dict(snapshot), "notes": ["Dry Run armed. Collecting reply samples..."]},
            "confidence": 0.0,
            "stability": 0.0,
            "complete": False,
        }
        _session["recommendation"] = _build_candidate_recommendation(snapshot, _session["candidate_plan"])
        _replies = {}
        _append_log(
            "[DryRun] Session started "
            f"id={_session['session_id']} profile={_session['profile_key']} "
            f"mode={'auto' if _session['auto_mode'] else 'fixed'} "
            f"stream={bool(snapshot.get('stream_mode', False))} "
            f"backend={snapshot.get('tts_backend')} "
            f"phase={_session.get('search_phase')} "
            f"candidates={len(_session.get('candidate_plan', []))}"
        )
        _serialize_session()
        return deepcopy(_session)


def stop_session(reason="manual"):
    global _session, _replies
    with _lock:
        _ensure_live_session_loaded()
        if _session is None:
            return None
        _session["active"] = False
        _session["stopped_at"] = time.time()
        _session["stop_reason"] = str(reason or "manual")
        _append_log(
            "[DryRun] Session stopped "
            f"id={_session.get('session_id')} reason={_session['stop_reason']} "
            f"samples={len(_session.get('observations', []) or [])} "
            f"confidence={float(_session.get('confidence', 0.0) or 0.0):.2f} "
            f"stability={float(_session.get('stability', 0.0) or 0.0):.2f}"
        )
        _persist_profile(_session)
        _serialize_session()
        result = deepcopy(_session)
        _session = None
        _replies = {}
        return result


def begin_reply(runtime_config, streamed=False, proactive=False):
    with _lock:
        _ensure_live_session_loaded()
        if not _session or not _session.get("active"):
            return None
        reply_id = uuid.uuid4().hex[:12]
        _replies[reply_id] = {
            "reply_id": reply_id,
            "started_at": time.time(),
            "streamed": bool(streamed),
            "proactive": bool(proactive),
            "candidate_index": int(_session.get("active_candidate_index", 0) or 0),
            "config_snapshot": _snapshot_config(runtime_config),
        }
        candidate_plan = _session.get("candidate_plan", []) or []
        candidate_index = int(_session.get("active_candidate_index", 0) or 0)
        candidate_label = None
        if candidate_plan:
            candidate_index = max(0, min(candidate_index, len(candidate_plan) - 1))
            candidate_label = (candidate_plan[candidate_index] or {}).get("label")
        _append_log(
            "[DryRun] Reply started "
            f"reply_id={reply_id} "
            f"candidate={candidate_label} "
            f"phase={_session.get('search_phase')} "
            f"round={_session.get('search_round')}"
        )
        _serialize_session()
        return reply_id


def record_reply_metric(reply_id, key, value):
    with _lock:
        _ensure_live_session_loaded()
        if not reply_id:
            return
        if reply_id in _replies:
            _replies[reply_id][key] = value
            _update_reply_derived_metrics(_replies[reply_id])
            _serialize_session()
            return
        if not _session:
            return
        updated = False
        for observation in _session.get("observations", []):
            if observation.get("reply_id") == reply_id:
                observation[key] = value
                _update_reply_derived_metrics(observation)
                started_at = observation.get("started_at")
                if started_at:
                    if key == "first_audio_chunk_at":
                        observation["first_audio_chunk_latency_ms"] = round((float(value) - started_at) * 1000.0, 1)
                    elif key == "first_chunk_published_at":
                        observation["first_chunk_published_latency_ms"] = round((float(value) - started_at) * 1000.0, 1)
                    elif key == "first_chunk_audio_start_at":
                        observation["first_chunk_audio_start_latency_ms"] = round((float(value) - started_at) * 1000.0, 1)
                    elif key == "first_token_at":
                        observation["first_token_latency_ms"] = round((float(value) - started_at) * 1000.0, 1)
                updated = True
                break
        if updated:
            for candidate in _session.get("candidate_plan", []) or []:
                for observation in candidate.get("observations", []) or []:
                    if observation.get("reply_id") == reply_id:
                        observation[key] = value
                        _update_reply_derived_metrics(observation)
            if key in (
                "first_chunk_render_ready_ms",
                "first_chunk_spf_ms",
                "first_chunk_frame_count",
                "avg_followup_headroom_ms",
                "min_followup_headroom_ms",
            ):
                _append_log(
                    "[DryRun] Late metric merged "
                    f"reply_id={reply_id} key={key} value={value}"
                )
            _recompute_session_scores()
        _serialize_session()


def accumulate_reply_metric(reply_id, key, delta):
    with _lock:
        _ensure_live_session_loaded()
        if not reply_id:
            return
        if reply_id in _replies:
            _replies[reply_id][key] = float(_replies[reply_id].get(key, 0.0) or 0.0) + float(delta)
            _update_reply_derived_metrics(_replies[reply_id])
            _serialize_session()
            return
        if not _session:
            return
        updated = False
        for observation in _session.get("observations", []):
            if observation.get("reply_id") == reply_id:
                observation[key] = float(observation.get(key, 0.0) or 0.0) + float(delta)
                _update_reply_derived_metrics(observation)
                updated = True
                break
        if updated:
            for candidate in _session.get("candidate_plan", []) or []:
                for observation in candidate.get("observations", []) or []:
                    if observation.get("reply_id") == reply_id:
                        observation[key] = float(observation.get(key, 0.0) or 0.0) + float(delta)
                        _update_reply_derived_metrics(observation)
            _recompute_session_scores()
        _serialize_session()


def update_reply_min_metric(reply_id, key, value):
    with _lock:
        _ensure_live_session_loaded()
        if not reply_id:
            return
        def _set_min(record):
            current = record.get(key)
            if current is None:
                record[key] = value
            else:
                record[key] = min(float(current), float(value))
            _update_reply_derived_metrics(record)
        if reply_id in _replies:
            _set_min(_replies[reply_id])
            _serialize_session()
            return
        if not _session:
            return
        updated = False
        for observation in _session.get("observations", []):
            if observation.get("reply_id") == reply_id:
                _set_min(observation)
                updated = True
                break
        if updated:
            for candidate in _session.get("candidate_plan", []) or []:
                for observation in candidate.get("observations", []) or []:
                    if observation.get("reply_id") == reply_id:
                        _set_min(observation)
            _recompute_session_scores()
        _serialize_session()


def record_reply_event(reply_id, key):
    record_reply_metric(reply_id, key, time.time())


def finalize_reply(reply_id):
    with _lock:
        _ensure_live_session_loaded()
        if not reply_id or not _session:
            return None
        existing = None
        for observation in _session.get("observations", []):
            if observation.get("reply_id") == reply_id:
                existing = observation
                break
        if existing is not None:
            _recompute_session_scores()
            _persist_profile(_session)
            _serialize_session()
            return deepcopy(existing)
        if reply_id not in _replies:
            return None
        reply = dict(_replies.pop(reply_id))
        started_at = reply.get("started_at")
        if started_at:
            for source_key, target_key in (
                ("first_token_at", "first_token_latency_ms"),
                ("first_audio_chunk_at", "first_audio_chunk_latency_ms"),
                ("first_chunk_published_at", "first_chunk_published_latency_ms"),
                ("first_chunk_audio_start_at", "first_chunk_audio_start_latency_ms"),
            ):
                if reply.get(source_key) is not None:
                    reply[target_key] = round((float(reply[source_key]) - started_at) * 1000.0, 1)
        _session["observations"].append(reply)
        _session["observations"] = _session["observations"][-16:]
        candidate_index = int(reply.get("candidate_index", 0) or 0)
        candidate_plan = list(_session.get("candidate_plan", []))
        candidate_label = None
        if 0 <= candidate_index < len(candidate_plan):
            candidate_plan[candidate_index]["observations"].append(reply)
            candidate_label = candidate_plan[candidate_index].get("label")
            _session["candidate_plan"] = candidate_plan
        _recompute_session_scores()
        _append_log(
            "[DryRun] Reply finalized "
            f"reply_id={reply_id} candidate={candidate_label} "
            f"first_audio={reply.get('first_audio_chunk_latency_ms')} "
            f"buffer_wait={reply.get('first_chunk_buffer_wait_ms')} "
            f"audio_start={reply.get('first_chunk_audio_start_latency_ms')} "
            f"render_ready={reply.get('first_chunk_render_ready_ms')} "
            f"spf={reply.get('first_chunk_spf_ms')} "
            f"headroom={reply.get('avg_followup_headroom_ms')} "
            f"quality={reply.get('avg_chunk_quality')} "
            f"avg_chars={reply.get('avg_chunk_chars')}"
        )
        completed_candidates = sum(1 for candidate in candidate_plan if candidate.get("observations"))
        round_complete = bool(completed_candidates >= len(candidate_plan) and len(candidate_plan) > 0)
        best = _best_candidate(_session.get("candidate_plan", []))
        if best is not None:
            _session["best_candidate_history"].append(
                {
                    "round": int(_session.get("search_round", 1) or 1),
                    "label": best.get("label"),
                    "score": best.get("score"),
                }
            )
            _session["best_candidate_history"] = _session["best_candidate_history"][-8:]

        if round_complete and _session.get("auto_mode"):
            history = _session.get("best_candidate_history", [])
            recent = history[-AUTO_STABLE_ROUNDS_REQUIRED:]
            stable = (
                len(recent) >= AUTO_STABLE_ROUNDS_REQUIRED
                and len({entry.get("label") for entry in recent}) == 1
                and len({entry.get("score") for entry in recent}) == 1
            )
            enough_rounds = int(_session.get("search_round", 1) or 1) >= 2
            total_samples = len(_session.get("observations", []) or [])
            hit_round_cap = int(_session.get("search_round", 1) or 1) >= MAX_AUTO_ROUNDS
            hit_sample_cap = total_samples >= MAX_AUTO_SAMPLES
            search_phase = str(_session.get("search_phase", "single") or "single")
            if (
                search_phase == "startup"
                and bool(_session.get("config_snapshot", {}).get("stream_mode", False))
            ):
                _append_log(
                    "[DryRun] Startup phase complete "
                    f"best={best.get('label') if best else None} "
                    f"score={best.get('score') if best else None}"
                )
                next_round = int(_session.get("search_round", 1) or 1) + 1
                _session["search_round"] = next_round
                _session["search_phase"] = "steady"
                _session["candidate_plan"] = []
                startup_best_settings = (best or {}).get("settings", {})
                steady_candidates = _build_stream_steady_candidates(startup_best_settings)
                for index, candidate_settings in enumerate(steady_candidates):
                    merged = dict(_session.get("config_snapshot", {}) or {})
                    merged.update(startup_best_settings or {})
                    merged.update(candidate_settings)
                    _session["candidate_plan"].append(
                        {
                            "index": index,
                            "label": f"Steady {index + 1}",
                            "settings": merged,
                            "observations": [],
                            "score": None,
                        }
                    )
                _session["active_candidate_index"] = 0
                _session["recommendation"] = _build_candidate_recommendation(
                    _session.get("config_snapshot", {}),
                    _session["candidate_plan"],
                )
                _append_log(
                    "[DryRun] Entering steady phase "
                    f"round={_session.get('search_round')} "
                    f"candidates={len(_session.get('candidate_plan', []))}"
                )
                _persist_profile(_session)
                _serialize_session()
                return deepcopy(reply)

            if (_session.get("stability", 0.0) >= RECOMMENDED_CONFIDENCE and enough_rounds) or stable or hit_round_cap or hit_sample_cap:
                if (_session.get("stability", 0.0) >= RECOMMENDED_CONFIDENCE and enough_rounds):
                    _session["completion_reason"] = "stability threshold reached"
                elif stable:
                    _session["completion_reason"] = "best candidate stabilized across rounds"
                elif hit_sample_cap:
                    _session["completion_reason"] = "reached max auto-sample budget"
                else:
                    _session["completion_reason"] = "reached max auto-search rounds"
                _session["complete"] = True
                _append_log(
                    "[DryRun] Complete "
                    f"reason={_session.get('completion_reason')} "
                    f"best={best.get('label') if best else None} "
                    f"score={best.get('score') if best else None} "
                    f"samples={len(_session.get('observations', []) or [])} "
                    f"confidence={float(_session.get('confidence', 0.0) or 0.0):.2f} "
                    f"stability={float(_session.get('stability', 0.0) or 0.0):.2f}"
                )
            else:
                next_round = int(_session.get("search_round", 1) or 1) + 1
                _session["search_round"] = next_round
                _session["search_phase"] = "refine"
                _session["candidate_plan"] = _build_refined_candidate_plan(
                    _session.get("config_snapshot", {}),
                    (best or {}).get("settings", {}),
                    next_round,
                )
                _session["active_candidate_index"] = 0
                _session["recommendation"] = _build_candidate_recommendation(
                    _session.get("config_snapshot", {}),
                    _session["candidate_plan"],
                )
                _append_log(
                    "[DryRun] Refining search "
                    f"round={_session.get('search_round')} "
                    f"best={best.get('label') if best else None} "
                    f"score={best.get('score') if best else None}"
                )
                _persist_profile(_session)
                _serialize_session()
                return deepcopy(reply)
        else:
            _session["complete"] = bool(round_complete and len(candidate_plan) > 0)
            if _session["complete"]:
                _session["completion_reason"] = "completed requested candidate count"
                _append_log(
                    "[DryRun] Complete "
                    f"reason={_session.get('completion_reason')} "
                    f"samples={len(_session.get('observations', []) or [])}"
                )

        _persist_profile(_session)
        _serialize_session()
        return deepcopy(reply)


def get_status():
    with _lock:
        if _session is not None:
            return deepcopy(_session)
        payload = _load_json(SESSION_PATH, {})
        session = payload.get("session")
        return deepcopy(session) if session else None


def get_latest_profile():
    with _lock:
        payload = _load_json(PROFILES_PATH, {"profiles": {}})
        profiles = payload.get("profiles", {})
        if not profiles:
            return None
        latest_key = max(
            profiles.keys(),
            key=lambda key: float((profiles.get(key) or {}).get("updated_at", 0.0) or 0.0),
        )
        latest = deepcopy(profiles.get(latest_key))
        latest["profile_key"] = latest_key
        return latest


def get_current_candidate_settings():
    with _lock:
        _ensure_live_session_loaded()
        if not _session or not _session.get("active"):
            return None
        candidate_plan = _session.get("candidate_plan", []) or []
        if not candidate_plan:
            return None
        index = int(_session.get("active_candidate_index", 0) or 0)
        index = max(0, min(index, len(candidate_plan) - 1))
        candidate = candidate_plan[index]
        return {
            "index": index,
            "label": candidate.get("label"),
            "settings": dict(candidate.get("settings") or {}),
            "score": candidate.get("score"),
        }


def auto_replies_enabled():
    with _lock:
        _ensure_live_session_loaded()
        return bool(_session and _session.get("active") and _session.get("auto_replies"))


def next_auto_reply():
    with _lock:
        _ensure_live_session_loaded()
        if not _session or not _session.get("active") or not _session.get("auto_replies"):
            return None
        index = int(_session.get("auto_reply_index", 0) or 0)
        prompt = AUTO_REPLY_PROMPTS[index % len(AUTO_REPLY_PROMPTS)]
        _session["auto_reply_index"] = index + 1
        _serialize_session()
        return prompt
