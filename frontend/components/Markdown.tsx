/**
 * Schlanker Markdown-Renderer für Dokumente der Wissensbasis (ohne Zusatzpaket).
 * Unterstützt: Überschriften, Absätze, Listen (auch nummeriert, eingerückt), Tabellen (| … | und
 * tabulatorgetrennte Zeilen aus PDF/Excel), Zitate, Code-Blöcke, Trennlinien, **fett**, *kursiv*, `Code`,
 * sowie typische Gliederungen deutscher Verträge („§ 3 …“, „1.2 …“) als Überschriften.
 */
import { Fragment, ReactNode } from "react";

function inline(text: string, key = 0): ReactNode[] {
  const out: ReactNode[] = [];
  const re = /(\*\*[^*]+\*\*|__[^_]+__|`[^`]+`|\*[^*\s][^*]*\*|\[[^\]]+\]\([^)]+\))/g;
  let last = 0;
  let m: RegExpExecArray | null;
  let k = key;
  while ((m = re.exec(text))) {
    if (m.index > last) out.push(<Fragment key={k++}>{text.slice(last, m.index)}</Fragment>);
    const tok = m[0];
    if (tok.startsWith("**") || tok.startsWith("__")) out.push(<strong key={k++}>{tok.slice(2, -2)}</strong>);
    else if (tok.startsWith("`")) out.push(<code key={k++} className="rounded bg-slate-100 px-1 font-mono text-[0.85em]">{tok.slice(1, -1)}</code>);
    else if (tok.startsWith("[")) {
      const [, label, href] = tok.match(/\[([^\]]+)\]\(([^)]+)\)/)!;
      out.push(<a key={k++} href={href} target="_blank" rel="noreferrer" className="text-accent-text underline">{label}</a>);
    } else out.push(<em key={k++}>{tok.slice(1, -1)}</em>);
    last = m.index + tok.length;
  }
  if (last < text.length) out.push(<Fragment key={k++}>{text.slice(last)}</Fragment>);
  return out;
}

const cells = (line: string) =>
  line.includes("\t") ? line.split("\t").map((c) => c.trim()) : line.trim().replace(/^\||\|$/g, "").split("|").map((c) => c.trim());
const isSep = (line: string) => /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/.test(line);
const isPipeRow = (line: string) => /^\s*\|.*\|\s*$/.test(line);
const isTabRow = (line: string) => line.includes("\t") && line.trim().length > 0;
const LIST = /^(\s*)([-*•–]|\d+[.)])\s+(.*)$/;

function Table({ rows, head }: { rows: string[][]; head: boolean }) {
  const n = Math.max(...rows.map((r) => r.length));
  const body = head ? rows.slice(1) : rows;
  const num = (c: string) => /^[-+]?[\d.,\s]+(%|€|EUR|m²|m³|m|t|St|h)?$/.test(c) && /\d/.test(c);
  return (
    <div className="my-2 overflow-x-auto">
      <table className="w-full border-collapse text-sm">
        {head && (
          <thead><tr>{Array.from({ length: n }, (_, i) => (
            <th key={i} className="border-b-2 border-slate-300 bg-slate-50 px-2 py-1 text-left font-semibold">{inline(rows[0][i] || "")}</th>
          ))}</tr></thead>
        )}
        <tbody>{body.map((r, j) => (
          <tr key={j} className="border-b border-slate-100">{Array.from({ length: n }, (_, i) => (
            <td key={i} className={`px-2 py-1 align-top ${num(r[i] || "") ? "text-right tabular-nums" : ""}`}>{inline(r[i] || "")}</td>
          ))}</tr>
        ))}</tbody>
      </table>
    </div>
  );
}

