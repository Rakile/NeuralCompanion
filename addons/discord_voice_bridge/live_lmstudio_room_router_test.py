from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from runtime_server import DiscordVoiceRuntimeServer


BASE_URL = os.environ.get("LMSTUDIO_BASE_URL", "http://127.0.0.1:1234/v1").rstrip("/")
API_ROOT = BASE_URL[:-3] if BASE_URL.endswith("/v1") else BASE_URL
MODEL = os.environ.get("LMSTUDIO_MODEL", "").strip()


CANDIDATES = [
    {"id": "echo", "name": "Echo", "call_names": "Echo, Ekko", "persona_hint": "bold debate companion"},
    {"id": "mira", "name": "Mira", "call_names": "Mira", "persona_hint": "sharp analyst"},
    {"id": "nova", "name": "Nova", "call_names": "Nova, Novak", "persona_hint": "curious moderator"},
]


@dataclass(frozen=True)
class Scenario:
    name: str
    speaker: str
    utterance: str
    expected_answer: bool
    expected_target: str = ""
    speaker_bot_id: str = ""
    policy_overrides: dict[str, Any] | None = None
    allow_any_target: tuple[str, ...] = ()


DEFAULT_POLICY = {
    "human_to_bot_routing": True,
    "bot_to_bot_routing": True,
    "exclude_speaker_from_targets": True,
    "allow_group_invitation_routing": True,
    "allow_open_room_invitation_routing": True,
    "self_route_policy": "ignore",
    "default_when_uncertain": True,
    "uncertain_fallback_target": "self",
}


SCENARIOS = [
    Scenario(
        name="human_direct_named_bot",
        speaker="Rakila",
        utterance="Mira, can you give us a clean summary of the argument?",
        expected_answer=True,
        expected_target="mira",
    ),
    Scenario(
        name="human_open_room_invitation",
        speaker="Rakila",
        utterance="What do all of you bots think about that?",
        expected_answer=True,
        allow_any_target=("echo", "mira", "nova"),
    ),
    Scenario(
        name="human_to_human_only",
        speaker="Rakila",
        utterance="Littorekt, I was asking you, not the bots.",
        expected_answer=False,
    ),
    Scenario(
        name="bot_asks_named_bot",
        speaker="Echo",
        speaker_bot_id="echo",
        utterance="Mira, can you challenge my premise before Nova moderates?",
        expected_answer=True,
        expected_target="mira",
    ),
    Scenario(
        name="bot_invites_multiple_bots",
        speaker="Echo",
        speaker_bot_id="echo",
        utterance="Mira and Nova, one of you should take the next counterargument.",
        expected_answer=True,
        allow_any_target=("mira", "nova"),
    ),
    Scenario(
        name="bot_general_room_statement_no_route",
        speaker="Nova",
        speaker_bot_id="nova",
        utterance="That is my position on the topic.",
        expected_answer=False,
    ),
    Scenario(
        name="ambiguous_uncertain_disabled",
        speaker="Rakila",
        utterance="Interesting.",
        expected_answer=False,
        policy_overrides={"default_when_uncertain": False, "uncertain_fallback_target": "none"},
    ),
    Scenario(
        name="self_route_should_pick_other_or_none",
        speaker="Nova",
        speaker_bot_id="nova",
        utterance="Nova should continue explaining this point.",
        expected_answer=False,
        policy_overrides={"exclude_speaker_from_targets": True, "self_route_policy": "ignore", "default_when_uncertain": False},
    ),
    Scenario(
        name="group_invitation_disabled",
        speaker="Rakila",
        utterance="Any bot can answer this if they want.",
        expected_answer=False,
        policy_overrides={
            "allow_group_invitation_routing": False,
            "allow_open_room_invitation_routing": False,
            "default_when_uncertain": False,
        },
    ),
]


