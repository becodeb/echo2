import { useMemo } from "react";

// ── Markdown renderer minimalista (sin dependencias) ─────────────

export function MarkdownView({ markdown }: { markdown: string }) {
  const html = useMemo(() => renderMarkdown(markdown), [markdown]);
  return (
    <div
      className="prose-echo max-w-none text-[15px] leading-relaxed text-ink-800 [&_h1]:mb-3 [&_h1]:text-xl [&_h1]:font-semibold [&_h2]:mb-2 [&_h2]:mt-5 [&_h2]:text-lg [&_h2]:font-semibold [&_h3]:mt-4 [&_h3]:font-semibold [&_li]:my-0.5 [&_p]:my-2 [&_table]:my-3 [&_table]:w-full [&_table]:border-collapse [&_td]:border [&_td]:border-ink-200 [&_td]:px-2.5 [&_td]:py-1.5 [&_th]:border [&_th]:border-ink-200 [&_th]:bg-ink-50 [&_th]:px-2.5 [&_th]:py-1.5 [&_th]:text-left [&_ul]:my-2 [&_ul]:list-disc [&_ul]:pl-5 [&_blockquote]:border-l-2 [&_blockquote]:border-ink-200 [&_blockquote]:pl-3 [&_blockquote]:text-ink-500 [&_hr]:my-4 [&_hr]:border-ink-100"
      dangerouslySetInnerHTML={{ __html: html }}
    />
  );
}

function escapeHtml(text: string): string {
  return text
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function inline(text: string): string {
  return escapeHtml(text)
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/(^|\s)_(.+?)_(?=\s|$)/g, "$1<em>$2</em>")
    .replace(/`(.+?)`/g, "<code>$1</code>");
}

function renderMarkdown(markdown: string): string {
  const lines = markdown.split("\n");
  const output: string[] = [];
  let inList = false;
  let inQuote = false;
  let tableRows: string[][] = [];

  const closeList = () => {
    if (inList) {
      output.push("</ul>");
      inList = false;
    }
  };
  const closeQuote = () => {
    if (inQuote) {
      output.push("</blockquote>");
      inQuote = false;
    }
  };
  const flushTable = () => {
    if (tableRows.length > 0) {
      const [head, ...body] = tableRows;
      output.push("<table><thead><tr>");
      head.forEach((cell) => output.push(`<th>${inline(cell)}</th>`));
      output.push("</tr></thead><tbody>");
      body.forEach((row) => {
        output.push("<tr>");
        row.forEach((cell) => output.push(`<td>${inline(cell)}</td>`));
        output.push("</tr>");
      });
      output.push("</tbody></table>");
      tableRows = [];
    }
  };

  for (const raw of lines) {
    const line = raw.trimEnd();
    if (line.startsWith("|") && line.endsWith("|")) {
      const cells = line.slice(1, -1).split("|").map((cell) => cell.trim());
      if (cells.every((cell) => /^[-: ]+$/.test(cell) && cell.length > 0)) continue;
      closeList();
      closeQuote();
      tableRows.push(cells);
      continue;
    }
    flushTable();

    if (line.startsWith("### ")) {
      closeList(); closeQuote();
      output.push(`<h3>${inline(line.slice(4))}</h3>`);
    } else if (line.startsWith("## ")) {
      closeList(); closeQuote();
      output.push(`<h2>${inline(line.slice(3))}</h2>`);
    } else if (line.startsWith("# ")) {
      closeList(); closeQuote();
      output.push(`<h1>${inline(line.slice(2))}</h1>`);
    } else if (line.startsWith("- ") || line.startsWith("* ")) {
      closeQuote();
      if (!inList) {
        output.push("<ul>");
        inList = true;
      }
      output.push(`<li>${inline(line.slice(2))}</li>`);
    } else if (line.startsWith("> ")) {
      closeList();
      if (!inQuote) {
        output.push("<blockquote>");
        inQuote = true;
      }
      output.push(`<p>${inline(line.slice(2))}</p>`);
    } else if (line === "---" || line === "***") {
      closeList(); closeQuote();
      output.push("<hr />");
    } else if (line.trim() === "") {
      closeList();
      closeQuote();
    } else {
      closeList(); closeQuote();
      output.push(`<p>${inline(line)}</p>`);
    }
  }
  closeList();
  closeQuote();
  flushTable();
  return output.join("\n");
}