export default function Markdown({ text }: { text: string }) {
  const lines = text.replace(/\r\n?/g, "\n").split("\n");
  const blocks: ReactNode[] = [];
  let i = 0;
  let k = 0;
  while (i < lines.length) {
    const line = lines[i];
    const tr = line.trim();
    if (!tr) { i++; continue; }

    if (tr.startsWith("```")) {
      const buf: string[] = [];
      i++;
      while (i < lines.length && !lines[i].trim().startsWith("```")) buf.push(lines[i++]);
      i++;
      blocks.push(<pre key={k++} className="my-2 overflow-x-auto rounded bg-slate-100 p-3 font-mono text-xs">{buf.join("\n")}</pre>);
      continue;
    }
    const h = tr.match(/^(#{1,6})\s+(.*)$/);
    if (h) {
      const lvl = h[1].length;
      const cls = ["text-lg font-semibold mt-4", "text-base font-semibold mt-4", "text-[15px] font-semibold mt-3", "text-sm font-semibold mt-3", "text-sm font-medium mt-2", "text-sm font-medium mt-2"][lvl - 1];
      blocks.push(<div key={k++} role="heading" aria-level={lvl} className={`${cls} mb-1 first:mt-0`}>{inline(h[2].replace(/#+\s*$/, ""))}</div>);
      i++;
      continue;
    }
    // Paragraphen-Überschrift im Vertrag: „§ 6 Behinderung …“ (kurze Zeile)
    if (/^§\s*\d+[a-z]?\b/.test(tr) && tr.length < 90 && !/[.;:]$/.test(tr)) {
      blocks.push(<div key={k++} className="mb-1 mt-4 text-[15px] font-semibold first:mt-0">{inline(tr)}</div>);
      i++;
      continue;
    }
    if (/^([-*_])\1{2,}$/.test(tr.replace(/\s/g, ""))) { blocks.push(<hr key={k++} className="my-3 border-slate-200" />); i++; continue; }

    // Tabelle: | a | b | (+ Trennzeile) oder ≥ 2 tabulatorgetrennte Zeilen
    if (isPipeRow(line) || (isTabRow(line) && i + 1 < lines.length && isTabRow(lines[i + 1]))) {
      const pipe = isPipeRow(line);
      const rows: string[][] = [];
      let head = false;
      while (i < lines.length && (pipe ? isPipeRow(lines[i]) || isSep(lines[i]) : isTabRow(lines[i]))) {
        if (pipe && isSep(lines[i])) { head = rows.length === 1; i++; continue; }
        rows.push(cells(lines[i]));
        i++;
      }
      if (!pipe) head = rows.length > 1 && rows[0].every((c) => c && !/\d/.test(c));
      blocks.push(<Table key={k++} rows={rows} head={head} />);
      continue;
    }
    if (tr.startsWith(">")) {
      const buf: string[] = [];
      while (i < lines.length && lines[i].trim().startsWith(">")) buf.push(lines[i++].trim().replace(/^>\s?/, ""));
      blocks.push(<blockquote key={k++} className="my-2 border-l-4 border-slate-300 pl-3 text-slate-700">{inline(buf.join(" "))}</blockquote>);
      continue;
    }
    if (LIST.test(line)) {
      const items: { depth: number; ordered: boolean; marker: string; text: string }[] = [];
      while (i < lines.length && (LIST.test(lines[i]) || (lines[i].startsWith("  ") && lines[i].trim() && items.length))) {
        const m = lines[i].match(LIST);
        if (m) items.push({ depth: Math.floor(m[1].replace(/\t/g, "  ").length / 2), ordered: /\d/.test(m[2]), marker: m[2], text: m[3] });
        else items[items.length - 1].text += " " + lines[i].trim();
        i++;
      }
      blocks.push(
        <ul key={k++} className="my-2 space-y-0.5">
          {items.map((it, j) => (
            <li key={j} className="flex gap-2" style={{ paddingLeft: `${it.depth * 1.25}rem` }}>
              <span className="w-5 shrink-0 text-right text-slate-500">{it.ordered ? it.marker : "•"}</span>
              <span className="min-w-0 flex-1">{inline(it.text)}</span>
            </li>
          ))}
        </ul>,
      );
      continue;
    }
    // Absatz: Folgezeilen bis Leerzeile / neuer Block (Zeilenumbrüche bleiben erhalten)
    const buf: string[] = [line];
    i++;
    while (i < lines.length && lines[i].trim() && !/^(#{1,6}\s|```|>|§\s*\d)/.test(lines[i].trim()) && !LIST.test(lines[i])
      && !isPipeRow(lines[i]) && !(isTabRow(lines[i]) && i + 1 < lines.length && isTabRow(lines[i + 1]))) buf.push(lines[i++]);
    blocks.push(
      <p key={k++} className="my-2 leading-relaxed">
        {buf.map((b, j) => <Fragment key={j}>{j > 0 && <br />}{inline(b.trim())}</Fragment>)}
      </p>,
    );
  }
  return <div className="text-sm text-slate-800">{blocks}</div>;
}
