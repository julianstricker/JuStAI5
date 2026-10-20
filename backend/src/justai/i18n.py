"""Texts JuStAI5 speaks or shows directly, in the user's language (de, it, en).

Everything that goes to a language model (system prompt, tool descriptions, tool results)
is English: models follow English instructions best and answer in the user's language
anyway. Only fixed texts that reach people without a model in between live here.
"""

from __future__ import annotations

LANGUAGES = ("en", "de", "it")
DEFAULT = "en"

_TEXTS: dict[str, dict[str, str]] = {
    "sorry.error": {
        "en": "Sorry, something went wrong.",
        "de": "Entschuldigung, dabei ist ein Fehler aufgetreten.",
        "it": "Scusa, si è verificato un errore.",
    },
    "sorry.failed": {
        "en": "Sorry, I could not do that.",
        "de": "Entschuldigung, das habe ich leider nicht geschafft.",
        "it": "Scusa, non ci sono riuscito.",
    },
    "cloud.note": {
        "en": "Note: the local model is unavailable, I am answering with a cloud model.",
        "de": "Hinweis: Das lokale Modell ist gerade nicht verfügbar, ich antworte über ein Cloud-Modell.",
        "it": "Nota: il modello locale non è disponibile, rispondo tramite un modello cloud.",
    },
    "memory.episode": {
        "en": "Conversation: {summary}",
        "de": "Gespräch: {summary}",
        "it": "Conversazione: {summary}",
    },
    "watch.announce": {
        "en": "Note: {name}.",
        "de": "Hinweis: {name}.",
        "it": "Avviso: {name}.",
    },
    "watch.automation": {
        "en": "Notice: {name}",
        "de": "Meldung: {name}",
        "it": "Avviso: {name}",
    },
    "watch.created_by_voice": {
        "en": "Created by voice for {name}",
        "de": "Angelegt per Sprache für {name}",
        "it": "Creato a voce per {name}",
    },
}


def lang(code: str | None) -> str:
    """Normalise a language code ('de-DE', 'it', None) to a supported one."""
    short = (code or "")[:2].lower()
    return short if short in LANGUAGES else DEFAULT


def text(key: str, language: str | None, **values: object) -> str:
    entry = _TEXTS[key]
    template = entry.get(lang(language)) or entry[DEFAULT]
    return template.format(**values) if values else template
