"use client";
import { createContext, ReactNode, useContext, useEffect, useState } from "react";

export type Lang = "de" | "en";

/**
 * UI-Übersetzung. Schlüssel = deutscher Originaltext, damit Deutsch ohne Wörterbuch funktioniert.
 * Feste Texte aus der Engine (Fristen, Sphären-Begründungen, Auswirkungsketten …) werden ebenfalls übersetzt.
 * Bewusst NICHT übersetzt: Schreiben an den AG (deutscher Vertrag, VOB/B) und Freitext aus Erfassungen.
 */

/**
 * Projektbegriffe (Vorgänge aus dem Bauzeitenplan, Geräte, Kolonnen). Gelten als exakte Einträge UND innerhalb
 * zusammengesetzter Engine-Texte (Auswirkungsketten, Alarme). BP = Bodenplatte, EG = Erdgeschoss, BA = Bauabschnitt.
 */
const TERMS: Record<string, string> = {
  "Vertragsfrist Rohbau EG": "Contractual deadline shell ground floor",
  "Baustelleneinrichtung": "Site setup",
  "Aushub BA1": "Excavation section 1",
  "Schalung Rand": "Edge formwork",
  "Bewehrung BP": "Rebar base slab",
  "Betonage BP": "Concreting base slab",
  "Wände EG": "Walls ground floor",
  "Kolonne Müller": "Müller crew",
  "Kolonne Schalung": "Formwork crew",
  "Erdbau": "Earthworks",
  "Bagger": "Excavator",
  "Betonpumpe": "Concrete pump",
};
const reEscape = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

