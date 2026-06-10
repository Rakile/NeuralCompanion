from __future__ import annotations

PROVIDER_ID = "companion_orb_target"

COMPANION_ORB_TARGET_PINGPONG_PROMPT = """When Companion Orb Target input is present, treat it as the orb's own selected sensory focus.

Primary rule:
- Comment on the actual visible content inside the captured image/region: readable text, UI controls, images, video content, alerts, selected items, or documents.
- Do not stop at naming the containing window or process. Window titles are only weak context unless no content is readable or visually identifiable.
- If OCR text or OCR regions are present, use them before window metadata.
- If a manual inspection request is present, inspect the selected region first and set should_speak=true when there is any visible content worth commenting on.
- For every spoken Companion Orb comment, include focus_bounds when available. Use OCR region screen_bounds for the exact thing being discussed; otherwise use the selected region/manual inspection bounds.

Manual inspection mode:
- metadata.manual_inspection means the user deliberately selected a specific visual focus area with the orb. Treat the captured crop as the primary evidence for this PONG.
- Do not describe the selection action, the orb movement, or that the user pointed at something. Respond to the visible content in the crop.
- Never mention "dropped", "dragged", "sensory ping", "metadata", coordinates, bounds, or "point of interest" in proactive_candidate. Those are implementation details, not visible content.
- Do not summarize unrelated windows spread across the desktop. Only mention another window if it is visibly inside or directly connected to the selected crop.
- If readable OCR is present, comment on the most relevant text/control/image inside the crop. If OCR is weak, describe the visible layout, icon, image, button, panel, or document area instead.
- When should_speak=true, proactive_candidate must name something visible in the selected crop and focus_bounds must be set to the exact OCR/object region when available, otherwise metadata.screen_bounds or metadata.manual_inspection.focus_bounds.
- If the crop is blank or unreadable, set should_speak=false unless a short clarification is genuinely useful.

Targeted mode:
- Infer the visible window/region, task, readable text, and visually important object from the current PING.
- Stay grounded in what is actually visible. Avoid guessing hidden app state or unreadable details.
- Prefer specific content observations over generic app/window descriptions.
- Use summary for meaningful target changes worth retaining.
- Set should_speak=false unless the current target clearly offers a useful, playful, or user-relevant comment.
- If should_speak=true, proactive_candidate must be one short line cue in the companion's voice, grounded in the visible target.
- If commenting on a specific visible item, include focus_bounds from an OCR region or screen_bounds when available.
- If exact bounds are not available, include focus_text that matches the visible text or subject being discussed.

Full-screen context map mode:
- The PING represents the desktop-wide map used by the Companion Orb to explore the user's current screen.
- Identify the strongest visible subject: active window, readable text area, interesting image/video area, alert, button, or workspace change.
- Prefer one focused subject over describing the entire desktop.
- Use focus_bounds from ocr_regions or screen_bounds for the region the orb should move toward.
- If manual_inspection.focus_bounds is present, manual inspection mode wins: do not broaden to the full desktop, and keep focus_bounds inside or near the selected crop.
- Use focus_text when the subject is text-like and should be matched against OCR.
- Do not mention process names unless the source explicitly provides them and the user has allowed process-name mentions.
- Do not ask for screenshots; this source already captured the current context.
- Do not request image generation unless a separate enabled behavior explicitly asks for it."""

COMPANION_ORB_TARGET_METADATA = {
    "target_source": "companion_orb",
    "privacy": "targeted_or_full_screen_opt_in",
    "prompt_fragment_enabled": True,
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
    ],
    "pong_influences": [
        {"field": "attention", "description": "short focus cue for the selected target or desktop subject"},
        {"field": "summary", "description": "meaningful target/desktop change worth retaining"},
        {"field": "proactive_candidate", "description": "short spoken cue only when hidden proactive replies are enabled and a comment is useful"},
        {"field": "focus_bounds", "description": "desktop coordinates the orb should move toward when commenting on a visible subject"},
        {"field": "focus_text", "description": "text/subject the orb should match against OCR regions when exact bounds are not available"},
    ],
    "tag_subscriptions": [],
    "pingpong_prompt": COMPANION_ORB_TARGET_PINGPONG_PROMPT,
}
