"""SiteVox – KI-Assistent für Bauleiter (AN-Seite): Dokumentation, Tagesberichte, Anzeigen.

Paketstruktur
-------------
understand/  Verstehen: ASR (Whisper), Foto (Qwen3-VL), Dokumente (Docling), E-Mail, LLM-Extraktion
engine/      Deterministische Regeln: Terminplan/CPM, Soll-Ist, Alarme, Risikosphäre, Fristen, Wetter
drafting/    Briefentwürfe: Jinja2-Vorlage als Gerüst, LLM füllt nur Sachverhalt + Auswirkungen
verify.py    Faktenprüfung: jede Zahl/jedes Datum/jeder Name muss in den Belegen stehen
confidence.py Feld-Konfidenz aus Belegen, ASR-Score, Sampling-Konsistenz, Retrieval, Regeln
export/      DOCX / PDF / Outlook-Entwurf (.eml, Graph mit Mail.ReadWrite – niemals Mail.Send)
store.py     SQLite
pipeline.py  Orchestrierung Erfassung → Beleg → Ereignis → Abweichung → Entwurf

Disclaimer: Entwurf – keine Rechtsberatung, Prüfung durch Bauleitung/Unternehmen erforderlich.
"""

DISCLAIMER = "Entwurf – keine Rechtsberatung, Prüfung durch Bauleitung/Unternehmen erforderlich."
__version__ = "0.1.0"