const EN: Record<string, string> = {
  // Navigation / Shell
  "Projekte": "Projects", "Dashboard": "Dashboard", "Erfassungen": "Captures", "Bauzeitenplan": "Schedule",
  "Schreiben": "Notices", "Postfach": "Mailbox", "Vertrag / LV": "Contract / BoQ", "Export": "Export",
  "Baustellen-Modus": "Site mode", "Container-Büro": "Site office", "Baustelle": "On site",
  "Dashboard, Prüfung, Export": "Dashboard, review, export", "Sprachmemo, Foto, Notiz": "Voice memo, photo, note",
  "KI-Assistent für die Bauleitung – Dokumentation, Tagesberichte, Anzeigen.": "AI assistant for site managers – documentation, daily reports, notices.",
  "{n} fristgebundene Schreiben offen": "{n} time-critical notices open",
  "Entwurf – keine Rechtsberatung, Prüfung durch Bauleitung/Unternehmen erforderlich":
    "Draft – not legal advice, review by site management/company required",
  "{n} AT": "{n} WD", "ID": "ID",
  "Fortschritt der Kolonne": "Crew progress", "lädt …": "loading …", "Schließen": "Close", "Sprache": "Language",
  "API nicht erreichbar: {e}. Läuft das Backend (uvicorn backend.main:app)?": "API unreachable: {e}. Is the backend running (uvicorn backend.main:app)?",

  // Dashboard
  "1 Projektübersicht": "1 Project overview", "2 Heute": "2 Today", "3 Handlungsbedarf": "3 Action required",
  "Projektübersicht": "Project overview", "Heute": "Today", "Handlungsbedarf": "Action required",
  "Vertrag": "Contract", "Auswirkung:": "Impact:", "Gesamtlaufzeit": "Full duration", "Tagesziel": "daily target",
  "Fortschritt": "Progress", "Soll": "Plan", "Ist": "Actual", "Verzug krit. Pfad": "Critical path delay",
  "Nächste Vertragsfrist": "Next contractual deadline", "Prognose": "Forecast", "Rückstand": "Backlog",
  "Gesamtfortschritt": "Overall progress",
  "Gewichtet nach LV-Summen. Ist {a}, Soll laut Bauzeitenplan {b}.": "Weighted by BoQ value. Actual {a}, planned per schedule {b}.",
  "Verzug kritischer Pfad": "Critical path delay",
  "Fällig am {d} – in {n} Arbeitstagen. Prognose bei aktuellem Tempo: {f}": "Due {d} – in {n} working days. Forecast at current pace: {f}",
  ", {n} AT Überschreitung": ", overrun {n} WD",
  "Tagesziel erreicht": "Daily target reached", "Personal": "Workforce", "Wetter (DWD)": "Weather (DWD)", "üblich": "normal",
  "Mit LV-Einheitspreisen gewichteter Anteil der heute geplanten Leistung:": "Share of today's planned output, weighted by BoQ unit prices:",
  "{c}: {p} anwesend (Soll {s})": "{c}: {p} present (plan {s})", "Gesamt": "Total",
  "Wetter (DWD via Bright Sky)": "Weather (DWD via Bright Sky)", "keine Daten": "no data",
  "§ 6 Abs. 2 Nr. 2 VOB/B: übliche Witterung ist keine Behinderung.": "§ 6 (2) No. 2 VOB/B: normal weather is not an obstruction.",
  "Niederschlag": "Precipitation", "Böen": "Gusts",
  "Tagesleistung je Vorgang · Strich = Tagessoll": "Daily output per activity · line = daily target",
  "{n} heute": "{n} today", "Tagessoll": "Daily target", "Ursache": "Cause",
  "Tagesverlauf {a}–{b} Uhr · Symbole = Erfassungen": "Daily timeline {a}–{b} · icons = captures",
  "Verknüpft mit": "Linked to", "In Erfassungen öffnen": "Open in captures", "Planmäßiger Einsatz.": "Planned operation.",
  "{n} Schreiben offen": "{n} notices open", "Bautagesbericht exportieren": "Export daily site report",
  "Review-Queue öffnen": "Open review queue", "Im Bauzeitenplan öffnen": "Open in schedule",
  "kritischer Pfad": "critical path", "Vertragsfrist {d}": "Contractual deadline {d}", "(im Plan)": "(on schedule)",
  "Gesamt {a} / {b}": "Total {a} / {b}", "Prognose Ende": "Forecast finish",
  "Prognose bei aktuellem Tempo: Ø {r}/AT, Rest {x}": "Forecast at current pace: avg {r}/WD, remaining {x}",
  "Puffer (Endtermin): {n} AT": "Float (finish): {n} WD", "Soll bis heute": "planned to date", "Heute:": "Today:",
  "von": "of", "Erfassungen ": "Captures ",

  // Legend / timeline
  "Arbeit": "Working", "eingeschränkt": "restricted", "Stillstand": "Idle", "geplant, nicht begonnen": "planned, not started",
  "Zusatzleistung": "Additional work", "nicht im LV": "not in BoQ", "LV prüfen": "check BoQ", "potenzieller Nachtrag": "potential claim",

  // Events
  "Materiallieferverzug": "Material delay", "Geräteausfall": "Equipment failure", "Witterung": "Weather",
  "Personalmangel": "Worker shortage", "Behinderung durch Dritte": "Third-party interference",
  "Planungsfehler": "Design error", "Qualitätsmangel": "Quality defect", "Zusätzliche Leistung": "Additional work",
  "Planlieferverzug / fehlende Mitwirkung": "Late drawings / missing client cooperation",
  "Leistungsänderung (AG-Anordnung)": "Change of scope (client order)",
  "Behinderungsanzeige": "Notice of obstruction (Behinderungsanzeige)",
  "Mehrkostenankündigung": "Notice of additional costs (Mehrkostenankündigung)",
  "Nachtragsankündigung": "Notice of variation (Nachtragsankündigung)",
  "Bedenkenanzeige": "Notice of concern (Bedenkenanzeige)", "Bautagebuch-Eintrag": "Site diary entry",
  "Interne Warnung": "Internal warning",
  "AG-Sphäre": "Client risk (AG)", "AN-Sphäre": "Contractor risk (AN)", "neutral": "neutral", "Vorschlag": "suggestion",
  "von Bauleitung bestätigt": "confirmed by site management",
  "Vorschlag – menschliche Bestätigung erforderlich": "Suggestion – human confirmation required",
  "Vorschlag, menschliche Bestätigung erforderlich.": "Suggestion, human confirmation required.",
  "Regel": "Rule", "KI-Einschätzung": "AI assessment", "{s} bestätigen": "Confirm {s}", "Empfehlung": "Recommendation",
  "Auswirkung (Engine)": "Impact (engine)", "Konfidenz": "Confidence",
  "Feld-Konfidenz (ohne LLM-Selbstauskunft)": "Field confidence (no LLM self-report)",
  "Ereignistyp": "Event type", "Risikosphäre": "Risk sphere", "Beginn": "Start", "Betroffene Vorgänge": "Affected activities",
  "Auswirkung (AT)": "Impact (WD)", "Belege": "Evidence", "ASR": "ASR", "Konsistenz": "Consistency", "Retrieval": "Retrieval",
  "kein Schreiben an AG": "no notice to client", "nur Bautagebuch": "site diary only", "Entwurf erstellen": "Create draft",
  "Entwurf bearbeiten": "Edit draft", "rot": "red", "seit {t}": "for {t}",
  "Belege öffnen": "Open evidence", "Bearbeiten": "Edit",
  "Konfidenz aus Belegen, ASR-Score, Sampling-Konsistenz, Retrieval und Regeln (keine LLM-Selbstauskunft)":
    "Confidence from evidence, ASR score, sampling consistency, retrieval and rules (no LLM self-report)",

  // Engine fixed texts
  "unverzüglich schriftlich anzeigen": "notify in writing without delay",
  "vor Ausführungsbeginn ankündigen": "announce before execution starts",
  "Ausführung bereits begonnen – Ankündigung verspätet?": "Execution already started – announcement late?",
  "möglichst vor Ausführung vereinbaren": "agree before execution if possible",
  "unverzüglich, möglichst vor Beginn der Arbeiten": "without delay, ideally before work starts",
  "keine Frist": "no deadline", "versendet": "sent",
  "Beschaffungsrisiko liegt beim AN; bei AG-Beistellung AG": "Procurement risk lies with contractor; client if client-supplied",
  "Eigene Geräte – Risiko des AN": "Own equipment – contractor's risk",
  "Übliche Witterung ist einzukalkulieren (§ 6 Abs. 2 Nr. 2)": "Normal weather must be priced in (§ 6 (2) No. 2)",
  "Eigene Personaldisposition – Risiko des AN": "Own staffing – contractor's risk",
  "Nur Vorunternehmer des AG fallen in die AG-Sphäre": "Only the client's preceding contractors fall into the client's sphere",
  "Planung wird vom AG geschuldet": "Design is owed by the client",
  "Eigene Leistung AN; Vorleistung anderer Unternehmer → AG": "Own work → contractor; prior work by others → client",
  "Vom AG geforderte, nicht vereinbarte Leistung": "Work requested by client, not in contract",
  "Planbeistellung ist Mitwirkungspflicht des AG": "Providing drawings is the client's duty to cooperate",
  "Anordnung des AG": "Client's order", "Vom AG beigestelltes Material": "Client-supplied material",
  "DWD-Werte über den vereinbarten/üblichen Schwellen": "DWD values above agreed/normal thresholds",
  "DWD-Werte im üblichen Rahmen – keine Behinderung (§ 6 Abs. 2 Nr. 2)": "DWD values within normal range – no obstruction (§ 6 (2) No. 2)",
  "Vorunternehmer im Auftrag des AG": "Preceding contractor engaged by client", "Mangel einer Vorleistung": "Defect in prior work",
  "Nur Dokumentation im Bautagebuch": "Site diary documentation only",
  "Zusätzliche Leistung: Mehrkosten vor Ausführung ankündigen": "Additional work: announce extra costs before execution",
  "Geänderte Leistung: neuen Preis vereinbaren": "Changed work: agree new price",
  "Technische Bedenken schriftlich mitteilen (ggf. zusätzlich Behinderung)": "Raise technical concerns in writing (possibly also obstruction)",
  "Bedenken gegen Vorleistung anderer Unternehmer": "Concerns about prior work by other contractors",
  "Eigener Mangel: intern beseitigen (§ 4 Abs. 7)": "Own defect: fix internally (§ 4 (7))",
  "AN-Risiko; AG kann bei unzureichender Besetzung Abhilfe verlangen (§ 5 Abs. 3)": "Contractor's risk; client may demand remedy if understaffed (§ 5 (3))",
  "AN-Risiko: Bautagebuch + interne Warnung, kein Schreiben an AG": "Contractor's risk: site diary + internal warning, no notice to client",
  "Behinderung aus AG-Sphäre bzw. unabwendbarer Umstand": "Obstruction from client's sphere or unavoidable circumstance",
  "Behinderung möglich – Auswirkung prüfen": "Possible obstruction – check impact",
  "Anordnung durch Architekt – Vollmacht prüfen, Ankündigung an AG richten": "Ordered by architect – check authority, address notice to client",
  "Ausführung bereits begonnen – Ankündigung muss VOR Ausführung erfolgen": "Execution already started – announcement must be made BEFORE execution",
  "Regelkonflikt: AN-Sphäre, aber Anzeige an AG vorgeschlagen": "Rule conflict: contractor's sphere, but notice to client suggested",
  "im Rahmen der üblichen Witterung – keine Behinderung": "within normal weather – no obstruction",
  "Eingangsgröße nur 'voraussichtlich' zugesagt": "input only 'expected', not confirmed",

  // Letters list / editor
  "Status: {s}. „Versendet“ setzt nur die Bauleitung nach eigenem Versand.": "Status: {s}. Only site management sets “Sent” after sending it themselves.",
  "Entwurf": "Draft", "Geprüft": "Approved", "Versendet": "Sent", "Verworfen": "Rejected",
  "erstellt {d}": "created {d}", "{n} nicht belegt": "{n} unsupported",
  "Noch keine Schreiben. Entwürfe entstehen aus „Handlungsbedarf“ im Dashboard.": "No notices yet. Drafts are created from “Action required” on the dashboard.",
  "Freigeben": "Approve", "Verwerfen": "Reject", "Übernehmen": "Accept",
  "Review-Queue (unsicherste zuerst):": "Review queue (least certain first):",
  "Felder · Farbe = Konfidenz": "Fields · colour = confidence",
  "Empfänger": "Recipient", "Vertragsnummer": "Contract no.", "Beginn des Ereignisses": "Event start",
  "Risikosphäre (Vorschlag)": "Risk sphere (suggestion)", "Voraussichtliche Auswirkung (AT)": "Expected impact (WD)",
  "Rechtsgrundlage (aus Vorlage)": "Legal basis (from template)", "Zustellweg": "Delivery method",
  "aus Vertragsstammdaten": "from contract master data", "berechnet von der Engine; Eingangsgrößen aus Belegen": "computed by engine; inputs from evidence",
  "Normzitat ausschließlich aus Vorlage": "legal citation from template only", "Firmenstandard – bitte bestätigen": "company standard – please confirm",
  "{n} Arbeitstage": "{n} working days",
  "Schreibentext bleibt deutsch (an deutschen AG nach VOB/B).": "Letter text stays German (addressed to the German client under VOB/B).",
  "[Vorlage]": "[template]", "KI-Text · jeder Satz belegt": "AI text · every sentence cited", "bearbeitet": "edited",
  "bearbeiten": "edit", "Speichern & neu prüfen": "Save & re-check", "Abbrechen": "Cancel", "Bezug:": "Reference:",
  "Faktenprüfung": "Fact check", "alle Werte belegt": "all values supported",
  "{n} Zahlen/Daten/Namen geprüft": "{n} numbers/dates/names checked", "Satz {n}": "sentence {n}",
  "belegt in {x}": "found in {x}", "andere Quelle": "other source", "manuell bestätigen": "confirm manually",
  "Wodurch ist der Wert belegt? (geht ins Audit-Log)": "What supports this value? (goes into the audit log)",
  "Datum in keinem Beleg gefunden": "date not found in any evidence", "Uhrzeit in keinem Beleg gefunden": "time not found in any evidence",
  "Zahl in keinem Beleg gefunden": "number not found in any evidence", "Name in keinem Beleg gefunden": "name not found in any evidence",
  "Satz ohne gültigen Beleg": "sentence without valid evidence",
  "Normzitat im KI-Text – nur aus Vorlage zulässig": "legal citation in AI text – only allowed from template",
  "Checkliste vor Freigabe": "Checklist before approval",
  "Empfänger ist der Auftraggeber bzw. dessen bevollmächtigter Vertreter": "Recipient is the client or its authorised representative",
  "Vertragsnummer korrekt": "Contract number correct",
  "Tatsachen, Ursache und voraussichtliche Auswirkungen sind benannt": "Facts, cause and expected impact are stated",
  "Zustellweg mit Nachweis festgelegt (E-Mail vorab + Einschreiben/Bote)": "Delivery method with proof set (email first + registered mail/courier)",
  "Freigegeben von {a} am {d}": "Approved by {a} on {d}", "PDF n/v": "PDF n/a",
  "LibreOffice (soffice) auf dem Server installieren": "Install LibreOffice (soffice) on the server",
  "Outlook-Entwurf (.eml)": "Outlook draft (.eml)",
  "SiteVox versendet nichts. Entwurf in Outlook öffnen, prüfen und selbst auf „Senden“ klicken.": "SiteVox sends nothing. Open the draft in Outlook, review it and click “Send” yourself.",
  "E-Mail vorab + Einschreiben mit Rückschein": "Email first + registered mail with return receipt",
  "E-Mail vorab + Bote mit Empfangsbestätigung": "Email first + courier with receipt", "Übergabe gegen Unterschrift": "Hand delivery against signature",
  "Habe ich versendet": "I have sent it", "Versendet am {d}": "Sent on {d}", "Audit-Log ({n})": "Audit log ({n})",
  "Belege zur Auswahl": "Evidence for selection", "Belege – Feld, Satz oder [E-xx] anklicken": "Evidence – click a field, sentence or [E-xx]",
  "Kein Rohbeleg für diese Stelle.": "No raw evidence for this item.",
  "Wert stammt aus Vorlage/Firmenstandard – bitte bewusst übernehmen.": "Value comes from template/company standard – accept deliberately.",
  "Alle Belege": "All evidence", "Normzitat nur aus Vorlage": "citation from template only",
  "Nicht belegt": "Unsupported", "Checkliste": "Checklist", "Feld": "Field",
  "unsicher – bitte übernehmen, bearbeiten oder verwerfen": "uncertain – please accept, edit or reject", "Pflichtfeld": "Required field",

  // Evidence
  "Sprachmemo": "Voice memo", "Foto": "Photo", "E-Mail": "Email", "Notiz": "Note", "Dokument": "Document",
  "Berechnung (Engine)": "Calculation (engine)", "ab {t}": "from {t}", "Abschnitt {a}–{b} s": "segment {a}–{b} s",
  "ASR-Score {s}": "ASR score {s}", "Von {f} · {s}": "From {f} · {s}", "Originaltext": "Original text", "Seite {n}": "Page {n}",
  "Retrieval-Relevanz {r}": "retrieval relevance {r}", "lädt {id} …": "loading {id} …", "Qwen3-VL-Beschreibung": "Qwen3-VL description",

  // Foto: KI-Beobachtung, Rückfrage, Antwort
  "KI-Beobachtung": "AI observation", "KI-Beobachtung – kein Beleg": "AI observation – not evidence",
  "durch Antwort gestützt": "supported by answer", "verworfen": "rejected",
  "visuelle Sicherheit {c}": "visual confidence {c}", "bestätigen": "confirm", "verwerfen": "reject", "zurücksetzen": "reset",
  "Ausschnitt aus dem Originalfoto": "Crop of the original photo", "Detailfoto": "Detail photo", "Originalfoto": "Original photo",
  "nur KI-Beobachtung": "AI observation only", "Beobachtung bestätigen": "Confirm observation",
  "Satz stützt sich nur auf eine KI-Beobachtung (kein Beleg) – bitte bestätigen": "Sentence relies only on an AI observation (not evidence) – please confirm",
  "Haben Sie den Befund vor Ort bzw. auf dem Foto geprüft? Kurze Notiz (Audit-Log):": "Did you check the finding on site / on the photo? Short note (audit log):",
  "Foto aufnehmen, danach kurz beschreiben – per Sprache oder Notiz": "Take a photo, then describe it briefly – by voice or note",
  "Foto beschreiben": "Describe photo", "Per Sprache beschreiben": "Describe by voice", "Als Notiz beschreiben": "Describe as note",
  "Stopp & speichern": "Stop & save", "Foto + Notiz speichern": "Save photo + note", "Ohne Beschreibung speichern": "Save without description",
  "Zurück": "Back", "Beschreiben": "Describe",
  "Foto ohne Beschreibung gespeichert": "Photo saved without description",
  "Foto mit Beschreibung übertragen – wird ausgewertet": "Photo with description uploaded – processing",
  "Was ist zu sehen – und warum? Wer, seit wann, welche Arbeiten, wie viel?": "What do you see – and why? Who, since when, which works, how much?",
  "z. B. „Riss in der Wand Achse C, Vorleistung Rohbauer, seit heute Morgen“": "e.g. “Crack in wall axis C, previous trade's work, since this morning”",
  "Ursache, Verursacher und Mengen kommen nur aus Ihrer Beschreibung – nicht aus dem Foto.": "Cause, responsible party and quantities come only from your description – not from the photo.",
  "Rückfrage zum Foto {t}": "Question about photo {t}", "{n} offen": "{n} open", "Antwort sprechen": "Answer by voice",
  "… oder als Notiz antworten": "… or answer as a note", "Detailfoto mit Maßstab anhängen (optional)": "Attach detail photo with scale (optional)",
  "Ohne Antwort ablegen": "File without answer", "Später": "Later", "Rückfrage": "Question", "Fehler": "Error",
  "Die KI beschreibt nur, was zu sehen ist. Wer es verursacht hat und welches Schreiben nötig ist, ergibt sich aus Ihrer Antwort und dem Regelwerk.":
    "The AI only describes what is visible. Who caused it and which notice is needed follows from your answer and the rule set.",
  "Foto übertragen – KI wertet aus, danach eine Rückfrage": "Photo uploaded – AI is analysing, then one question",
  "Antwort übertragen – wird ausgewertet": "Answer uploaded – processing", "Foto ohne Antwort abgelegt": "Photo filed without answer",
  "{d} als Entwurf angelegt – Prüfung im Büro": "{d} created as draft – review in the office", "Im Bautagebuch dokumentiert": "Logged in the site diary",
  "Bestätigen": "Confirm", "bestätigt": "confirmed", "Rückfrage offen": "Question open", "in Arbeit": "processing",
  "Rückfrage:": "Question:", "Antwort:": "Answer:", "ohne Antwort abgelegt": "filed without answer",
  "Zugang/Zufahrt blockiert": "Access blocked", "stehendes Wasser": "Standing water", "Material auf der Arbeitsfläche": "Material on work area",
  "Gerät steht still": "Equipment idle", "Riss": "Crack", "Oberflächenfehler": "Surface defect", "Beschädigung": "Damage",
  "Bauzustand / Fortschritt": "Construction stage / progress", "Sicherheitsmangel": "Safety hazard",
  "Was ist hier passiert?": "What happened here?",
  "Wessen Material ist das, und seit wann ist der Zugang blockiert?": "Whose material is this, and since when has access been blocked?",
  "Wer blockiert den Zugang (Firma/Gewerk, im Auftrag des Bauherrn?), seit wann, und welche Arbeiten sind betroffen?":
    "Who is blocking access (company/trade, on behalf of the client?), since when, and which work is affected?",
  "Seit wann steht das Wasser, und welche Arbeiten können deshalb nicht ausgeführt werden?": "Since when has the water been standing, and which work cannot be carried out?",
  "Wessen Gerät ist das, warum steht es, und seit wann?": "Whose equipment is this, why is it idle, and since when?",
  "Ist das unsere Leistung oder eine Vorleistung? Bitte Detailfoto mit Maßstab.": "Is this our work or a previous trade's work? Please add a detail photo with scale.",
  "Ist das unsere Leistung oder eine Vorleistung? Wer hat es beschädigt? Bitte Detailfoto mit Maßstab.":
    "Is this our work or a previous trade's work? Who damaged it? Please add a detail photo with scale.",
  "Welche Menge wurde heute erledigt (z. B. t, m², m³), und für welchen Vorgang?": "What quantity was completed today (e.g. t, m², m³), and for which activity?",
  "Was ist hier passiert, und ist die Gefahrenstelle bereits gesichert?": "What happened here, and has the hazard already been secured?",
  "Foto zeigt Arbeitsfortschritt – Menge bitte per Sprache oder Notiz nachtragen (wird nicht aus dem Foto geschätzt).":
    "Photo shows progress – please add the quantity by voice or note (never estimated from the photo).",

  // Other pages
  "Bauzeitenplan · Stand {d}": "Schedule · as of {d}", "Vorgang": "Activity", "LV": "BoQ", "Verzug": "Delay", "Puffer": "Float", "Menge": "Quantity",
  "Berechnung deterministisch (CPM auf Arbeitstagen, Prognose = Restmenge / Ø-Leistung der letzten 3 AT, Blockaden aus Ereignissen). Import: Excel-Bauzeitenplan.":
    "Deterministic calculation (CPM on working days, forecast = remaining qty / avg output of last 3 WD, blockages from events). Import: Excel schedule.",
  "Offene Punkte & Termine": "Open items & deadlines", "ohne Termin": "no date",
  "Dem Projekt zugeordnete E-Mails (Mock: .eml-Ordner, später Graph mit Mail.ReadWrite)": "Emails assigned to this project (mock: .eml folder, later Graph with Mail.ReadWrite)",
  "Von {f} · An {t}": "From {f} · To {t}", "KI-Zusammenfassung": "AI summary", "Verknüpfte Ereignisse": "Linked events", "E-Mail auswählen": "Select an email",
  "Rechtsgrundlagen (VOB/B aktuelle Fassung)": "Legal basis (VOB/B current edition)", "Projektunterlagen": "Project documents",
  "Normzitate in Schreiben stammen ausschließlich aus den Vorlagen. Die Wissensbasis dient dem Nachweis und der Suche (BM25 + BGE-M3, Rerank).":
    "Legal citations in notices come only from templates. The knowledge base is for traceability and search (BM25 + BGE-M3, rerank).",
  "z. B. Behinderung unverzüglich schriftlich": "e.g. Behinderung unverzüglich schriftlich", "Suchen": "Search", "Relevanz": "relevance",
  "{n} S.": "{n} p.", "S. {n}": "p. {n}",
  "Bautagesbericht": "Daily site report",
  "Entwurf aus Erfassungen, Soll-Ist, Wetter (DWD), Ereignissen und Fotos (Gesichter automatisch verpixelt, mit Zeitstempel/GPS).":
    "Draft from captures, plan vs. actual, weather (DWD), events and photos (faces blurred automatically, with timestamp/GPS).",
  "Bautagesbericht {d} (DOCX)": "Daily site report {d} (DOCX)",
  "Bautagesbericht {d} (PDF)": "Daily site report {d} (PDF)",
  "im Bautagebuch dokumentiert": "logged in site diary", "offen": "open", "Zurücksetzen": "Reset",
  "Bestätigung zurücknehmen – Sphäre wieder als Vorschlag des Regelwerks": "Undo confirmation – risk sphere back to the rule-based suggestion",
  "Noch nicht bestätigt": "Not confirmed yet",
  "Ereignisse ohne Schreiben an den AG": "Events without a notice to the client",
  "Interne Ereignisse (AN-Risiko) und Ereignisse, für die noch kein Entwurf erstellt wurde.":
    "Internal events (contractor risk) and events without a draft yet.",
  "Freigabe zurückziehen": "Revoke approval", "Versand zurücknehmen": "Undo 'sent'", "Wiederherstellen": "Restore",
  "Verworfenes Schreiben wiederherstellen – es wird wieder zum Entwurf und kann geprüft und freigegeben werden. Begründung (geht ins Audit-Log):":
    "Restore the rejected notice – it goes back to draft and can be reviewed and approved. Reason (recorded in the audit log):",
  "Freigabe zurückziehen – das Schreiben wird wieder zum Entwurf. Begründung (geht ins Audit-Log):":
    "Revoke approval – the notice goes back to draft. Reason (recorded in the audit log):",
  "Versand-Markierung zurücknehmen – Status wird wieder „Geprüft“. Begründung (geht ins Audit-Log):":
    "Undo the 'sent' mark – status returns to approved. Reason (recorded in the audit log):",
  "Alle übernehmen ({n})": "Accept all ({n})", "{n} Punkte offen": "{n} items open", "Prüfen & freigeben": "Review & approve",
  "Übernimmt alle noch offenen Felder. Bearbeitete und verworfene Felder bleiben unverändert.":
    "Accepts all open fields. Edited and rejected fields stay unchanged.",
  "Export erst nach Freigabe. Outlook-Entwurf als .eml (X-Unsent) – der Versand erfolgt durch Sie.": "Export only after approval. Outlook draft as .eml (X-Unsent) – you send it.",
  "gesperrt bis Freigabe": "locked until approved",

  // Bearbeiten / Löschen
  "Ereignis bearbeiten": "Edit event", "Vorgang bearbeiten": "Edit activity", "Ist-Menge korrigieren": "Correct actual quantity",
  "Ist heute": "Actual today", "Leer lassen = Eintrag löschen": "Leave empty = delete entry",
  "Manuelle Korrektur der aus der Sprachnotiz übernommenen Menge (Audit-Log).": "Manual correction of the quantity taken from the voice memo (audit log).",
  "Projekt-Stammdaten": "Project master data",
  "Empfänger und Vertragsnummer neuer Schreiben werden aus diesen Stammdaten übernommen.": "Recipient and contract number of new notices are taken from this master data.",
  "Bauvorhaben": "Project", "Adresse Baustelle": "Site address", "Vertragsdatum": "Contract date", "Vertragsgrundlage": "Contract basis",
  "Auftraggeber": "Client (AG)", "Adresse AG": "Client address", "Bevollmächtigter Vertreter": "Authorised representative",
  "Funktion": "Role", "E-Mail AG": "Client email",
  "Risikosphäre, Empfehlung und Konfidenz werden nach dem Speichern regelbasiert neu berechnet.": "Risk sphere, recommendation and confidence are recomputed by the rules after saving.",
  "Gantt, Soll-Ist, kritischer Pfad und Prognose werden aus dem geänderten Bauzeitenplan neu berechnet.": "Gantt, plan vs. actual, critical path and forecast are recomputed from the edited schedule.",
  "Keine Änderungen": "No changes", "Gespeichert – Werte neu berechnet": "Saved – values recomputed",
  "Speichern": "Save", "Löschen": "Delete", "Gelöscht": "Deleted",
  "Wirklich löschen? (wird im Audit-Log protokolliert)": "Really delete? (recorded in the audit log)",
  "Beschreibung": "Description", "Ende": "End", "Anfang": "Start", "Typ": "Type", "Einheit": "Unit",
  "Kommagetrennt, z. B. Bewehrung BP, Betonage BP": "Comma-separated, e.g. Bewehrung BP, Betonage BP",
  "Blockiert bis (für Prognose)": "Blocked until (for forecast)", "Tagesverlauf: Gerät/Kolonne": "Daily timeline: equipment/crew",
  "Je Zeile: Ressource | work/restricted/idle/planned_not_started | Start | Ende": "One per line: resource | work/restricted/idle/planned_not_started | start | end",
  "Ausführung bereits begonnen (Zusatzleistung)": "Execution already started (additional work)",
  "Meilenstein (Vertragsfrist)": "Milestone (contractual deadline)", "LV-Position": "BoQ item", "LV-Summe (€)": "BoQ value (€)",
  "Gewichtung für den Gesamtfortschritt": "Weight for overall progress", "Vorgänger": "Predecessors",
  "z. B. A40FS-1; A30SS+4 (FS/SS, Lag in Arbeitstagen)": "e.g. A40FS-1; A30SS+4 (FS/SS, lag in working days)",
  "Synonyme (für Spracherkennung)": "Aliases (for speech matching)", "Semikolon-getrennt": "Semicolon-separated",
  "Neuer Vorgang": "New activity", "leer = automatisch": "empty = automatic",
  "Kolonne": "Crew", "Kolonne hinzufügen": "Add crew",
  "„Gesamt“ steuert die Kennzahl Personal; sonst Summe der Kolonnen.": "“Gesamt” (total) drives the workforce KPI; otherwise the sum of crews.",
  "Erfassung bearbeiten": "Edit capture", "Titel": "Title", "Zusammenfassung": "Summary", "Transkript": "Transcript", "Text": "Text",
  "Text korrigieren (z. B. Erkennungsfehler im Transkript) und optional neu auswerten lassen. Die Originaldatei bleibt erhalten.":
    "Correct the text (e.g. recognition errors in the transcript) and optionally re-analyse. The original file is kept.",
  "Nach dem Speichern neu auswerten (Ereignisse/Mengen neu ableiten)": "Re-analyse after saving (derive events/quantities again)",
  "Erfassung inkl. Datei löschen? Abgeleitete Mengen, Belege und Ereignisse werden mit entfernt (Audit-Log).":
    "Delete capture including file? Derived quantities, evidence and events are removed too (audit log).",
  "„{x}“ löschen? Abgeleitete Mengen, Belege und Ereignisse werden mit entfernt (Audit-Log).":
    "Delete “{x}”? Derived quantities, evidence and events are removed too (audit log).",
  "„{x}“ löschen?": "Delete “{x}”?", "korrigiert": "corrected",
  "Dokument hochladen": "Upload document", "Leistungsverzeichnis (LV)": "Bill of quantities (LV)", "Planlieferliste": "Drawing schedule",
  "Protokoll": "Minutes", "Sonstiges": "Other", "PDF / DOCX / Bild wählen": "Choose PDF / DOCX / image",
  "Ende liegt vor dem Anfang": "End is before start", "Rechtsgrundlagen sind schreibgeschützt": "Legal sources are read-only",
  "Ereignis gehört zu einem freigegebenen/versendeten Schreiben": "Event belongs to an approved/sent notice",

  // Wissensbasis + GAEB
  "Wissensbasis": "Knowledge base", "Keine Treffer": "No results",
  "Unterlagen, auf die sich Schreiben und Prüfungen stützen.": "Documents that notices and checks rely on.",
  "PDF / DOCX / GAEB / Bild wählen": "Choose PDF / DOCX / GAEB / image",
  "GAEB: DA XML (.x81–.x89), GAEB 2000 (.p8x) und GAEB 90 (.d8x) werden als LV mit Positionen eingelesen.": "GAEB: DA XML (.x81–.x89), GAEB 2000 (.p8x) and GAEB 90 (.d8x) are imported as a BoQ with line items.",
  "Suche schließen": "Close search", "Dokument links auswählen oder oben suchen": "Select a document on the left or search above",
  "GAEB-Export": "GAEB export", "GAEB-Austauschphase": "GAEB exchange phase",
  "X83 · Angebotsaufforderung": "X83 · Invitation to tender", "X84 · Angebotsabgabe": "X84 · Bid submission",
  "X86 · Auftragserteilung": "X86 · Contract award", "X81 · Leistungsbeschreibung": "X81 · Specification",
  "GAEB {v} · Phase {p} · {n} Positionen": "GAEB {v} · phase {p} · {n} items",

  // Belege nach Quelle
  "Alle Belege – je Quelle einmal": "All evidence – one entry per source", "Belege – je Quelle einmal": "Evidence – one entry per source",
  "{n} Fundstellen": "{n} passages",

  // Postfach verbinden
  "Postfach verbinden": "Connect mailbox", "Anbieter": "Provider", "E-Mail-Adresse": "Email address", "App-Passwort": "App password",
  "E-Mails zu diesem Projekt werden abgeholt, zugeordnet und ausgewertet. Nur lesender Zugriff – nichts wird gelöscht oder als gelesen markiert.": "Emails for this project are fetched, assigned and analysed. Read-only – nothing is deleted or marked as read.",
  "Nur E-Mails übernehmen, die diesem Projekt zugeordnet werden (Vertragsnummer, Projektname, bekannte Absender)": "Only import emails assigned to this project (contract no., project name, known senders)",
  "Erweiterte Einstellungen": "Advanced settings", "Erweiterte Einstellungen ausblenden": "Hide advanced settings",
  "IMAP-Server": "IMAP server", "Port": "Port", "Verschlüsselung": "Encryption", "Benutzername (falls abweichend)": "Username (if different)",
  "Ordner": "Folder", "Zeitraum (Tage)": "Period (days)",
  "Das Passwort wird nicht gespeichert, sondern nur im Arbeitsspeicher des lokalen Servers gehalten. Nach einem Neustart muss es erneut eingegeben werden.": "The password is not stored; it is only kept in the local server's memory and must be re-entered after a restart.",
  "Verbindung wird getestet …": "Testing connection …", "Verbinden & testen": "Connect & test", "folgt (OAuth)": "coming (OAuth)",
  "Gmail": "Gmail", "GMX": "GMX", "WEB.DE": "WEB.DE", "T-Online": "T-Online", "IONOS": "IONOS",
  "Anderer IMAP-Server": "Other IMAP server", "Microsoft 365 / Outlook": "Microsoft 365 / Outlook",
  "Google-Konto → Sicherheit → App-Passwörter (2-Faktor muss aktiv sein)": "Google account → Security → App passwords (2-step verification required)",
  "In GMX unter E-Mail → Einstellungen → POP3/IMAP Abruf zuerst IMAP erlauben": "In GMX, first allow IMAP under Email → Settings → POP3/IMAP",
  "In WEB.DE unter Einstellungen → POP3/IMAP Abruf zuerst IMAP erlauben": "In WEB.DE, first allow IMAP under Settings → POP3/IMAP",
  "Eigenes E-Mail-Passwort aus dem Kundencenter verwenden": "Use the email password from the customer centre",
  "Serverdaten beim E-Mail-Anbieter / der IT erfragen": "Ask your email provider / IT for the server details",
  "Microsoft erlaubt IMAP nur noch mit OAuth – Anbindung über Microsoft Graph folgt": "Microsoft only allows IMAP with OAuth – Microsoft Graph integration coming",
  "{n} neue E-Mail(s) übernommen · {d} bereits vorhanden · {o} anderes Projekt": "{n} new email(s) imported · {d} already present · {o} other project",
  "App-Passwort für {a} eingeben (wird nicht gespeichert):": "Enter app password for {a} (not stored):",
  "Verbindung zu {a} trennen? Bereits übernommene E-Mails bleiben erhalten.": "Disconnect {a}? Imported emails are kept.",
  "verbunden": "connected", "Passwort erforderlich": "password required", "zuletzt": "last", "Abrufen": "Fetch", "Passwort": "Password", "Trennen": "Disconnect",

  // Mobile
  "Stopp": "Stop", "z. B. „Bagger steht seit 10 Uhr, Hydraulikschlauch …“": "e.g. “Excavator idle since 10am, hydraulic hose …” (German or English)",
  "Notiz / Stichworte": "Note / keywords", "Senden": "Upload", "Heute erfasst": "Captured today",
  "Übertragen – wird ausgewertet": "Uploaded – being analysed", "Fehler: {e}": "Error: {e}",
  "Mikrofon nicht verfügbar (HTTPS bzw. Berechtigung nötig)": "Microphone unavailable (HTTPS or permission required)",
  // Dashboard = Bautagesbericht-Abschnitte
  "Heute beachten": "Attention today", "Bautagesbericht Nr. {n}": "Daily report No. {n}",
  "Tagesfortschritt": "Daily progress", "Plan → Prognose Ende": "Planned → forecast end", "Ist / Tagessoll": "actual / daily target",
  "Keine Fortschritts-Erfassungen an diesem Tag.": "No progress captures on this day.", "Vergrößern": "Enlarge",
  "noch nicht freigegeben": "not yet released", "noch nicht erstellt": "not yet drafted",
  "{doc} „{ev}“ {state} – {dl}": "{doc} “{ev}” {state} – {dl}", "{c}: {n} von {p} Personen": "{c}: {n} of {p} workers",
  "Meilenstein gefährdet": "Milestone at risk", "seit {a}": "since {a}",
  "Arbeitsfähigkeit": "Workability", "gegeben": "given", "nicht gegeben": "not given",
  "trocken": "dry", "Regen": "rain", "Keine Wetterdaten erfasst.": "No weather data recorded.",
  "Personaleinsatz": "Workforce", "Firma / Kolonne": "Company / crew", "Gewerk": "Trade", "Stunden": "Hours",
  "davon Stillstand": "of which idle", "Summe": "Total", "Bewehrung": "Reinforcement", "Schalung": "Formwork", "Aushub": "Excavation",
  "* nicht einzeln erfasst – aus der gemeldeten Gesamtzahl abgeleitet.": "* not recorded individually – derived from the reported total.",
  "Geräteeinsatz": "Equipment", "Gerät": "Equipment", "Status": "Status", "Soll h": "Planned h", "Ist h": "Actual h",
  "Ausfallzeit": "Downtime", "im Einsatz": "in operation", "Ausfall": "breakdown", "nicht eingesetzt": "not deployed",
  "Kein Großgerät im Tagesverlauf erfasst.": "No heavy equipment recorded today.",
  "Lieferungen": "Deliveries", "Lieferant": "Supplier", "Material": "Material", "geplant": "planned", "tatsächlich": "actual",
  "pünktlich": "on time", "ja": "yes", "{n} min Verzug": "{n} min late", "Lieferschein": "Delivery note",
  "Keine Lieferungen erfasst.": "No deliveries recorded.",
  // E-Mail-Empfänger der Anzeigen
  "An:": "To:", "E-Mail Empfänger (AG)": "Recipient email (client)",
  "E-Mail-Adresse des AG fehlt – bitte prüfen und eintragen": "Client email address missing – please check and enter it",
  "Keine E-Mail-Adresse des AG bzw. seines bevollmächtigten Vertreters in den hochgeladenen Unterlagen gefunden – Bauleitung bitte prüfen und eintragen (oder verwerfen, wenn nur per Post zugestellt wird).":
    "No email address of the client or its authorised representative found in the uploaded documents – site manager, please check and enter it (or reject the field if delivered by post only).",
  "„E-Mail Empfänger (AG)“ fehlt – Adresse eintragen oder Feld verwerfen (nur Postversand)":
    "“Recipient email (client)” missing – enter the address or reject the field (post only)",
  // Sendedialog (Versand über gebundenes Postfach)
  "Schreiben per E-Mail an den AG senden": "Send notice to the client by email", "Von": "From", "An": "To", "Cc": "Cc",
  "Betreff": "Subject", "Anhang": "Attachment", "Jetzt senden": "Send now", "sendet …": "sending …", "Entsperren": "Unlock",
  "gesperrt": "locked", "App-Passwort des Postfachs": "Mailbox app password", "optional, mehrere mit Komma": "optional, separate with commas",
  "Kein Postfach gebunden": "No mailbox connected", "Per E-Mail an AG senden …": "Send to client by email …",
  "Erst freigeben – nur geprüfte Schreiben können gesendet werden": "Approve first – only approved notices can be sent",
  "Keine E-Mail-Adresse des AG im Feld „E-Mail Empfänger (AG)“": "No client email address in the field “Recipient email (client)”",
  "Kein Postfach gebunden – unter „Postfach“ verbinden": "No mailbox connected – connect one under “Mailbox”",
  "Postfach gesperrt – Passwort eingeben": "Mailbox locked – enter password",
  "Kein Export des Schreibens vorhanden": "No export of the notice available",
  "Original per Einschreiben mit Rückschein versenden (E-Mail allein wahrt die Schriftform ggf. nicht)":
    "Send the original by registered mail with return receipt (email alone may not satisfy the written-form requirement)",
  "Original versendet": "Original sent", "Original versendet: {m}": "Original sent: {m}",
  "Einschreiben mit Rückschein": "Registered mail with return receipt", "Bote mit Empfangsbestätigung": "Courier with receipt",
  "Per E-Mail gesendet an {to} von {from} am {d}": "Emailed to {to} from {from} on {d}",
  "SiteVox sendet nur nach Ihrer Bestätigung im Sendedialog über das gebundene Postfach. Alternativ: Outlook-Entwurf öffnen und selbst senden.":
    "SiteVox only sends after you confirm in the send dialog, via the connected mailbox. Alternatively open the Outlook draft and send it yourself.",
  "SMTP-Server (Versand, leer = automatisch)": "SMTP server (sending, empty = automatic)", "SMTP-Port": "SMTP port",
  "Gerät hinzufügen": "Add equipment", "Name fehlt": "Name missing", "Zeile entfernen": "Remove row",
  "Zeile „{n}“ aus dem Bericht entfernen?": "Remove row “{n}” from the report?", "manuell": "manual",
  "manuell geändert": "edited manually", "Manuelle Änderung verwerfen": "Discard manual change",
  "Doppelklick auf eine Zeile = bearbeiten · blau hinterlegt = manuell geändert · gilt auch für den PDF-Bericht":
    "Double-click a row to edit · blue = edited manually · also applies to the PDF report",
  "An diesem Tag beachten": "Attention on this day", "Verlauf": "History", "Verlauf – Bericht vom {d}": "History – report of {d}", "Alle Tage": "All days", "Zu heute": "Back to today",
  "Frühere Tage als komplettes Dashboard ansehen": "View earlier days as the full dashboard",
  "Noch keine Berichtstage vorhanden.": "No report days yet.", "{n} Erfassungen": "{n} captures", "{n} Ereignisse": "{n} events",
  "Projekt bearbeiten": "Edit project", "Kurzname": "Short name",
  "offen seit {d}": "open since {d}",
  "Kontakte": "Contacts", "Kontakt hinzufügen": "Add contact", "Kontakt bearbeiten": "Edit contact", "Firma": "Company",
  "Telefon": "Phone", "Vollmacht": "Authority", "unbekannt": "unknown", "bevollmächtigt": "authorised",
  "nicht bevollmächtigt": "not authorised", "bevollmächtigt (Anzeigen an diese Person)": "authorised (notices go to this person)",
  "Suchen …": "Search …", "Entfernen": "Remove", "Fundstellen": "Found in",
  "Empfänger für Anzeigen": "Recipient for notices", "Stammdaten": "Master data",
  "„{x}“ aus den Kontakten entfernen?": "Remove “{x}” from contacts?",
  "Automatisch aus Vertrag, Unterlagen und E-Mails dieses Projekts erkannt – mit Fundstelle. Im Sendedialog per Klick als Empfänger übernehmen.":
    "Detected automatically from this project's contract, documents and e-mails – with source. Pick them as recipients in the send dialog.",
  "Noch keine Kontakte erkannt – Vertrag oder E-Mails hochladen bzw. Postfach verbinden.": "No contacts yet – upload the contract or e-mails, or connect a mailbox.",
  "als Cc": "as Cc",
  "{x} ist laut Vertrag nicht bevollmächtigt – eine Anzeige an diese Adresse ist ggf. unwirksam.":
    "{x} is not authorised under the contract – a notice sent to this address may be ineffective.",
  "Aus dem Vertrag erkannt": "Detected in the contract", "Alle übernehmen": "Apply all", "bisher": "currently",
  "Alle erkannten Angaben stimmen mit den Stammdaten überein.": "All detected details match the master data.",
  "Telefon AG": "Client phone", "Beteiligte ohne Vollmacht": "Parties without authority",
  "Vertragsfristen": "Contract deadlines", "E-Mail AG (Empfänger der Anzeigen)": "Client e-mail (recipient of notices)",
  "Leer lassen, was im Vertrag steht – nach dem Hochladen des Vertrags füllt SiteVox leere Felder automatisch (mit Fundstelle).":
    "Leave blank what is in the contract – after the contract upload SiteVox fills empty fields automatically (with source).",
  "DWD · automatisch": "DWD · automatic",
  "Keine Wetterdaten – Koordinaten der Baustelle in den Projekt-Stammdaten eintragen": "No weather data – enter the site coordinates in the project master data",
  "Wetterdienst gerade nicht erreichbar – wird automatisch erneut versucht": "Weather service unreachable – retrying automatically",
  "Koordinaten Baustelle (Breite, Länge) – für das Wetter": "Site coordinates (lat, lon) – for weather",
  "In Google Maps: Rechtsklick auf die Baustelle → erste Zeile (Koordinaten) anklicken = kopiert.": "In Google Maps: right-click the site → click the first line (coordinates) to copy.",
  "Rechtsgrundlagen": "Legal basis", "Hinzufügen": "Add", "Hochladen": "Upload", "Archivieren": "Archive",
  "Rechtsgrundlage hinzufügen": "Add legal text", "Neue Fassung hochladen": "Upload new version",
  "Fassung / Stand": "Version / as of", "z. B. Ausgabe 2026, Stand 01.10.2026": "e.g. 2026 edition, as of 01/10/2026",
  "wird eingelesen …": "reading …", "ersetzt": "superseded", "Frühere / archivierte Fassungen": "Earlier / archived versions",
  "PDF (mit Textebene), DOCX, TXT oder MD hierher ziehen oder auswählen": "Drop or select a PDF (with text layer), DOCX, TXT or MD",
  "Gilt für alle Projekte. Der Text wird je Paragraph (§) in die Suche aufgenommen.": "Applies to all projects. The text is indexed per section (§).",
  "Ersetzt „{x}“. Die bisherige Fassung wird archiviert und nicht mehr für neue Schreiben herangezogen; bereits erstellte Schreiben behalten ihren Bezug.":
    "Replaces “{x}”. The previous version is archived and no longer used for new letters; existing letters keep their reference.",
  "„{x}“ archivieren? Sie wird dann nicht mehr für neue Schreiben herangezogen.": "Archive “{x}”? It will no longer be used for new letters.",
  "Unterlagen": "Documents", "Bauzeitenplan (Excel)": "Schedule (Excel)", "wird angelegt …": "creating …",
  "Vertrag, LV (auch GAEB), Bauzeitenplan (Excel), Protokolle … hierher ziehen oder auswählen":
    "Drop or select contract, BoQ (incl. GAEB), schedule (Excel), minutes …",
  "Dokumente landen in der Wissensbasis und werden im Hintergrund ausgewertet; der Bauzeitenplan liefert die Vorgänge für Dashboard und Bericht.":
    "Documents go to the knowledge base and are analysed in the background; the schedule provides the activities for dashboard and report.",
  "Projekt angelegt, {n} Datei(en) nicht übernommen – später unter Wissensbasis erneut hochladen.":
    "Project created, {n} file(s) failed – upload again later under Knowledge base.",
  "Entsperrt – E-Mails werden jetzt im Hintergrund abgerufen.": "Unlocked – fetching e-mails in the background now.",
  "Gesperrt – Passwort eingeben, dann wird automatisch abgerufen": "Locked – enter the password to enable automatic fetching",
  "Automatischer Abruf alle {n} Min.": "Auto-fetch every {n} min", "nächster": "next", "Automatischer Abruf aus": "Auto-fetch off",
  "Letzter Abruf fehlgeschlagen": "Last fetch failed",
  "Neues Projekt": "New project", "Kurzname *": "Short name *", "Anlegen": "Create", "Projekt löschen": "Delete project",
  "Projekt „{n}“ mit allen Erfassungen, Ereignissen und Schreiben löschen? Das kann nicht rückgängig gemacht werden.":
    "Delete project “{n}” with all captures, events and letters? This cannot be undone.",
  ...TERMS,
};

