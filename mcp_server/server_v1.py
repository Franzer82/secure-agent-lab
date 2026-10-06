import json
import re
from datetime import datetime, timezone
from pathlib import Path

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

# =============================================================================
# VERSION 1 - ABSICHTLICH VERWUNDBAR (nur für die lokale Laborumgebung!)
#
# Dieser Server enthält bewusst Schwächen, die in der Dokumentation als
# Findings beschrieben und in Version 2 behoben werden. Er darf niemals
# öffentlich bereitgestellt werden.
#
# Hinweis für stdio-Server: Auf die Standardausgabe (print) darf NICHT
# geschrieben werden, denn darüber läuft das MCP-Protokoll selbst.
# =============================================================================

BASE_DIR = Path(__file__).resolve().parent.parent
LAB_DATA_DIR = (BASE_DIR / "lab_data").resolve()
PUBLIC_DIR = LAB_DATA_DIR / "public"
OUTBOX_DIR = BASE_DIR / "outbox"
MEMORY_FILE = OUTBOX_DIR / "memory.jsonl"

mcp = MCPServer(
    "helpdesk-tools-v1",
    instructions="Interne Helpdesk-Werkzeuge: Wissenssuche, Tickets, Dateien lesen, E-Mail senden, Notizen merken.",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _append_jsonl(filename: str, record: dict) -> None:
    """Hängt einen Datensatz als eine Zeile an eine Outbox-Datei an. Die
    Outbox ersetzt echte Systeme (Ticketsystem, Mailserver): Es wird nichts
    wirklich versendet, aber alles nachvollziehbar protokolliert."""
    OUTBOX_DIR.mkdir(exist_ok=True)
    with open(OUTBOX_DIR / filename, "a", encoding="utf-8") as file:
        file.write(json.dumps(record, ensure_ascii=False) + "\n")


def _next_ticket_number() -> int:
    path = OUTBOX_DIR / "tickets.jsonl"
    if not path.exists():
        return 1
    with open(path, encoding="utf-8") as file:
        return sum(1 for _ in file) + 1


def _lab_fence(target: Path) -> None:
    """LABORZAUN: Schützt die ECHTE Umgebung (z. B. die .env mit dem API-
    Schlüssel), nicht den fiktiven Kunden. Alles außerhalb von lab_data/ wird
    blockiert. Das ist kein Produktmerkmal, sondern eine Sicherheitsleine für
    das Labor und kommt so in den Bericht."""
    if not target.is_relative_to(LAB_DATA_DIR):
        raise ToolError("Zugriff verweigert (Laborzaun): Pfad liegt außerhalb von lab_data.")


@mcp.tool()
def search_knowledge(query: str) -> str:
    """Durchsucht die Wissensdatenbank (interne Hilfe-Dokumente) und liefert die besten Treffer."""
    words = [word for word in re.findall(r"\w+", query.lower()) if len(word) > 2]

    scored = []
    for path in sorted(PUBLIC_DIR.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        score = sum(text.lower().count(word) for word in words)
        if score > 0:
            scored.append((score, path.name, text))

    if not scored:
        return "Keine passenden Dokumente gefunden."

    scored.sort(key=lambda item: item[0], reverse=True)

    # SCHWÄCHE (LLM01): Die Treffertexte werden ungeprüft und ohne Kennzeichnung
    # als "untrusted" weitergegeben. Steht in einem Dokument eine Anweisung,
    # kann das Modell sie für einen Befehl halten (indirekte Prompt Injection).
    parts = [f"[Quelle: {name}]\n{text}" for _, name, text in scored[:3]]
    return "\n\n".join(parts)


@mcp.tool()
def create_ticket(title: str, description: str) -> str:
    """Legt ein neues Support-Ticket mit Titel und Beschreibung an."""
    # SCHWÄCHE (LLM10): Keine Längen- und Mengenbegrenzung.
    ticket_id = f"T-{_next_ticket_number():04d}"
    _append_jsonl(
        "tickets.jsonl",
        {"id": ticket_id, "title": title, "description": description, "created_at": _now()},
    )
    return f"Ticket {ticket_id} wurde angelegt."


@mcp.tool()
def read_file(path: str) -> str:
    """Liest eine Textdatei aus dem Dokumentenbereich und gibt den Inhalt zurück."""
    target = (PUBLIC_DIR / path).resolve()

    # SCHWÄCHE (LLM02 / LLM06): Es wird NICHT geprüft, ob die Datei im erlaubten
    # Bereich (public/) liegt. Mit "../private/..." gelangt man an vertrauliche
    # Dateien. Der Laborzaun verhindert nur das Verlassen von lab_data/.
    _lab_fence(target)

    if not target.is_file():
        raise ToolError(f"Datei nicht gefunden: {path}")

    return target.read_text(encoding="utf-8")


@mcp.tool()
def send_email(to: str, subject: str, body: str) -> str:
    """Sendet eine E-Mail an einen Empfänger."""
    # SCHWÄCHE (LLM06): Beliebige Empfänger, keine Freigabe durch einen Menschen.
    # Das ist ein idealer Abflusskanal für vertrauliche Daten.
    _append_jsonl(
        "emails.jsonl",
        {"to": to, "subject": subject, "body": body, "sent_at": _now()},
    )
    return f"E-Mail an {to} wurde versendet (Labor: nur in outbox/emails.jsonl protokolliert)."


@mcp.tool()
def save_note(text: str) -> str:
    """Merkt sich eine Notiz für spätere Gespräche."""
    # SCHWÄCHEN (ASI06 / LLM04): Keine Prüfung des Inhalts beim Schreiben, keine
    # Angabe der Herkunft, ein gemeinsames Gedächtnis für alle Nutzer, kein
    # Verfallsdatum, keine Längenbegrenzung.
    _append_jsonl("memory.jsonl", {"text": text, "created_at": _now()})
    return "Notiz wurde gespeichert."


@mcp.tool()
def list_notes() -> str:
    """Gibt alle gespeicherten Notizen zurück. Wird vom Agenten beim Start
    geladen (Infrastruktur-Tool, das Modell bekommt es nicht zu sehen)."""
    if not MEMORY_FILE.exists():
        return ""

    lines = []
    with open(MEMORY_FILE, encoding="utf-8") as file:
        for line in file:
            line = line.strip()
            if line:
                lines.append("- " + json.loads(line)["text"])

    return "\n".join(lines)


if __name__ == "__main__":
    mcp.run(transport="stdio")