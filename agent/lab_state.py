from pathlib import Path

# Setzt den veränderlichen Laborzustand zurück (Gedächtnis, Tickets, E-Mails, Audit-Log).
# Es werden bewusst nur ausdrücklich benannte Dateien gelöscht, nie ein ganzer
# Ordner: Ein Löschwerkzeug soll nur das anfassen können, wofür es gedacht ist.

OUTBOX_DIR = Path(__file__).resolve().parent.parent / "outbox"

MEMORY_FILES = ["memory.jsonl"]
OUTBOX_FILES = ["tickets.jsonl", "emails.jsonl", "audit.jsonl"]


def _remove(names: list[str]) -> list[str]:
    removed = []
    for name in names:
        path = OUTBOX_DIR / name
        if path.exists():
            path.unlink()
            removed.append(name)
    return removed


def reset_memory() -> list[str]:
    return _remove(MEMORY_FILES)


def reset_outbox() -> list[str]:
    return _remove(OUTBOX_FILES)


def reset_all() -> list[str]:
    return reset_memory() + reset_outbox()


if __name__ == "__main__":
    removed = reset_all()
    print("Zurückgesetzt: " + (", ".join(removed) if removed else "nichts zu tun"))