// Muster für zusammengesetzte Engine-Texte (Auswirkungsketten, Wetter, Blocker)
const EN_RULES: [RegExp, string][] = [
  [/um (\d+) AT überschritten/g, "exceeded by $1 WD"],
  [/Prognose überschreitet um (\d+) AT/g, "forecast exceeds by $1 WD"],
  [/^Böen bis (\d+) km\/h$/, "gusts up to $1 km/h"],
  [/^gefunden in: (.+)$/, "found in: $1"],
  [/^Keine gültige E-Mail-Adresse: (.+)$/, "Not a valid email address: $1"],
  [/\(statt ([^)]+)\)/g, "(instead of $1)"],
  // mehrwortige Projektbegriffe innerhalb von Sätzen (längste zuerst, damit „Vertragsfrist Rohbau EG“ vor „… EG“ greift)
  ...Object.entries(TERMS).filter(([k]) => k.includes(" ")).sort((a, b) => b[0].length - a[0].length)
    .map(([k, v]) => [new RegExp(reEscape(k), "g"), v] as [RegExp, string]),
  [/^Sprachmemo (\d\d:\d\d)/, "Voice memo $1"],
  [/^Foto (\d\d:\d\d)/, "Photo $1"],
  [/^Mail (\d\d:\d\d)/, "Email $1"],
  [/^Notiz (\d\d:\d\d)/, "Note $1"],
  [/^Dokument (\d\d:\d\d)/, "Document $1"],
  [/^Protokoll Baubesprechung Nr\. (\d+)/, "Site meeting minutes No. $1"],
  [/ – Bewehrung unvollständig/, " – reinforcement incomplete"],
  [/ · Bagger nach Reparatur/, " · excavator after repair"],
  [/(\d+) AT\b/g, "$1 WD"],
  [/\bAchse ([A-Z0-9]+)\b/g, "axis $1"],
  [/^Nicht belegt: (\w+) „(.+)“ \((\w+) Satz (\d+)\)$/, "Unsupported: $1 “$2” ($3 sentence $4)"],
  [/^Feld „(.+)“ unsicher – bitte übernehmen, bearbeiten oder verwerfen$/, "Field “$1” uncertain – please accept, edit or reject"],
  [/^Pflichtfeld „(.+)“ verworfen$/, "Required field “$1” rejected"],
  [/^Checkliste: (.+)$/, "Checklist: $1"],
  [/^LLM-Einschätzung \((\w+)\) weicht von Regel \((\w+)\) ab – bitte prüfen$/, "LLM assessment ($1) differs from rule ($2) – please check"],
  [/^manuell bestätigt: (.*)$/, "confirmed manually: $1"],
  [/^Beleg wird in Schreiben (\S+) \((\S+)\) verwendet – Löschen nicht zulässig \(Nachweis\)$/, "Evidence is used in notice $1 ($2) – deletion not allowed (proof)"],
  [/^Vorgänger (\S+) existiert nicht$/, "Predecessor $1 does not exist"],
  [/^Zyklus im Terminplan bei (\S+)$/, "Cycle in schedule at $1"],
  [/^Vorgang ist Vorgänger von (.+) – dort zuerst entfernen$/, "Activity is a predecessor of $1 – remove it there first"],
  [/^ID (\S+) existiert bereits$/, "ID $1 already exists"],
  [/Niederschlag ([\d.,]+) mm > ([\d.,]+) mm/, "Precipitation $1 mm > $2 mm"],
  [/Böen ([\d.,]+) km\/h > ([\d.,]+) km\/h/, "Gusts $1 km/h > $2 km/h"],
  [/Frost ([-\d.,]+) °C < ([-\d.,]+) °C/, "Frost $1 °C < $2 °C"],
];

