import re

from agent_core import PolicyDecision

# =============================================================================
# POLICY VERSION 2: Die Berechtigung wird AUSSERHALB des Modells entschieden.
#
# Jedes Gespräch bekommt eine NEUE Policy-Instanz, denn die Regeln brauchen
# Zustand (wie viele Tickets, wurde schon ein Dokument gelesen). Eine Instanz,
# die über mehrere Gespräche hinweg lebt, würde die Zähler verfälschen.
#
# Wichtige Regeln gelten bewusst AUCH im Server (mehrstufige Verteidigung).
# Diese Policy kann dazu Dinge, die ein Server nicht weiß: den Verlauf eines
# Gesprächs.
# =============================================================================

COMPANY_DOMAIN = "nordlicht-lab.example"

# Gleiche Regel wie im Server: Der GESAMTE Text muss genau eine interne Adresse sein.
INTERNAL_ADDRESS = re.compile(r"[A-Za-z0-9._%+-]+@" + re.escape(COMPANY_DOMAIN), re.IGNORECASE)

MAX_TICKETS_PER_RUN = 3

# Deny by default: Nur diese Werkzeuge dürfen vom Modell aufgerufen werden.
# Alles andere (auch Infrastruktur-Tools wie list_notes) wird abgelehnt.
ALLOWED_TOOLS = {"search_knowledge", "create_ticket", "read_file", "send_email", "save_note"}

# Diese Werkzeuge bringen Dokumentinhalte in das Gespräch.
DOCUMENT_TOOLS = {"search_knowledge", "read_file"}


def _deny(reason: str) -> PolicyDecision:
    return PolicyDecision(allowed=False, reason=reason)


def _path_problem(path) -> str:
    """Liefert einen Grund, wenn der Pfad verdächtig aussieht, sonst einen leeren
    Text. Das ist nur die Vorprüfung auf Syntax. Die eigentliche Prüfung (Pfad
    auflösen und im erlaubten Bereich prüfen) macht der Server."""
    if not isinstance(path, str) or not path.strip():
        return "Der Pfad fehlt oder ist kein Text."
    if "\x00" in path:
        return "Der Pfad enthält ein ungültiges Zeichen."
    if "\\" in path:
        return "Rückwärts-Schrägstriche sind in Pfaden nicht erlaubt."

    cleaned = path.strip()
    if cleaned.startswith(("/", "~")) or re.match(r"^[A-Za-z]:", cleaned):
        return "Absolute Pfade sind nicht erlaubt."
    if any(part == ".." for part in cleaned.split("/")):
        return "Pfade mit '..' sind nicht erlaubt."
    return ""


class PolicyV2:
    def __init__(self, max_tickets: int = MAX_TICKETS_PER_RUN) -> None:
        self.max_tickets = max_tickets
        self.tickets_allowed = 0
        self.document_contact = False

    def __call__(self, tool_name: str, args: dict) -> PolicyDecision:
        if tool_name not in ALLOWED_TOOLS:
            return _deny(f"Das Werkzeug '{tool_name}' ist für das Modell nicht freigegeben.")

        if tool_name == "send_email":
            recipient = args.get("to")
            if not isinstance(recipient, str) or not INTERNAL_ADDRESS.fullmatch(recipient.strip()):
                return _deny("Nur firmeninterne Empfänger sind zulässig.")

        elif tool_name == "create_ticket":
            if self.tickets_allowed >= self.max_tickets:
                return _deny(f"Höchstens {self.max_tickets} Tickets pro Gespräch.")
            self.tickets_allowed += 1

        elif tool_name == "read_file":
            problem = _path_problem(args.get("path"))
            if problem:
                return _deny(problem)

        elif tool_name == "save_note":
            # Wer in diesem Gespräch Dokumentinhalte gelesen hat, könnte von
            # einer darin versteckten Anweisung beeinflusst sein. Notizen
            # überdauern das Gespräch, deshalb wird das Speichern dann gesperrt.
            # Das hat einen Preis: "Such die Anleitung und merk dir den Server"
            # speichert dann nichts. Ein bewusster Zielkonflikt.
            if self.document_contact:
                return _deny("Notizen werden nicht gespeichert, nachdem Dokumentinhalte gelesen wurden.")

        # Erst wenn der Aufruf erlaubt ist, zählt er als Dokumentkontakt.
        if tool_name in DOCUMENT_TOOLS:
            self.document_contact = True

        return PolicyDecision(allowed=True)


def make_policy_v2() -> PolicyV2:
    """Erzeugt eine frische Policy für ein neues Gespräch."""
    return PolicyV2()