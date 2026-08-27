import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import "katex/dist/katex.min.css";

const CODE_FENCE_RE = /```[\s\S]*?```/g;
const INLINE_CODE_RE = /`[^`\n]+`/g;
const SEP_CELL_RE = /^:?-{3,}:?$/;

/** True when a $...$ / $$...$$ body looks like real math, not swallowed prose. */
function looksLikeMath(expr: string): boolean {
  const cleaned = expr.trim();
  if (!cleaned) return false;

  // TeX commands or explicit math markup
  if (/\\[a-zA-Z]+/.test(cleaned)) return true;

  // Display-style operators / symbols
  if (/[=∑∫∏√∞≈≠≤≥±⋅×÷∈∉⊂⊃⊆⊇→←↔⇒⇐⇔∇∂]|\\{|\\}/.test(cleaned)) {
    // Reject if it is mostly English prose with an incidental equals sign
    const words = cleaned.match(/[A-Za-z]{3,}/g) ?? [];
    const proseWords = words.filter(
      (w) =>
        !/^(sin|cos|tan|log|ln|exp|min|max|sup|inf|lim|arg|det|dim|ker|mod|gcd|lcm|var|cov|mse|rmse|mae|theta|alpha|beta|gamma|delta|epsilon|sigma|mu|lambda|phi|psi|omega|mathbf|mathrm|text|frac|sum|prod|int|partial|infty|cdot|times|leq|geq|neq|approx|subset|in|to|of|or|and)$/i.test(
          w,
        ),
    );
    if (proseWords.length >= 6) return false;
    return true;
  }

  // Short identifier / simple expression: y, Xθ, n_i, (m, n)
  const spaceCount = (cleaned.match(/\s+/g) ?? []).length;
  if (cleaned.length <= 48 && spaceCount <= 2) return true;

  return false;
}

function escapeDollars(s: string): string {
  return s.replace(/\$/g, "\\$");
}

/**
 * Walk text and keep only $ / $$ spans that look like math.
 * Prose accidentally wrapped in $...$ (common LLM failure) is left as plain text.
 */
function sanitizeDollarMath(text: string): string {
  let out = "";
  let i = 0;

  while (i < text.length) {
    if (text[i] !== "$") {
      out += text[i];
      i += 1;
      continue;
    }

    // Escaped \$
    if (i > 0 && text[i - 1] === "\\") {
      out += "$";
      i += 1;
      continue;
    }

    const display = text.startsWith("$$", i);
    const delim = display ? "$$" : "$";
    const open = i;
    const close = text.indexOf(delim, open + delim.length);

    if (close === -1) {
      // Unmatched opener — do not start math mode for the rest of the message
      out += escapeDollars(text.slice(open));
      break;
    }

    const body = text.slice(open + delim.length, close);
    const span = text.slice(open, close + delim.length);

    // Inline $ must not span newlines (almost always accidental prose wrap)
    if (!display && body.includes("\n")) {
      out += escapeDollars(span);
    } else if (looksLikeMath(body)) {
      out += span;
    } else {
      out += escapeDollars(span);
    }

    i = close + delim.length;
  }

  return out;
}

/**
 * Expand pipe tables that LLMs sometimes emit as a single line, e.g.
 * `| A | B | | --- | --- | | c | d |` → proper multi-line GFM table.
 */
export function normalizeCollapsedPipeTables(raw: string): string {
  if (!raw.includes("|")) return raw;

  return raw
    .split("\n")
    .map((line) => {
      const trimmed = line.trim();
      if (!trimmed.startsWith("|") || !/\|\s*:?-{3,}:?\s*\|/.test(trimmed)) {
        return line;
      }
      if ((trimmed.match(/\|/g) ?? []).length < 8) return line;

      const parts = trimmed.split("|").map((c) => c.trim());
      if (parts[0] !== "") return line;
      const cells =
        parts[parts.length - 1] === "" ? parts.slice(1, -1) : parts.slice(1);

      const sepStart = cells.findIndex((c) => SEP_CELL_RE.test(c));
      if (sepStart <= 0) return line;

      const colCount = sepStart;
      const sepCells = cells.slice(sepStart, sepStart + colCount);
      if (sepCells.length < colCount || !sepCells.every((c) => SEP_CELL_RE.test(c))) {
        return line;
      }

      const rows: string[][] = [cells.slice(0, colCount), sepCells];
      let i = sepStart + colCount;
      while (i + colCount <= cells.length) {
        rows.push(cells.slice(i, i + colCount));
        i += colCount;
      }

      const indent = line.match(/^\s*/)?.[0] ?? "";
      const formatted = rows.map((row) => `${indent}| ${row.join(" | ")} |`);
      if (i < cells.length) {
        formatted.push(`${indent}| ${cells.slice(i).join(" | ")} |`);
      }
      return formatted.join("\n");
    })
    .join("\n");
}

/**
 * Convert common LLM math notations into remark-math delimiters ($ / $$)
 * so KaTeX can render them — and strip false-positive math spans.
 */
export function normalizeMathMarkdown(raw: string): string {
  if (!raw) return "";

  // Protect code so we do not rewrite $ or brackets inside it
  const protectedChunks: string[] = [];
  const protect = (match: string) => {
    const token = `\u0000CODE${protectedChunks.length}\u0000`;
    protectedChunks.push(match);
    return token;
  };

  let text = normalizeCollapsedPipeTables(raw)
    .replace(CODE_FENCE_RE, protect)
    .replace(INLINE_CODE_RE, protect);

  // \[ ... \]  →  $$ ... $$
  text = text.replace(/\\\[([\s\S]*?)\\\]/g, (_m, expr: string) => {
    const cleaned = String(expr).trim();
    return looksLikeMath(cleaned) ? `\n\n$$\n${cleaned}\n$$\n\n` : cleaned;
  });

  // \( ... \)  →  $ ... $
  text = text.replace(/\\\(([\s\S]*?)\\\)/g, (_m, expr: string) => {
    const cleaned = String(expr).trim();
    return looksLikeMath(cleaned) ? `$${cleaned}$` : cleaned;
  });

  // [ y = X\theta + \varepsilon ]  (LLM often wraps TeX in square brackets)
  // Only rewrite when the bracket body contains TeX commands — avoid markdown links.
  text = text.replace(
    /\[\s*([^\[\]]*\\[a-zA-Z{}_^][^\[\]]*)\s*\]/g,
    (_m, expr: string) => {
      const cleaned = String(expr).replace(/,\s*$/, "").trim();
      if (!looksLikeMath(cleaned)) return `[${cleaned}]`;
      const isDisplay =
        cleaned.length > 24 ||
        /[=∑∫∏]/.test(cleaned) ||
        /\\(?:frac|sum|prod|int|theta|mathbf|mathrm|text|top|partial)/.test(cleaned);
      return isDisplay ? `\n\n$$\n${cleaned}\n$$\n\n` : `$${cleaned}$`;
    },
  );

  text = sanitizeDollarMath(text);

  // Collapse excessive blank lines created by replacements
  text = text.replace(/\n{3,}/g, "\n\n");

  // Restore code
  text = text.replace(/\u0000CODE(\d+)\u0000/g, (_m, idx: string) => {
    return protectedChunks[Number(idx)] ?? "";
  });

  return text;
}

type MarkdownMessageProps = {
  content: string;
  className?: string;
};

/** Renders assistant chat content with Markdown + KaTeX math. */
export default function MarkdownMessage({ content, className }: MarkdownMessageProps) {
  const source = normalizeMathMarkdown(content);

  return (
    <div className={className ? `chat-md ${className}` : "chat-md"}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm, remarkMath]}
        rehypePlugins={[[rehypeKatex, { strict: "ignore", errorColor: "inherit" }]]}
        components={{
          a: ({ href, children }) => (
            <a href={href} target="_blank" rel="noopener noreferrer">
              {children}
            </a>
          ),
          table: ({ children }) => (
            <div className="chat-md-table-wrap">
              <table>{children}</table>
            </div>
          ),
        }}
      >
        {source}
      </ReactMarkdown>
    </div>
  );
}
