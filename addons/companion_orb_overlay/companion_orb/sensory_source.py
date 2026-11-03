from __future__ import annotations

PROVIDER_ID = "companion_orb_target"

COMPANION_ORB_TARGET_PINGPONG_PROMPT = """Companion Orb Target is the orb's selected visual focus. Use only visible evidence from the current PING.

- When metadata.orb_watch.active is true, its registered subject is the ONLY background focus for this source. Use fresh observation and code-computed eligibility. If eligible=false or unavailable, do not match any Orb background rule, speak, or move for this source. Other sources retain their own rules. Previous titles are comparison evidence, never current facts. Do not confuse NC chat, recommendations or subtitles with the watched title. Manual inspections retain their own rules.

- Prefer recognized OCR text and labelled OCR regions. metadata.ocr_region_detection_only is geometry, not recognized text. Treat window titles as weak context and never invent unreadable details.
- metadata.manual_inspection is a user-selected crop. Keep evidence and focus inside it; do not broaden to unrelated windows.
- In full-screen mode, use metadata.lfm_visual_context to select one strong visible subject and its labelled screen_bounds, confirmed by the screenshot or OCR.
- Evaluate enabled rules only for their stated input scope and repeat policy. On a permitted match, set should_speak=true and include its exact [orb_rule:<rule id>], [companion_orb_supervisor_match], and [orb_subject:<stable visible subject>] tags. Otherwise set should_speak=false.
- Put the matched visible evidence in summary. For focus_bounds, prefer the exact OCR/LFM region, then metadata.drop_focus_bounds or metadata.manual_inspection.focus_bounds, then metadata.screen_bounds. Use focus_text only when exact bounds are unavailable.
- Always set should_generate_image=false and visual_candidate="". Do not expose capture mechanics, OCR, scene maps, coordinates, or disallowed process names in spoken output."""

COMPANION_ORB_TARGET_METADATA = {
    "target_source": "companion_orb",
    "privacy": "targeted_or_full_screen_opt_in",
    "prompt_fragment_enabled": True,
    "requires_prompt_contributor": True,
    "ping_payload": [
        {"field": "image", "description": "hidden screenshot of the selected orb target, or full desktop when Full-screen context map is enabled"},
        {"field": "content_text", "description": "source label, capture mode, and timestamp framing the image as ambient context"},
        {"field": "metadata.target", "description": "target type, title, and screen bounds; process_name is omitted when the privacy option is off"},
        {"field": "metadata.screen_bounds", "description": "desktop coordinate rectangle for the captured target or full desktop"},
        {"field": "metadata.manual_inspection", "description": "optional user-triggered inspection request with focus_bounds to inspect first"},
        {"field": "metadata.manual_inspection_primary", "description": "true when this PING is a user-directed selected crop and should override broad desktop context"},
        {"field": "metadata.drop_focus_bounds", "description": "safe clipped desktop bounds for the selected crop, suitable as fallback focus_bounds"},
        {"field": "metadata.ocr_regions", "description": "optional text/object regions with screen_bounds for orb movement focus"},
        {"field": "metadata.ocr_text", "description": "optional extracted readable text from the target or desktop map"},
        {"field": "metadata.ocr_text_recognized", "description": "true only when the local OCR path resolved actual text"},
        {"field": "metadata.ocr_region_detection_only", "description": "true when only unlabeled text-shaped geometry was detected"},
        {"field": "metadata.ocr_text_recognition_available", "description": "whether a local backend capable of recognizing text is available"},
        {"field": "metadata.lfm_visual_context", "description": "optional private LFM scene summary, visible evidence, and labelled desktop regions with screen_bounds for response grounding and orb movement"},
    ],
    "pong_influences": [
        {"field": "attention", "description": "short focus cue for the selected target or desktop subject"},
        {"field": "summary", "description": "meaningful target/desktop change worth retaining"},
        {"field": "proactive_candidate", "description": "runtime-restored Action for a permitted tagged supervisor rule match"},
        {"field": "focus_bounds", "description": "desktop coordinates the orb should move toward when commenting on a visible subject"},
        {"field": "focus_text", "description": "text/subject the orb should match against OCR regions when exact bounds are not available"},
        {"field": "should_generate_image", "description": "always false for Companion Orb Target"},
        {"field": "visual_candidate", "description": "always empty for Companion Orb Target"},
    ],
    "tag_subscriptions": [],
    "pingpong_prompt": COMPANION_ORB_TARGET_PINGPONG_PROMPT,
}
