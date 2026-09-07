import Link from "next/link";
import type { ReactNode } from "react";

function renderInline(value: string): ReactNode[] {
  const nodes: ReactNode[] = [];
  const pattern = /(\[([^\]]+)\]\((\/jobs\/[^)\s]+)\)|\*\*([^*]+)\*\*|`([^`]+)`)/g;
  let cursor = 0;
  let match: RegExpExecArray | null;
  let key = 0;

  while ((match = pattern.exec(value)) !== null) {
    if (match.index > cursor) nodes.push(value.slice(cursor, match.index));
    if (match[2] && match[3]) {
      nodes.push(
        <Link
          className="font-medium text-indigo-600 underline decoration-indigo-200 underline-offset-2 hover:text-indigo-700 dark:text-indigo-400 dark:decoration-indigo-700 dark:hover:text-indigo-300"
          href={match[3]}
          key={`link-${key}`}
        >
          {match[2]}
        </Link>,
      );
    } else if (match[4]) {
      nodes.push(<strong key={`strong-${key}`}>{match[4]}</strong>);
    } else if (match[5]) {
      nodes.push(
        <code className="rounded bg-slate-100 px-1.5 py-0.5 text-[0.9em] text-indigo-700 dark:bg-slate-800 dark:text-indigo-300" key={`code-${key}`}>
          {match[5]}
        </code>,
      );
    }
    cursor = match.index + match[0].length;
    key += 1;
  }
  if (cursor < value.length) nodes.push(value.slice(cursor));
  return nodes;
}

type ListItem = {
  content: string;
  children: ReactNode[];
};

type ListMatch = {
  indent: number;
  ordered: boolean;
  number: number;
  content: string;
};

function matchListItem(line: string): ListMatch | null {
  const match = line.match(/^(\s*)([-*+]|(\d+)[.)])\s+(.+)$/);
  if (!match) return null;
  return {
    indent: match[1].length,
    ordered: Boolean(match[3]),
    number: match[3] ? Number(match[3]) : 1,
    content: match[4],
  };
}

function renderList(
  lines: string[],
  start: number,
  baseIndent: number,
  keyPrefix: string,
): { node: ReactNode; end: number } {
  const first = matchListItem(lines[start]);
  if (!first) return { node: null, end: start };
  const items: ListItem[] = [];
  let index = start;
  while (index < lines.length) {
    const current = matchListItem(lines[index]);
    if (!current || current.indent < baseIndent) break;
    if (current.indent > baseIndent) {
      if (items.length) {
        const nested = renderList(lines, index, current.indent, `${keyPrefix}-nested-${items.length}`);
        items[items.length - 1].children.push(nested.node);
        index = nested.end;
        continue;
      }
      index += 1;
      continue;
    }
    if (current.ordered !== first.ordered) break;
    items.push({ content: current.content, children: [] });
    index += 1;
  }
  const List = first.ordered ? "ol" : "ul";
  const listClass = first.ordered ? "list-decimal" : "list-disc";
  const node = (
    <List
      className={`my-2 space-y-1.5 pl-5 ${listClass}`}
      key={keyPrefix}
      start={first.ordered ? first.number : undefined}
    >
      {items.map((item, itemIndex) => (
        <li key={`${keyPrefix}-${itemIndex}`}>
          {renderInline(item.content)}
          {item.children}
        </li>
      ))}
    </List>
  );
  return { node, end: index };
}

function tableCells(line: string): string[] {
  const value = line.trim().replace(/^\|/, "").replace(/\|$/, "");
  return value.split("|").map((cell) => cell.trim());
}

function isTableDivider(line: string): boolean {
  const cells = tableCells(line);
  return cells.length > 0 && cells.every((cell) => /^:?-{3,}:?$/.test(cell));
}

function renderTable(lines: string[], start: number): { node: ReactNode; end: number } | null {
  if (!lines[start]?.includes("|") || !isTableDivider(lines[start + 1] ?? "")) return null;
  const headers = tableCells(lines[start]);
  const rows: string[][] = [];
  let index = start + 2;
  while (index < lines.length && lines[index].trim().includes("|")) {
    rows.push(tableCells(lines[index]));
    index += 1;
  }
  const node = (
    <div className="my-3 overflow-x-auto rounded-xl border border-slate-200 dark:border-slate-700" key={`table-${start}`}>
      <table className="min-w-full divide-y divide-slate-200 text-left text-sm dark:divide-slate-700">
        <thead className="bg-slate-50 dark:bg-slate-800/80">
          <tr>{headers.map((header, cellIndex) => <th className="whitespace-nowrap px-3 py-2 font-semibold text-slate-800 dark:text-slate-200" key={`head-${cellIndex}`}>{renderInline(header)}</th>)}</tr>
        </thead>
        <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
          {rows.map((row, rowIndex) => <tr key={`row-${rowIndex}`}>{headers.map((_, cellIndex) => <td className="px-3 py-2 align-top text-slate-600 dark:text-slate-300" key={`cell-${rowIndex}-${cellIndex}`}>{renderInline(row[cellIndex] ?? "")}</td>)}</tr>)}
        </tbody>
      </table>
    </div>
  );
  return { node, end: index };
}

export function MarkdownContent({ value, className = "" }: { value: string; className?: string }) {
  const lines = value.split(/\r?\n/);
  const blocks: ReactNode[] = [];
  let index = 0;

  while (index < lines.length) {
    const line = lines[index];
    const trimmed = line.trim();
    if (trimmed.startsWith("```")) {
      const language = trimmed.slice(3).trim();
      const codeLines: string[] = [];
      index += 1;
      while (index < lines.length && !lines[index].trim().startsWith("```")) {
        codeLines.push(lines[index]);
        index += 1;
      }
      if (index < lines.length) index += 1;
      blocks.push(
        <pre className="my-3 overflow-x-auto rounded-xl bg-slate-900 p-4 text-xs leading-6 text-slate-100" key={`code-block-${index}`}>
          <code data-language={language || undefined}>{codeLines.join("\n")}</code>
        </pre>,
      );
      continue;
    }

    const table = renderTable(lines, index);
    if (table) {
      blocks.push(table.node);
      index = table.end;
      continue;
    }

    const list = matchListItem(line);
    if (list) {
      const rendered = renderList(lines, index, list.indent, `list-${index}`);
      blocks.push(rendered.node);
      index = rendered.end;
      continue;
    }

    if (!trimmed) {
      blocks.push(<div className="h-2" key={`space-${index}`} />);
      index += 1;
      continue;
    }
    const heading = trimmed.match(/^(#{1,6})\s+(.+)$/);
    if (heading) {
      const level = heading[1].length;
      const size = level === 1 ? "text-xl" : level === 2 ? "text-lg" : "text-base";
      const props = {
        className: `${size} mt-4 font-semibold text-slate-900 first:mt-0 dark:text-slate-100`,
      };
      const content = renderInline(heading[2]);
      blocks.push(
        level === 1 ? <h2 key={`heading-${index}`} {...props}>{content}</h2>
          : level === 2 ? <h3 key={`heading-${index}`} {...props}>{content}</h3>
            : level === 3 ? <h4 key={`heading-${index}`} {...props}>{content}</h4>
              : level === 4 ? <h5 key={`heading-${index}`} {...props}>{content}</h5>
                : <h6 key={`heading-${index}`} {...props}>{content}</h6>,
      );
      index += 1;
      continue;
    }
    if (trimmed.startsWith("> ")) {
      blocks.push(<blockquote className="border-l-2 border-indigo-300 pl-3 italic text-slate-500 dark:border-indigo-600 dark:text-slate-400" key={`quote-${index}`}>{renderInline(trimmed.slice(2))}</blockquote>);
      index += 1;
      continue;
    }
    blocks.push(<p className="leading-7" key={`paragraph-${index}`}>{renderInline(trimmed)}</p>);
    index += 1;
  }

  return <div className={`text-sm text-slate-700 dark:text-slate-300 ${className}`}>{blocks}</div>;
}
