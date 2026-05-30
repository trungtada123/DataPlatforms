import { formatStatusLabel, statusTone } from "../types";

type MetaGridProps = {
  traceId?: string;
  status?: string;
  toolsUsed?: string[];
};

export function MetaGrid({ traceId, status, toolsUsed }: MetaGridProps) {
  const tone = statusTone(status);
  const toolsLabel =
    toolsUsed && toolsUsed.length > 0 ? toolsUsed.join(", ") : "Không có";

  return (
    <div className="meta-grid">
      <div className="meta-cell">
        <span className="meta-label">Mã theo dõi</span>
        <strong className="meta-value meta-value-truncate" title={traceId ?? ""}>
          {traceId ?? "—"}
        </strong>
      </div>
      <div className="meta-cell">
        <span className="meta-label">Trạng thái</span>
        <span className={`meta-status meta-status-${tone}`}>{formatStatusLabel(status)}</span>
      </div>
      <div className="meta-cell">
        <span className="meta-label">Công cụ</span>
        <strong className="meta-value">{toolsLabel}</strong>
      </div>
    </div>
  );
}
