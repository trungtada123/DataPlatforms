import type { ReactNode } from "react";

function renderInline(text: string): ReactNode[] {
  const parts = text.split(/(\*\*[^*]+\*\*)/g);
  return parts.map((part, index) => {
    const bold = part.match(/^\*\*([^*]+)\*\*$/);
    if (bold) {
      return <strong key={index}>{bold[1]}</strong>;
    }
    return part;
  });
}

export function MarkdownLite({ text }: { text: string }) {
  const lines = text.replace(/\r\n/g, "\n").split("\n");
  const nodes: ReactNode[] = [];
  let listItems: string[] = [];
  let key = 0;

  const flushList = () => {
    if (!listItems.length) return;
    nodes.push(
      <ul className="md-list" key={`list-${key++}`}>
        {listItems.map((item, index) => (
          <li key={index}>{renderInline(item)}</li>
        ))}
      </ul>,
    );
    listItems = [];
  };

  for (const rawLine of lines) {
    const line = rawLine.trimEnd();
    const trimmed = line.trim();

    if (!trimmed) {
      flushList();
      continue;
    }

    if (trimmed.startsWith("## ")) {
      flushList();
      nodes.push(
        <h3 className="md-h2" key={`h2-${key++}`}>
          {trimmed.slice(3).trim()}
        </h3>,
      );
      continue;
    }

    if (trimmed.startsWith("### ")) {
      flushList();
      nodes.push(
        <h4 className="md-h3" key={`h3-${key++}`}>
          {trimmed.slice(4).trim()}
        </h4>,
      );
      continue;
    }

    if (trimmed.startsWith("- ")) {
      listItems.push(trimmed.slice(2).trim());
      continue;
    }

    flushList();
    nodes.push(
      <p className="md-p" key={`p-${key++}`}>
        {renderInline(trimmed)}
      </p>,
    );
  }

  flushList();

  if (!nodes.length) {
    return <p className="md-p">{text}</p>;
  }

  return <div className="answer-markdown">{nodes}</div>;
}
