"""ComfyUI checkpoint detection and prompt rules for Visual Reply.

The detector works on already-loaded workflow data; callers perform disk or
network I/O on their existing worker paths, never in a Qt property getter.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePath
import re
from threading import Lock
from typing import Mapping

from addons.visual_reply.providers import provider_settings_from_config


RULE_LABELS = {
    "auto": "Auto Detect",
    "pony_realism": "Pony Realism",
    "pony_xl": "Pony XL / Pony Diffusion",
    "cyberillustrious_play_v4": "CyberIllustrious Semi-Realistic - Play V4",
    "sdxl_photo": "SDXL Photorealistic",
    "sdxl_general": "SDXL General / Artistic",
    "flux": "FLUX",
    "sd15": "SD 1.5",
    "generic": "Generic / Custom",
}
RULE_OPTIONS = tuple(RULE_LABELS)
_PONY_PREFIX = "score_9, score_8_up, score_7_up"
# Cyberdelia's Play V4 examples (Civitai model 1991867, version 3090637).
_CYBERILLUSTRIOUS_PREFIX = "masterpiece, best_quality"
_CYBERILLUSTRIOUS_NEGATIVE = ("lowres", "worst_quality", "bad_quality")
_MODEL_INPUTS = ("ckpt_name", "checkpoint", "checkpoint_name", "unet_name", "model_name", "filename")
_cache_lock = Lock()
_detection_cache: dict[tuple[str, str], "ModelDetection"] = {}


@dataclass(frozen=True, slots=True)
class ModelDetection:
    model_name: str = ""
    rules: str = "generic"
    status: str = "Model unavailable; using Generic rules"


def normalize_rules(value: object) -> str:
    value = str(value or "auto").strip().lower()
    return value if value in RULE_LABELS else "auto"


def effective_rules(selection: object, detected: ModelDetection) -> str:
    selected = normalize_rules(selection)
    return detected.rules if selected == "auto" else selected


def _model_family(name: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "", PurePath(name.replace("\\", "/")).name.lower())
    if normalized == "cyberillustrioussemiplayv4safetensors":
        return "cyberillustrious_play_v4"
    if "ponyrealism" in normalized:
        return "pony_realism"
    if "ponydiffusion" in normalized or "ponyxl" in normalized:
        return "pony_xl"
    if "realvisxl" in normalized or "realisticvisionxl" in normalized:
        return "sdxl_photo"
    if "flux" in normalized:
        return "flux"
    if "sdxl" in normalized or "stablediffusionxl" in normalized:
        return "sdxl_general"
    if "sd15" in normalized or "stablediffusionv15" in normalized or "v15pruned" in normalized:
        return "sd15"
    return "generic"


def _api_nodes(payload: object) -> dict[str, dict]:
    if not isinstance(payload, dict):
        return {}
    if isinstance(payload.get("nodes"), list):
        ui_nodes = {
            str(item.get("id")): item
            for item in payload["nodes"]
            if isinstance(item, dict) and item.get("id") is not None
        }
        links = {}
        for link in payload.get("links") or []:
            if isinstance(link, list) and len(link) >= 3:
                links[str(link[0])] = [str(link[1]), link[2]]
        nodes = {}
        for item in payload["nodes"]:
            if not isinstance(item, dict):
                continue
            node_id = str(item.get("id") or "")
            class_type = str(item.get("type") or "")
            if not node_id or not class_type:
                continue
            inputs = {}
            for entry in item.get("inputs") or []:
                if isinstance(entry, dict) and entry.get("link") is not None:
                    link = links.get(str(entry["link"]))
                    if link:
                        inputs[str(entry.get("name") or "")] = link
            if _is_model_loader(class_type):
                for key in _MODEL_INPUTS:
                    linked = inputs.get(key)
                    if not isinstance(linked, list) or not linked:
                        continue
                    source = ui_nodes.get(str(linked[0]), {})
                    if str(source.get("type") or "") != "PrimitiveNode":
                        continue
                    primitive_values = source.get("widgets_values") or []
                    if isinstance(primitive_values, list) and primitive_values and isinstance(primitive_values[0], str):
                        inputs[key] = primitive_values[0]
                widgets = item.get("widgets_values") or []
                if isinstance(widgets, dict):
                    for key in _MODEL_INPUTS:
                        if isinstance(widgets.get(key), str) and widgets[key].strip():
                            inputs[key] = widgets[key]
                            break
                elif isinstance(widgets, list) and widgets and isinstance(widgets[0], str):
                    inputs["ckpt_name"] = widgets[0]
            nodes[node_id] = {"class_type": class_type, "inputs": inputs}
        return nodes
    if not payload or not all(isinstance(node, dict) and "class_type" in node for node in payload.values()):
        return {}
    return {str(node_id): node for node_id, node in payload.items()}


def _is_model_loader(class_type: str) -> bool:
    name = class_type.lower()
    return (
        "checkpointloader" in name
        or name in {"unetloader", "diffusionmodelloader"}
        or ("diffusionmodel" in name and "loader" in name)
    )


def _model_filename(inputs: Mapping[str, object]) -> str:
    for key in _MODEL_INPUTS:
        value = inputs.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip().replace("\\", "/").split("/")[-1]
    return ""


def detect_workflow_model(payload: object) -> ModelDetection:
    """Select only loaders upstream of the primary generation sampler."""
    nodes = _api_nodes(payload)
    samplers = [
        node_id for node_id, node in nodes.items()
        if "ksampler" in str(node.get("class_type") or "").lower()
        or "samplercustom" in str(node.get("class_type") or "").lower()
    ]
    if not samplers:
        return ModelDetection(status="No connected sampler/model found; using Generic rules")
    def has_empty_latent(node_id: str) -> bool:
        inputs = nodes[node_id].get("inputs") or {}
        latent = inputs.get("latent_image") if isinstance(inputs, dict) else None
        if not isinstance(latent, (list, tuple)) or len(latent) < 2:
            return False
        upstream = nodes.get(str(latent[0]), {})
        return "emptylatent" in str(upstream.get("class_type") or "").lower()

    sampler = next((node_id for node_id in samplers if has_empty_latent(node_id)), samplers[0])
    sampler_inputs = nodes[sampler].get("inputs") or {}
    if not isinstance(sampler_inputs, dict):
        return ModelDetection(status="Malformed sampler inputs; using Generic rules")
    roots = [sampler_inputs.get(key) for key in ("model", "positive", "negative", "guider")]
    pending = [str(value[0]) for value in roots if isinstance(value, (list, tuple)) and len(value) >= 2]
    seen: set[str] = set()
    names: set[str] = set()
    while pending:
        node_id = pending.pop()
        if node_id in seen:
            continue
        seen.add(node_id)
        node = nodes.get(node_id)
        if not isinstance(node, dict):
            continue
        class_type = str(node.get("class_type") or "")
        inputs = node.get("inputs") or {}
        if not isinstance(inputs, dict):
            continue
        if _is_model_loader(class_type):
            filename = _model_filename(inputs)
            if filename:
                names.add(filename)
            continue
        for value in inputs.values():
            if isinstance(value, (list, tuple)) and len(value) >= 2 and str(value[0]) in nodes:
                pending.append(str(value[0]))
    if len(names) != 1:
        status = "Multiple connected models; using Generic rules" if names else "Connected model unavailable; using Generic rules"
        return ModelDetection(status=status)
    name = names.pop()
    rules = _model_family(name)
    return ModelDetection(name, rules, "Detected" if rules != "generic" else "Unknown model; using Generic rules")


_SCENE_INSTRUCTION = (
    "Write one coherent English image scene from the latest conversation and assistant reply. "
    "Prioritize the actual subject and action, established persona traits when relevant, then setting, "
    "composition, lighting and mood. For abstract topics use a grounded visual metaphor; for technical "
    "topics depict the discussed concept. Avoid unrelated people, contradictory details, and quality-tag spam. "
    "Return only the positive prompt inside the existing [visualize: ...] tag, with no JSON or preface."
)
_MODEL_INSTRUCTIONS = {
    "cyberillustrious_play_v4": (
        "Begin with masterpiece, best_quality exactly once. Use concise, comma-separated "
        "Danbooru-style visual tags with underscores for established multiword tags. "
        "Order the scene as subject/count and identity, appearance, clothing, action/pose, "
        "setting, composition, lighting and mood. Preserve clear subject relationships; "
        "use short descriptive English when tags cannot express them. Describe adults "
        "unambiguously where relevant. Match the requested medium; use realistic, "
        "photorealistic only when the scene calls for that style. Do not invent a person "
        "for landscapes or objects. Avoid Pony score tags, BREAK, negative-prompt terms, "
        "LoRA commands, and long stacks of quality tags."
    ),
    "pony_realism": "Begin with score_9, score_8_up, score_7_up. Then use comma-separated Pony-style visual descriptors and cinematic photographic detail when the scene fits. Aim for roughly 25–45 meaningful descriptors for a complex scene; favor clarity over count. Put subject and action first; describe adults unambiguously where relevant. Never add BREAK unless the workflow explicitly supports it.",
    "pony_xl": "Begin with score_9, score_8_up, score_7_up. Use comma-separated Pony-style visual tags and the scene's actual medium, including illustration or fantasy when appropriate; do not force photorealism. Aim for roughly 25–45 meaningful descriptors for a complex scene. Never add BREAK unless the workflow explicitly supports it.",
    "sdxl_photo": "Use natural descriptive English, specific photographic framing, plausible materials and lighting. Do not use Pony score tags.",
    "sdxl_general": "Use flexible scene description that respects the intended medium, whether photography, illustration or painting. Do not use Pony score tags.",
    "flux": "Use coherent natural language with clear subject relationships, composition and lighting. Avoid long tag lists and Pony score tags.",
    "sd15": "Use a short structured comma-separated prompt, highest-priority subject and action first. Do not use Pony score tags.",
    "generic": "Use clear model-neutral subject, action, setting, composition and lighting. Do not add model-specific score tags.",
}


def model_instruction(rules: str) -> str:
    return f"{_SCENE_INSTRUCTION} {refinement_instruction(rules)}"


def refinement_instruction(rules: str) -> str:
    """Model guidance without automatic reply context or visualize-tag output."""
    return _MODEL_INSTRUCTIONS.get(rules, _MODEL_INSTRUCTIONS["generic"])


def compose_positive_prompt(prompt: str, rules: str) -> str:
    """Keep literal encoder input clean; instructions themselves never go here."""
    text = str(prompt or "").strip()
    if rules == "cyberillustrious_play_v4":
        text = re.sub(r"(?i)\b(?:score_\d+(?:_up)?|BREAK)\b\s*,?\s*", "", text)
        text = re.sub(r"(?i)\b(?:masterpiece|best[ _]quality)\b\s*,?\s*", "", text).strip(" ,")
        return f"{_CYBERILLUSTRIOUS_PREFIX}, {text}" if text else _CYBERILLUSTRIOUS_PREFIX
    if rules not in {"pony_realism", "pony_xl"}:
        return text
    text = re.sub(r"(?i)\b(?:score_9|score_8_up|score_7_up)\b\s*,?\s*", "", text).strip()
    text = re.sub(r"(?i)\bBREAK\b\s*,?\s*", "", text).strip(" ,")
    return f"{_PONY_PREFIX}, {text}" if text else _PONY_PREFIX


def compose_negative_prompt(prompt: str, rules: str) -> str:
    """Adapt Play V4 quality tags while retaining custom rendering exclusions."""
    if rules != "cyberillustrious_play_v4":
        return str(prompt or "").strip()
    text = re.sub(r"(?i)\bscore_\d+(?:_up)?\b\s*,?\s*", "", str(prompt or ""))
    terms = list(_CYBERILLUSTRIOUS_NEGATIVE)
    seen = set(terms)
    for term in text.split(","):
        term = term.strip()
        key = term.casefold().replace(" ", "_")
        if term and key not in seen:
            terms.append(term)
            seen.add(key)
    return ", ".join(terms)


def remember_detection(workflow_path: str, base_url: str, detected: ModelDetection) -> None:
    with _cache_lock:
        _detection_cache[(str(workflow_path), str(base_url))] = detected


def cached_detection(workflow_path: str, base_url: str) -> ModelDetection:
    with _cache_lock:
        return _detection_cache.get((str(workflow_path), str(base_url)), ModelDetection())


def rules_for_config(config: Mapping[str, object]) -> str:
    """Resolve frozen chat instruction from settings and completed detection only."""
    if str(config.get("visual_reply_provider") or "openai").lower() != "comfyui":
        return ""
    from addons.visual_reply.runtime_config import VisualReplyRuntime

    settings = provider_settings_from_config(config).get("comfyui", {})
    selected = normalize_rules(settings.get("prompting_rules", "auto"))
    runtime = VisualReplyRuntime(lambda: dict(config))
    return effective_rules(selected, cached_detection(runtime.workflow_path(), runtime.base_url()))
