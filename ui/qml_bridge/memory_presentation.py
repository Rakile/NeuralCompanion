"""Bounded, readable memory inspection; never include stored image blobs."""
from collections.abc import Mapping
from pathlib import PureWindowsPath
import re


ACTION_TITLES = {
    'review_summary': 'Conversation summary', 'summarize_recent': 'Conversation summary updated',
    'forget_summary': 'Conversation summary forgotten', 'search_archive': 'Archive search results',
    'review_archive': 'Long-term archive contents', 'export_report': 'Session memory report',
    'refresh_models': 'Embedding models', 'rebuild_embeddings': 'Search embeddings',
    'rebuild_archive': 'Inactive archive candidate', 'save_context': 'Chat context saved',
    'load_context': 'Chat context loaded',
}


def describe_memory(config, summary, conversation, archive, embedding):
    """Default UI answers; diagnostics stay separate from these short labels."""
    total = int(getattr(conversation, 'total_messages', 0) or 0)
    covered = int(getattr(conversation, 'summarized_messages', summary.get('source_turn_count', 0)) or 0)
    pending = max(0, total-covered)
    saved = bool(config.get('active_chat_context_path'))
    scratch = bool(config.get('quick_chat_context_active'))
    if scratch:
        summary_text = 'Not used in this temporary chat.'
    elif not config.get('continuity_memory_enabled'):
        summary_text = 'Conversation summary is off.'
    elif not saved:
        summary_text = 'Save this conversation to enable automatic summaries.'
    elif not summary.get('summary'):
        summary_text = 'No summary yet. Use Update now to create one.'
    elif pending:
        summary_text = f'{pending} new message(s) waiting to be summarized.'
    else:
        summary_text = f'Up to date — covers all {total} messages.' if total else 'Summary available.'
    if (saved and not scratch and config.get('continuity_memory_enabled')
            and not config.get('continuity_memory_auto_summarize', config.get('continuity_memory_update_on_save', False))):
        summary_text += ' Automatic updates are off.'
    archived = min(total, int(archive.get('archived_through', 0) or 0))
    if scratch:
        archive_text = 'Not used in this temporary chat.'
    elif not saved:
        archive_text = 'Save this conversation to use long-term memory.'
    elif not config.get('long_term_memory_auto_archive_enabled') and not config.get('long_term_memory_retrieval_enabled'):
        archive_text = 'Long-term memory is off.'
    elif total and archived == total:
        archive_text = f'All {total} messages stored.'
    elif total:
        archive_text = f'{archived} of {total} messages stored. {total-archived} waiting.'
    else:
        archive_text = 'No messages to store yet.'
    if saved and not scratch and config.get('long_term_memory_retrieval_enabled') and not config.get('long_term_memory_auto_archive_enabled'):
        archive_text += ' Automatic storage is off.'
    if saved and not scratch and embedding.get('enabled') and 'indexed_messages' in embedding:
        indexed = min(archived, int(embedding.get('indexed_messages', 0) or 0))
        archive_text = f'{archived} messages saved · {indexed} indexed'
        if total > archived:
            archive_text += f' · {total-archived} not yet stored'
        if not config.get('long_term_memory_auto_archive_enabled'):
            archive_text += '. Automatic storage is off.'
    needs_attention = False
    search_text = ''
    can_retry = False
    if saved and not scratch and embedding.get('enabled'):
        missing = int(embedding.get('missing_for_model', 0) or 0)
        needs_attention = bool(missing or embedding.get('session_mismatch') or embedding.get('writes_blocked') or embedding.get('warning'))
        if missing:
            search_text = f'{missing} completed item(s) still need indexing. They may be queued or need a retry.'
            can_retry = not bool(embedding.get('session_mismatch') or embedding.get('writes_blocked'))
        elif needs_attention:
            search_text = 'Search index needs attention. Open Advanced settings for details.'
        else:
            search_text = 'Search index is up to date.'
        waiting = int(embedding.get('waiting_messages', 0) or 0)
        if waiting:
            waiting_text = f'{waiting} recent messages waiting for the next batch.'
            search_text = search_text + '\n' + waiting_text if needs_attention else waiting_text
        if config.get('long_term_memory_embedding_provider') == 'openai' and not config.get('long_term_memory_embedding_cloud_consent'):
            needs_attention = True
            can_retry = False
            search_text = 'Confirm OpenAI memory search in Providers to finish setup.'
    from core.runtime.embedding_provider import PROVIDERS
    provider = str(config.get('long_term_memory_embedding_provider') or 'lmstudio')
    identity = PROVIDERS.get(provider, {})
    source = identity.get('label', provider) + ' · ' + str(config.get('long_term_memory_embedding_model') or identity.get('model', ''))
    return dict(summaryHeadline=summary_text, archiveStatus=archive_text, embeddingStatus=search_text,
                searchNeedsAttention=needs_attention, canRetryIndexing=can_retry,
                totalMessages=total, searchSource=source)


