import json
import re
from pathlib import Path


APP_HELP_DIR = Path(__file__).resolve().parent / "app_help"
APP_HELP_PATH = APP_HELP_DIR / "knowledge.json"
README_PATH = Path(__file__).resolve().parent / "README.md"


def _load_knowledge():
    try:
        payload = json.loads(APP_HELP_PATH.read_text(encoding="utf-8"))
        topics = list(payload.get("topics") or [])
        return [topic for topic in topics if isinstance(topic, dict)]
    except Exception:
        return []


def _load_markdown_sections():
    paths = []
    if README_PATH.exists():
        paths.append(README_PATH)
    for path in sorted(APP_HELP_DIR.glob("*.md")):
        paths.append(path)
    sections = []
    for path in paths:
        try:
            text = path.read_text(encoding="utf-8")
        except Exception:
            continue
        current_title = path.stem.replace("_", " ").title()
        current_lines = []
        for line in text.splitlines():
            heading = re.match(r"^(#{1,3})\s+(.+?)\s*$", line)
            if heading:
                if current_lines:
                    body = "\n".join(current_lines).strip()
                    if body:
                        sections.append({"title": current_title, "body": body})
                current_title = heading.group(2).strip()
                current_lines = []
                continue
            current_lines.append(line)
        if current_lines:
            body = "\n".join(current_lines).strip()
            if body:
                sections.append({"title": current_title, "body": body})
    return sections


def _normalize(text):
    return re.sub(r"\s+", " ", str(text or "").strip().lower())


def _tokenize(text):
    return re.findall(r"[a-z0-9_]+", _normalize(text))


def _latest_user_like_message(messages):
    for message in reversed(list(messages or [])):
        role = str(message.get("role") or "").lower()
        content = str(message.get("content") or "").strip()
        if not content:
            continue
        if content == "You continue speaking.":
            continue
        if role in {"user", "system"}:
            return content
    return ""


def _looks_like_app_question(text):
    text_n = _normalize(text)
    if not text_n:
        return False
    app_markers = (
        "neural interface",
        "this app",
        "this application",
        "lm studio",
        "musetalk",
        "vseeface",
        "pockettts",
        "chatterbox",
        "turbotts",
        "dry run",
        "performance profile",
        "performance profiles",
        "tutorial",
        "stream mode",
        "tts backend",
        "chunking",
        "brain tab",
        "persona tab",
        "musetalk vram",
        "avatar engine",
        "avatar engines",
        "body tab",
        "dynamics tab",
        "hand doctor",
        "live sync",
        "push to talk",
        "voice activation",
        "preset",
        "tutorial persona",
        "initialize system",
        "musetalk preview",
    )
    question_markers = (
        "how",
        "what",
        "where",
        "why",
        "which",
        "help",
        "explain",
        "tell me",
        "could you",
        "can you",
        "do you know",
        "show me",
        "walk me through",
        "use",
        "setup",
        "set up",
        "configure",
        "tutorial",
    )
    has_app_marker = any(marker in text_n for marker in app_markers)
    has_question_marker = ("?" in text_n) or any(re.search(rf"\b{re.escape(marker)}\b", text_n) for marker in question_markers)
    return has_app_marker and has_question_marker


def retrieve_help_topics(query, max_topics=3):
    query_n = _normalize(query)
    if not _looks_like_app_question(query_n):
        return []
    query_tokens = set(_tokenize(query_n))
    ranked = []
    for topic in _load_knowledge():
        score = 0.0
        for keyword in topic.get("keywords") or []:
            key_n = _normalize(keyword)
            if not key_n:
                continue
            if key_n in query_n:
                score += 3.0
            else:
                key_tokens = set(_tokenize(key_n))
                score += 0.4 * len(query_tokens & key_tokens)
        title = _normalize(topic.get("title"))
        if title and title in query_n:
            score += 2.0
        if score > 0:
            ranked.append((score, topic))
    ranked.sort(key=lambda item: item[0], reverse=True)
    return [topic for _, topic in ranked[:max_topics]]


def retrieve_markdown_sections(query, max_sections=2):
    query_n = _normalize(query)
    if not _looks_like_app_question(query_n):
        return []
    query_tokens = set(_tokenize(query_n))
    ranked = []
    for section in _load_markdown_sections():
        title = _normalize(section.get("title"))
        body = _normalize(section.get("body"))
        haystack = f"{title} {body}".strip()
        if not haystack:
            continue
        score = 0.0
        for token in query_tokens:
            if token and re.search(rf"\b{re.escape(token)}\b", haystack):
                score += 0.35
        if title and title in query_n:
            score += 2.0
        if score > 0:
            ranked.append((score, section))
    ranked.sort(key=lambda item: item[0], reverse=True)
    return [section for _, section in ranked[:max_sections]]


def build_help_context(messages, max_topics=3):
    query = _latest_user_like_message(messages)
    topics = retrieve_help_topics(query, max_topics=max_topics)
    sections_md = retrieve_markdown_sections(query, max_sections=1)
    if not topics and not sections_md:
        return ""
    sections = []
    for topic in topics:
        title = str(topic.get("title") or "Untitled Topic")
        summary = str(topic.get("summary") or "").strip()
        bullets = [str(item).strip() for item in (topic.get("bullets") or []) if str(item).strip()]
        block = [f"{title}: {summary}"] if summary else [title]
        block.extend(f"- {item}" for item in bullets[:6])
        sections.append("\n".join(block))
    for section in sections_md:
        title = str(section.get("title") or "Documentation")
        body = str(section.get("body") or "").strip()
        body = re.sub(r"\n{2,}", "\n", body)
        body = "\n".join(line.strip() for line in body.splitlines() if line.strip())
        if body:
            clipped = body[:900].strip()
            sections.append(f"{title}:\n{clipped}")
    joined = "\n\n".join(sections).strip()
    if not joined:
        return ""
    return (
        "Application help context for answering questions about this app. "
        "Use it only if the user is asking about the application's features or setup. "
        "Prefer the current UI behavior over older documentation wording. "
        "Do not present advanced override settings as required normal setup unless the user explicitly asks about advanced troubleshooting.\n\n"
        f"{joined}"
    )


def explain_help_lookup(messages, max_topics=3):
    query = _latest_user_like_message(messages)
    looks_like = _looks_like_app_question(query)
    topics = retrieve_help_topics(query, max_topics=max_topics) if looks_like else []
    markdown_sections = retrieve_markdown_sections(query, max_sections=1) if looks_like else []
    return {
        "query": query,
        "looks_like_app_question": looks_like,
        "topic_titles": [str(topic.get("title") or "") for topic in topics],
        "topic_count": len(topics),
        "markdown_titles": [str(section.get("title") or "") for section in markdown_sections],
        "markdown_count": len(markdown_sections),
    }
