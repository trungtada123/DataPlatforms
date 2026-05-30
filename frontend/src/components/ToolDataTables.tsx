import type { ToolDataTable } from "../evidenceTables";

type ToolDataTablesProps = {
  tables: ToolDataTable[];
};

export function ToolDataTables({ tables }: ToolDataTablesProps) {
  if (!tables.length) {
    return null;
  }

  const grouped = groupByTool(tables);

  return (
    <section className="data-tables-section">
      <h3 className="section-label">Bảng dữ liệu theo nhánh công cụ</h3>
      <p className="muted data-tables-hint">
        Dùng cho báo cáo: market (kết quả SQL), tin tức đã crawl, và retrieval BCTC.
      </p>
      <div className="data-tables-list">
        {grouped.map((group) => (
          <div key={group.toolName} className="data-tables-tool-group">
            <p className="data-tables-tool-label">{group.toolLabel}</p>
            {group.tables.map((table) => (
              <DataTableCard key={table.id} table={table} />
            ))}
          </div>
        ))}
      </div>
    </section>
  );
}

function groupByTool(tables: ToolDataTable[]): Array<{ toolName: string; toolLabel: string; tables: ToolDataTable[] }> {
  const map = new Map<string, { toolName: string; toolLabel: string; tables: ToolDataTable[] }>();
  for (const table of tables) {
    const existing = map.get(table.toolName);
    if (existing) {
      existing.tables.push(table);
      continue;
    }
    map.set(table.toolName, {
      toolName: table.toolName,
      toolLabel: table.toolLabel,
      tables: [table],
    });
  }
  return [...map.values()];
}

function DataTableCard({ table }: { table: ToolDataTable }) {
  return (
    <article className="data-table-card">
      <header className="data-table-card-header">
        <h4 className="data-table-title">{table.title}</h4>
        {table.hint ? <p className="data-table-hint">{table.hint}</p> : null}
      </header>
      <div className="data-table-scroll">
        <table className="data-table">
          <thead>
            <tr>
              {table.columns.map((column) => (
                <th key={column.key}>{column.label}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {table.rows.map((row, rowIndex) => (
              <tr key={`${table.id}-row-${rowIndex}`}>
                {table.columns.map((column) => (
                  <td key={column.key}>
                    <CellValue value={row[column.key]} kind={column.kind} />
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </article>
  );
}

function CellValue({ value, kind }: { value: unknown; kind?: "text" | "link" }) {
  if (value === null || value === undefined || value === "") {
    return <span className="muted">—</span>;
  }

  const text = String(value).trim();
  if (kind === "link" && /^https?:\/\//i.test(text)) {
    return (
      <a href={text} target="_blank" rel="noreferrer" className="data-table-link">
        {truncateLink(text)}
      </a>
    );
  }

  return <span>{text}</span>;
}

function truncateLink(url: string): string {
  if (url.length <= 56) return url;
  return `${url.slice(0, 40)}…${url.slice(-12)}`;
}