def format_save_result(path, operation, state):
    lines = [f'Conversation saved as {PureWindowsPath(str(path)).name}.', '']
    if state.get('summaryHeadline'):
        lines.append('Conversation summary: ' + state['summaryHeadline'])
    if state.get('archiveStatus'):
        lines.append('Older messages: ' + state['archiveStatus'])
    if state.get('embeddingStatus'):
        lines.append(state['embeddingStatus'])
    return '\n'.join(lines)


def _bounded(text, limit=40000):
    return text if len(text) <= limit else text[:limit] + '\n\nDisplay shortened. Export the session report for full details.'


def _entry(item, number, *, search=False):
    kind = 'Archived chat' if item.get('kind') in {'chunk', 'raw_chunk'} or 'text' in item else 'Memory record'
    title = item.get('title') or kind
    source = item.get('source_chat_id') or 'Unknown source'
    start, end = item.get('source_message_start'), item.get('source_message_end')
    location = f'{source} · messages {start}–{end}' if start is not None and end is not None else str(source)
    body = (item.get('snippet') if search else None) or item.get('summary') or item.get('text') or item.get('content') or ''
    if kind == 'Archived chat' and not search and start is not None:
        # Indexed raw text stays stable when preceding rows are deleted;
        # presentation uses the current canonical range instead.
        position = int(start)-1
        def renumber(match):
            nonlocal position
            position += 1
            return str(position) + '. '
        body = re.sub(r'^\d+\. (?=(?:User|Assistant|System):)', renumber, str(body), flags=re.MULTILINE)
    tags = ', '.join(str(tag) for tag in item.get('tags', ()))
    return f'{number}. {title}\n{kind} · {location}\n{str(body)[:1200]}' + (f'\nTags: {tags}' if tags else '')


def format_search(query, results):
    values = list(results)
    lines = [f'Search: {query}', f'{len(values)} result(s)', '']
    lines.extend(_entry(item, n, search=True) + '\n' for n, item in enumerate(values, 1))
    return _bounded('\n'.join(lines))


def format_archive(archive):
    records, chunks = list(archive.records), list(archive.chunks)
    lines = [f'Storage: {archive.storage_path}', f'Showing {len(records)} memory record(s) and {len(chunks)} archived chunk(s).',
             'Review is limited to 200 of each. Export the session report for a full copy.', '', 'Memory records', '']
    lines.extend(_entry(item, n) + '\n' for n, item in enumerate(records, 1))
    lines.extend(['', 'Archived conversation chunks', ''])
    lines.extend(_entry(dict(item, kind='chunk'), n) + '\n' for n, item in enumerate(chunks, 1))
    return _bounded('\n'.join(lines))


def format_operation_result(value, depth=0):
    if value is None:
        return 'Completed.'
    if isinstance(value, Mapping):
        lines = []
        for key, item in value.items():
            if key in {'blob', 'history', 'conversation_history', 'provider_context'}:
                continue
            label = str(key).replace('_', ' ').capitalize()
            text = format_operation_result(item, depth+1) if depth < 3 else str(item)[:500]
            lines.append(f'{label}: {text}')
        return _bounded('\n'.join(lines))
    if isinstance(value, (tuple, list)):
        return _bounded('\n'.join(format_operation_result(item, depth+1) for item in value[:100]))
    if isinstance(value, bool):
        return 'Yes' if value else 'No'
    return _bounded(str(value))
