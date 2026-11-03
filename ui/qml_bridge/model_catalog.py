"""Shared capability filtering for main-chat and auxiliary model selectors."""
from collections.abc import Mapping
from core.runtime.providers import infer_model_supports_images


def model_catalog_entry_supports_images(item):
    if 'supports_images' in item and item.get('supports_images') is not None:
        return bool(item.get('supports_images'))
    capabilities = item.get('capabilities')
    if isinstance(capabilities, Mapping):
        for key in ('supports_images', 'images', 'image', 'vision'):
            if key in capabilities:
                return bool(capabilities.get(key))
    return infer_model_supports_images(str(item.get('id') or item.get('model') or item.get('name') or '').strip())


def model_catalog_entry_tool_support(item):
    """Return reported tool support, or None when the provider does not say."""
    support = item.get('supports_tools')
    if isinstance(support, bool):
        return support
    capabilities = item.get('capabilities')
    if isinstance(capabilities, Mapping):
        for key in ('tools', 'tool_use', 'trained_for_tool_use'):
            support = capabilities.get(key)
            if isinstance(support, bool):
                return support
    elif isinstance(capabilities, (list, tuple, set)):
        reported = {str(value).strip().lower() for value in capabilities if str(value).strip()}
        return bool({'tools', 'tool_use'} & reported) if reported else None
    return None