def main() -> int:
    model = MODEL or _first_lmstudio_model()
    if not model:
        print(f"FAIL: no LM Studio chat model available at {BASE_URL}", file=sys.stderr)
        return 2
    print(f"LM Studio base URL: {BASE_URL}")
    print(f"Model: {model}")
    failed = 0
    for scenario in SCENARIOS:
        policy = dict(DEFAULT_POLICY)
        if scenario.policy_overrides:
            policy.update(scenario.policy_overrides)
        candidates = _eligible_candidates(scenario, policy)
        raw = _chat_completion(model, _system_prompt(policy), _user_prompt(scenario, candidates))
        parsed = _parse_decision(raw)
        ok = _matches(scenario, parsed)
        failed += 0 if ok else 1
        print("\n---", scenario.name, "---")
        print("speaker:", scenario.speaker, f"(bot_id={scenario.speaker_bot_id or 'human'})")
        print("utterance:", scenario.utterance)
        print("candidates:", ", ".join(item["id"] for item in candidates) or "(none)")
        print("policy:", json.dumps(policy, sort_keys=True))
        print("raw:", raw)
        print("parsed:", json.dumps(parsed, sort_keys=True))
        print(
            "expected:",
            json.dumps(
                {
                    "answer": scenario.expected_answer,
                    "target": scenario.expected_target,
                    "allow_any_target": scenario.allow_any_target,
                },
                sort_keys=True,
            ),
        )
        print("result:", "PASS" if ok else "FAIL")
    if failed:
        print(f"\nFAIL: {failed} live LM Studio routing scenario(s) failed.")
        return 1
    print("\nPASS: all live LM Studio routing scenarios passed.")
    return 0


def _first_lmstudio_model() -> str:
    try:
        with urllib.request.urlopen(f"{BASE_URL}/models", timeout=8) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception:
        return ""
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, list):
        return ""
    for item in data:
        model_id = str(item.get("id") if isinstance(item, dict) else item).strip()
        if model_id and "embedding" not in model_id.lower() and "embed" not in model_id.lower():
            return model_id
    return ""


def _eligible_candidates(scenario: Scenario, policy: dict[str, Any]) -> list[dict[str, str]]:
    candidates = list(CANDIDATES)
    if scenario.speaker_bot_id and policy.get("exclude_speaker_from_targets", True):
        candidates = [item for item in candidates if item["id"] != scenario.speaker_bot_id]
    return candidates


def _system_prompt(policy: dict[str, Any]) -> str:
    return (
        f"{DiscordVoiceRuntimeServer.DEFAULT_ROUTER_RULES_PROMPT}\n\n"
        "Active routing policy:\n"
        f"- human_to_bot_routing: {policy['human_to_bot_routing']}\n"
        f"- bot_to_bot_routing: {policy['bot_to_bot_routing']}\n"
        f"- exclude_speaker_from_targets: {policy['exclude_speaker_from_targets']}\n"
        f"- allow_group_invitation_routing: {policy['allow_group_invitation_routing']}\n"
        f"- allow_open_room_invitation_routing: {policy['allow_open_room_invitation_routing']}\n"
        f"- self_route_policy: {policy['self_route_policy']}\n"
        f"- default_when_uncertain: {policy['default_when_uncertain']}\n"
        f"- uncertain_fallback_target: {policy['uncertain_fallback_target']}\n\n"
        "Obey the active routing policy. Do not answer the user yourself."
    )


def _user_prompt(scenario: Scenario, candidates: list[dict[str, str]]) -> str:
    candidate_lines = [
        f"- id={item['id']}; name={item['name']}; call_names={item['call_names']}; persona: {item['persona_hint']}"
        for item in candidates
    ]
    return (
        "Candidate NC bots:\n"
        + "\n".join(candidate_lines)
        + "\n\nCurrent Discord voice participants:\n- Echo (bot)\n- Mira (bot)\n- Nova (bot)\n- Rakila\n- Littorekt\n\n"
        + "Recent shared room context:\n"
        + "Rakila asked the room to debate a topic. Echo, Mira, and Nova are available as NC bots.\n\n"
        + f"Speaker: {scenario.speaker}\n\n"
        + f"Latest utterance:\n[2026-06-11 18:00:00 W. Europe Daylight Time] {scenario.speaker}: {scenario.utterance}\n\n"
        + 'Return one-line minified JSON only, for example: {"answer":true,"target_bot_id":"mira","reason":"speaker addressed Mira"}'
    )


