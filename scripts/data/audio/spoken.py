"""Schreibform → Sprechform für die TTS (de/en/pl/tr). Die Referenz (Gold-Text) bleibt die Schreibform.

XTTS liest Uhrzeiten, Daten, Dezimalzahlen und Abkürzungen oft falsch ("26.11." → "sechsundzwanzig Punkt elf",
"BA1" → Lautbrei). Deshalb wird vor der Synthese ausgeschrieben, wie ein Bauleiter es sagen würde:
  08:15 → de "acht Uhr fünfzehn" · en "eight fifteen" · pl "ósma piętnaście"* · tr "sekiz on beş"
  26.11. → de "sechsundzwanzigsten November" · en "the twenty-sixth of November" · pl "dwudziestego szóstego
           listopada" · tr "yirmi altı Kasım"
  7.2 / 7,2 → "sieben Komma zwei" · "seven point two" · "siedem przecinek dwa" · "yedi virgül iki"
  BA1 → "B A eins" · "B A one" · "B A jeden" · "B A bir"
(*pl: Stunde als Grundzahl – umgangssprachlich üblich und für ASR gleichwertig.)
"""
from __future__ import annotations

import re

MONTHS = {
    "de": ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober", "November",
           "Dezember"],
    "en": ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
           "November", "December"],
    "pl": ["stycznia", "lutego", "marca", "kwietnia", "maja", "czerwca", "lipca", "sierpnia", "września",
           "października", "listopada", "grudnia"],
    "tr": ["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım",
           "Aralık"],
}
COMMA = {"de": "Komma", "en": "point", "pl": "przecinek", "tr": "virgül"}
_TR_ONES = ["sıfır", "bir", "iki", "üç", "dört", "beş", "altı", "yedi", "sekiz", "dokuz"]
_TR_TENS = ["", "on", "yirmi", "otuz", "kırk", "elli", "altmış", "yetmiş", "seksen", "doksan"]


def cardinal(n: int, lang: str) -> str:
    if lang == "tr" and 0 <= n < 1000:  # num2words(tr) schreibt zusammen ("onbeş") – getrennt ist natürlicher
        h, r = divmod(n, 100)
        t, o = divmod(r, 10)
        parts = ([] if h == 0 else ["yüz"] if h == 1 else [_TR_ONES[h], "yüz"]) + \
                ([_TR_TENS[t]] if t else []) + ([_TR_ONES[o]] if o else [])
        return " ".join(parts) or "sıfır"
    from num2words import num2words

    return num2words(n, lang=lang)


def _ordinal(n: int, lang: str) -> str:
    from num2words import num2words

    w = num2words(n, to="ordinal", lang=lang)
    if lang == "de":
        return w + "n"            # "am sechsundzwanzigsten"
    if lang == "tr":              # num2words schreibt zusammen; Ordnungszahl = Grundzahl + Suffix des letzten Wortes
        return w
    if lang == "pl":              # Genitiv: dwudziesty szósty → dwudziestego szóstego
        return " ".join(x[:-1] + "ego" if x.endswith("y") else x + "ego" if x.endswith("i") else x for x in w.split())
    return w


def _time(h: int, m: int, lang: str) -> str:
    H, M = cardinal(h, lang), cardinal(m, lang)
    if lang == "de":
        return f"{H} Uhr" if m == 0 else f"{H} Uhr {M}"
    if lang == "en":
        if m == 0:
            return f"{H} o'clock" if h <= 12 else f"{H} hundred"
        return f"{H} oh {M}" if m < 10 else f"{H} {M}"
    return H if m == 0 else f"{H} {M}"


def _date(d: int, mo: int, lang: str) -> str:
    if not 1 <= mo <= 12:
        return f"{d}.{mo}."
    if lang == "en":
        return f"the {_ordinal(d, 'en')} of {MONTHS['en'][mo - 1]}"
    if lang == "tr":
        return f"{cardinal(d, 'tr')} {MONTHS['tr'][mo - 1]}"
    return f"{_ordinal(d, lang)} {MONTHS[lang][mo - 1]}"


def _month_no(name: str) -> int:
    for ms in MONTHS.values():
        if name in ms:
            return ms.index(name) + 1
    return 0


def _decimal(i: str, f: str, lang: str) -> str:
    return f"{cardinal(int(i), lang)} {COMMA[lang]} " + " ".join(cardinal(int(c), lang) for c in f)


def spoken_form(text: str, lang: str) -> str:
    if lang not in COMMA:
        return text
    s = text
    s = re.sub(r"\b(\d{1,2})[:.](\d{2})\s*(Uhr|h)\b", lambda m: _time(int(m[1]), int(m[2]), lang), s)
    s = re.sub(r"\b(\d{1,2}):(\d{2})\b", lambda m: _time(int(m[1]), int(m[2]), lang), s)
    s = re.sub(r"\b(\d{1,2})\.(\d{1,2})\.(?:\d{2,4})?(?=\W|$)", lambda m: _date(int(m[1]), int(m[2]), lang), s)
    months = "|".join(sorted((m for ms in MONTHS.values() for m in ms), key=len, reverse=True))
    s = re.sub(r"\b(\d{1,2})\.?\s+(" + months + r")\b",
               lambda m: _date(int(m[1]), _month_no(m[2]), lang) if lang != "tr" else
               f"{cardinal(int(m[1]), lang)} {m[2]}", s)
    s = re.sub(r"\b(\d+)[.,](\d+)\b", lambda m: _decimal(m[1], m[2], lang), s)
    if lang in ("tr", "de", "pl"):  # "4." vor einem Wort = Ordnungszahl
        # nur vor kleingeschriebenem Wort – "statt 16. Bei der …" ist Satzende, keine Ordnungszahl
        s = re.sub(r"\b(\d{1,2})\.(?=\s+[a-zäöüßçğışąćęłńóśźż])",
                   lambda m: _ordinal(int(m[1]), lang).rstrip("n") if lang == "de" else _ordinal(int(m[1]), lang), s)
    s = re.sub(r"\bBA\s?(\d+)\b", lambda m: f"B A {cardinal(int(m[1]), lang)}", s)
    s = re.sub(r"(\d+)\s?[–-]\s?(\d+)", lambda m: f"{m[1]} {'bis' if lang == 'de' else 'to' if lang == 'en' else 'do' if lang == 'pl' else 'ile'} {m[2]}", s)
    s = re.sub(r"\b\d+\b", lambda m: cardinal(int(m[0]), lang), s)  # übrige Ganzzahlen ausschreiben
    return re.sub(r"\s+", " ", s).strip()
