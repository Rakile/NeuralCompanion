"""Allowlisted token-limit diagnostics; never forward raw provider error bodies."""
import re


def limit_category(error):
    text=str(error).casefold()
    if any(marker in text for marker in ('unsupported parameter','unrecognized request argument','unknown parameter')):
        return ''
    if any(marker in text for marker in ('exceed_context_size','context_length_exceeded','prompt_too_long',
            'context length','context window','context size','maximum context','prompt is too long','input is too long')):
        return 'context_length'
    if any(marker in text for marker in ('max_output_tokens','max_tokens','output token limit','output-token limit','maximum output tokens')):
        return 'output_limit'
    return ''


def limit_message(error):
    category=limit_category(error)
    if category=='context_length':
        text=str(error)
        match=re.search(r'request\s*\(\s*(\d{1,12})\s*tokens\).*?context size\s*\(\s*(\d{1,12})\s*tokens\)',text,re.I|re.S)
        if match is None:
            match=re.search(r'needs ([\d,]{1,20}) input tokens.*?has ([\d,]{1,20})',text,re.I|re.S)
        details=(f'The model request needs {int(match[1].replace(",","")):,} input tokens, but the loaded context has '
            f'{int(match[2].replace(",","")):,}. ') if match else 'The conversation and tool results exceed the loaded model context length. '
        return details+"Increase the model's allocated context length, allowing room for the reply, or request a shorter transcript/context."
    if category=='output_limit':
        return 'The model reached its output-token limit before completing the reply. Increase the maximum output tokens or request a shorter reply.'
    return ''