type Ctx = { lang: Lang; setLang: (l: Lang) => void; t: (s: string, p?: Record<string, any>) => string };
const LangCtx = createContext<Ctx>({ lang: "de", setLang: () => {}, t: (s) => s });

let currentLang: Lang = "de";
export const locale = () => (currentLang === "en" ? "en-GB" : "de-DE");

function translate(lang: Lang, s: string, p?: Record<string, any>) {
  let out = s;
  if (lang === "en" && s) {
    if (EN[s] !== undefined) out = EN[s];
    else {
      for (const [rx, rep] of EN_RULES) out = out.replace(rx, rep);
      // Teilstücke der Checklisten-/Blocker-Texte ebenfalls nachschlagen
      out = out.replace(/(“|„)([^“”„]+)(”|“)/g, (m, a, inner, b) => (EN[inner] ? `“${EN[inner]}”` : m));
      const tail = out.match(/^(Checklist: )(.+)$/);
      if (tail && EN[tail[2]]) out = tail[1] + EN[tail[2]];
    }
  }
  if (p) for (const [k, v] of Object.entries(p)) out = out.split(`{${k}}`).join(String(v));
  return out;
}

export function LangProvider({ children }: { children: ReactNode }) {
  const [lang, setLangState] = useState<Lang>("de");
  useEffect(() => {
    try {
      const saved = localStorage.getItem("sitevox.lang");
      const initial = saved === "en" || saved === "de" ? saved : navigator.language.startsWith("de") ? "de" : "en";
      setLangState(initial as Lang);
    } catch {}
  }, []);
  currentLang = lang;
  useEffect(() => {
    document.documentElement.lang = lang;
  }, [lang]);
  const setLang = (l: Lang) => {
    setLangState(l);
    try { localStorage.setItem("sitevox.lang", l); } catch {}
  };
  return (
    <LangCtx.Provider value={{ lang, setLang, t: (s, p) => translate(lang, s, p) }}>
      {/* key erzwingt Neuaufbau, damit auch Datums-/Zahlenformate sofort wechseln */}
      <div key={lang} className="contents">{children}</div>
    </LangCtx.Provider>
  );
}

export const useT = () => useContext(LangCtx);

export function LangToggle({ dark = false }: { dark?: boolean }) {
  const { lang, setLang, t } = useT();
  return (
    <div className={`inline-flex overflow-hidden rounded-md border text-2xs font-semibold ${dark ? "border-slate-600" : "border-slate-300"}`} role="group" aria-label={t("Sprache")}>
      {(["de", "en"] as Lang[]).map((l) => (
        <button key={l} onClick={() => setLang(l)} aria-pressed={lang === l}
          className={`px-2 py-0.5 uppercase ${lang === l ? (dark ? "bg-white text-slate-900" : "bg-slate-900 text-white") : dark ? "text-slate-300" : "text-slate-600 hover:bg-slate-100"}`}>
          {l}
        </button>
      ))}
    </div>
  );
}
