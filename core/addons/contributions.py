from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


WidgetFactory = Callable[[Any], Any]


@dataclass
class TabContribution:
    id: str
    title: str
    factory: WidgetFactory
    addon_id: str = ""
    area: str = "top_level"
    order: int = 1000
    tooltip: str = ""
    parent_tab_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

