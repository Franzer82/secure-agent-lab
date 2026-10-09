import json
import re
from datetime import datetime, timezone
from pathlib import Path

from agent_core import PolicyDecision
from policy_v2 import (
    ALLOWED_TOOLS,
    COMPANY_DOMAIN,  # noqa: F401  (wird im Drift-Test mit dem Server verglichen)
    DOCUMENT_TOOLS,
    INTERNAL_ADDRESS,
    MAX_TICKETS_PER_RUN,
    _path_problem,
)

# =============================================================================
# POLICY VERSION 2.1 (docs/v2_1_plan.md)
#
# Änderungen gegenüber policy_v2.py:
#   - Die Notizprüfung des Servers gilt zusätzlich hier (zweite Schicht bei A8)
#   - Allgemeine Meldungen an das Modell, Einzelheiten nur im Audit-Log
#   - Audit-Log abgelehnter Aktionen (Quelle "policy"), nur Ziele und Längen
#
# Die Regeln von Policy und Server sind bewusst doppelt vorhanden. Damit sie nicht
# auseinanderlaufen, vergleicht tests/test_policy_v2_1.py die Werte beider Dateien.
# policy_v2.py bleibt als gemessenes Artefakt unverändert.
# =============================================================================

# Gleiche Werte und Meldungen wie im Server (server_v2_1.py).
NOTE_MAX_LENGTH = 200
LINK_PATTERN = re.compile(r"https?://|www\.", re.IGNORECASE)
AUDIT_VALUE_LIMIT = 100

GENERIC_DENIED = "Diese Aktion ist nicht erlaubt."
LIMIT_REACHED = "Das Limit für diese Aktion ist erreicht. Bitte später erneut versuchen."
INVALID_INPUT = "Die Eingabe ist ungültig."

OUTBOX_DIR = Path(__file__).resolve().parent.parent / "outbox"
AUDIT_FILE = OUTBOX_DIR / "audit.jsonl"


def _audit(tool: str, code: str, **details) -> None:
    """Schreibt einen Eintrag ins Audit-Log. Erlaubt sind nur Ziele (Pfad, Empfänger) und
    Längen, keine Inhalte. Werte werden als JSON geschrieben und gekürzt: Zeilenumbrüche aus
    Modell-Eingaben können so keine Logzeilen fälschen. Schlägt das Schreiben fehl, bleibt die
    Ablehnung trotzdem bestehen."""
    record = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": "policy",
        "tool": str(tool)[:AUDIT_VALUE_LIMIT],
        "code": code,
    }
    for name, value in details.items():
        record[name] = value if isinstance(value, int) else str(value)[:AUDIT_VALUE_LIMIT]

    try:
        OUTBOX_DIR.mkdir(exist_ok=True)
        with open(AUDIT_FILE, "a", encoding="utf-8") as file:
            file.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        pass


def _text_or_marker(value) -> str:
    return value if isinstance(value, str) else "(kein Text)"


def _note_problem(text) -> tuple[str, int] | None:
    """Dieselbe Prüfung wie im Server. Liefert (Code, Länge) oder None, wenn die Notiz in Ordnung ist."""
    if not isinstance(text, str):
        return "note_empty", 0

    stripped = text.strip()
    if not stripped:
        return "note_empty", 0
    if len(stripped) > NOTE_MAX_LENGTH:
        return "note_too_long", len(stripped)
    if "@" in stripped or LINK_PATTERN.search(stripped):
        return "note_contains_address_or_link", len(stripped)
    return None


class PolicyV21:
    """Jedes Gespräch bekommt eine NEUE Instanz, denn die Regeln brauchen Zustand (wie viele
    Tickets, wurde schon ein Dokument gelesen)."""

    def __init__(self, max_tickets: int = MAX_TICKETS_PER_RUN) -> None:
        self.max_tickets = max_tickets
        self.tickets_allowed = 0
        self.document_contact = False

    @staticmethod
    def _deny(tool: str, code: str, reason: str = GENERIC_DENIED, **details) -> PolicyDecision:
        """Lehnt ab: Der Grund (Code) steht im Log, das Modell bekommt nur die allgemeine Meldung."""
        _audit(tool, code, **details)
        return PolicyDecision(allowed=False, reason=reason)

    def __call__(self, tool_name: str, args: dict) -> PolicyDecision:
        if tool_name not in ALLOWED_TOOLS:
            return self._deny(tool_name, "tool_not_allowed")

        if tool_name == "send_email":
            recipient = args.get("to")
            if not isinstance(recipient, str) or not INTERNAL_ADDRESS.fullmatch(recipient.strip()):
                return self._deny(tool_name, "recipient_not_internal", to=_text_or_marker(recipient))

        elif tool_name == "create_ticket":
            if self.tickets_allowed >= self.max_tickets:
                return self._deny(tool_name, "ticket_limit_run", LIMIT_REACHED, count=self.tickets_allowed)
            self.tickets_allowed += 1

        elif tool_name == "read_file":
            path = args.get("path")
            if _path_problem(path):
                return self._deny(tool_name, "path_not_allowed", path=_text_or_marker(path))

        elif tool_name == "save_note":
            # Wer in diesem Gespräch Dokumentinhalte gelesen hat, könnte von einer darin
            # versteckten Anweisung beeinflusst sein. Notizen überdauern das Gespräch.
            if self.document_contact:
                return self._deny(tool_name, "note_after_document_contact")

            problem = _note_problem(args.get("text"))
            if problem:
                code, length = problem
                reason = INVALID_INPUT if code in ("note_empty", "note_too_long") else GENERIC_DENIED
                return self._deny(tool_name, code, reason, length=length)

        # Erst wenn der Aufruf erlaubt ist, zählt er als Dokumentkontakt.
        if tool_name in DOCUMENT_TOOLS:
            self.document_contact = True

        return PolicyDecision(allowed=True)


def make_policy_v2_1() -> PolicyV21:
    """Erzeugt eine frische Policy für ein neues Gespräch."""
    return PolicyV21()