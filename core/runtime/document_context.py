"""Ephemeral document retraction guards; never provider JSON or history."""
from dataclasses import dataclass, field
from collections.abc import Callable, Mapping, Sequence


@dataclass(frozen=True, slots=True)
class DocumentContextTicket:
    package_id: str
    activation_revision: int
    request_id: str
    is_current: Callable[[], bool] = field(repr=False, compare=False)

    def current(self) -> bool:
        try:
            return bool(self.is_current())
        except Exception:
            return False


def filter_document_messages(messages: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    result = []
    for message in messages:
        ticket = message.get("_nc_document_ticket")
        if isinstance(ticket, DocumentContextTicket) and not ticket.current():
            continue
        result.append({k:v for k,v in message.items() if k != "_nc_document_ticket"})
    return result