def _chat_completion(model: str, system_prompt: str, user_prompt: str) -> str:
    if os.environ.get("LMSTUDIO_ROUTER_TEST_OPENAI_ONLY", "").strip().lower() not in {"1", "true", "yes"}:
        legacy = _lmstudio_api_v1_chat(model, system_prompt, user_prompt)
        if legacy is not None:
            return legacy
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0,
        "max_tokens": 2048,
        "reasoning": "off",
        "stream": False,
    }
    return _chat_completion_payload(payload)


def _lmstudio_api_v1_chat(model: str, system_prompt: str, user_prompt: str) -> str | None:
    payload = {
        "model": model,
        "store": False,
        "stream": False,
        "system_prompt": system_prompt,
        "input": user_prompt,
        "temperature": 0,
        "max_tokens": 2048,
        "reasoning": "off",
    }
    raw = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        f"{API_ROOT}/api/v1/chat",
        data=raw,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        if exc.code == 400 and "reasoning" in body.lower():
            retry_payload = dict(payload)
            retry_payload.pop("reasoning", None)
            raw_retry = json.dumps(retry_payload).encode("utf-8")
            retry_request = urllib.request.Request(
                f"{API_ROOT}/api/v1/chat",
                data=raw_retry,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(retry_request, timeout=60) as response:
                result = json.loads(response.read().decode("utf-8"))
        else:
            return None
    except Exception:
        return None
    output = result.get("output") if isinstance(result, dict) else None
    if isinstance(output, list):
        messages = [
            str(item.get("content") or "")
            for item in output
            if isinstance(item, dict) and str(item.get("type") or "message") == "message"
        ]
        return "\n".join(part for part in messages if part).strip()
    return str(result.get("content") or result.get("message") or "") if isinstance(result, dict) else ""


def _chat_completion_payload(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        f"{BASE_URL}/chat/completions",
        data=raw,
        headers={"Content-Type": "application/json", "Authorization": "Bearer lm-studio"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        if exc.code == 400 and "reasoning" in payload and "reasoning" in body.lower():
            retry_payload = dict(payload)
            retry_payload.pop("reasoning", None)
            return _chat_completion_payload(retry_payload)
        raise RuntimeError(f"LM Studio HTTP {exc.code}: {body}") from exc
    choices = result.get("choices") if isinstance(result, dict) else None
    if not choices:
        return json.dumps(result)
    message = choices[0].get("message") if isinstance(choices[0], dict) else {}
    return str((message or {}).get("content") or "").strip()


def _parse_decision(raw: str) -> dict[str, Any]:
    match = re.search(r"\{.*\}", str(raw or ""), flags=re.DOTALL)
    if not match:
        return {"answer": False, "target_bot_id": "", "reason": "parse_failed"}
    try:
        payload = json.loads(match.group(0))
    except Exception:
        return {"answer": False, "target_bot_id": "", "reason": "parse_failed"}
    return {
        "answer": bool(payload.get("answer")),
        "target_bot_id": re.sub(r"[^a-zA-Z0-9_.-]+", "_", str(payload.get("target_bot_id") or payload.get("target") or "").strip()).strip("._-").lower(),
        "reason": str(payload.get("reason") or ""),
    }


def _matches(scenario: Scenario, parsed: dict[str, Any]) -> bool:
    if bool(parsed.get("answer")) != scenario.expected_answer:
        return False
    if not scenario.expected_answer:
        return True
    target = str(parsed.get("target_bot_id") or "")
    if scenario.expected_target:
        return target == scenario.expected_target
    if scenario.allow_any_target:
        return target in scenario.allow_any_target
    return bool(target)


if __name__ == "__main__":
    raise SystemExit(main())
