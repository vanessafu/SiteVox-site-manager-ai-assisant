# knowledge/ – Quellenübersicht

## Automatisch geladen (21.11.2026)

| Ordner/Datei | Inhalt | Quelle | Nutzung |
|---|---|---|---|
| `laws/bgb_bauvertrag.md` | BGB §§ 631–650v (Werk-/Bauvertrag), §§ 126–127, 130 (Form, Zugang), §§ 305, 307, 310 (AGB/VOB-Privileg), § 242 – zusammengefasst | Spiegel von gesetze-im-internet.de (github.com/xerj-org/corpus-de-gesetze), XML-Stand 2026-09-26 | RAG, Gesetzeszitate. Amtlicher Text, § 5 UrhG |
| `laws/bgb_norms/` | dieselben 56 Normen, eine Datei pro Paragraph | wie oben | Chunking pro Norm |
| `terminology/uniclass2015/` | Uniclass 2015, alle Tabellen als CSV (englische Begriffe) | github.com/buildig/uniclass-2015 (Stand 2022-01), Original NBS | Englischer Term-Seed für Whisper-Hotwords / Nachkorrektur |
| `bgb.md`, `vob_b.md` | bestehender Demo-Korpus | (vorhanden, unverändert) | |

## Von Hand herunterladen (Seiten waren aus der Sandbox nicht erreichbar)

| Datei | Link | Ablegen unter |
|---|---|---|
| VHB-Bund 2017, Lesefassung 2023 (Vertragsbedingungen, Formblätter, Richtlinie 411 Bautagebuch) | https://fib-bund.de/Inhalt/Vergabe/VHB/VHB_2017_Lesefassung_2023.pdf | `contracts/` |
| IATE-Export (de/en/pl, Domäne Bauwesen; Registrierung nötig, kein Türkisch) | https://iate.europa.eu/download-iate | `terminology/iate/` |
| VOB/B 2016 (DIN 1961:2016-09, kostenpflichtig, auch englisch) | https://www.dinmedia.de/de/norm/din-1961/256403134 | `laws/` – nur intern nutzen |
| BIM-Portal des Bundes (Merkmale, deutsche Begriffe) | https://www.bimdeutschland.de | `terminology/bim_portal/` |
| BGB amtlich (Abgleich) | https://www.gesetze-im-internet.de/bgb/ | – |
