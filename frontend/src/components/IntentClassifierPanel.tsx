import { buildIntentClassifierView } from "../intentPlanDisplay";
import type { IntentPlan } from "../types";

type IntentClassifierPanelProps = {
  plan?: IntentPlan;
};

export function IntentClassifierPanel({ plan }: IntentClassifierPanelProps) {
  if (!plan || Object.keys(plan).length === 0) {
    return null;
  }

  const view = buildIntentClassifierView(plan);

  return (
    <section className="intent-classifier-panel" aria-label="Từ khóa intent classifier">
      <div className="intent-classifier-head">
        <h3 className="section-label intent-classifier-title">Intent classifier</h3>
        <div className="intent-classifier-badges">
          <span className="intent-chip intent-chip-primary">{view.primaryIntent}</span>
          {view.tools.map((tool) => (
            <span key={tool.key} className="intent-chip intent-chip-tool">
              {tool.label}
            </span>
          ))}
          <span className="intent-chip intent-chip-meta" title="Chế độ phân loại">
            {view.classifierMode}
          </span>
        </div>
      </div>

      <p className="intent-normalized">
        <span className="intent-kw-label">Truy vấn chuẩn hóa</span>
        <span className="intent-kw-value">{view.normalizedQuery}</span>
      </p>

      {view.toolQueryItems.length > 0 ? (
        <div className="intent-kw-block">
          <span className="intent-kw-label">Keyword / truy vấn nhánh</span>
          <ul className="intent-tool-query-list">
            {view.toolQueryItems.map((item) => (
              <li key={item.key} className="intent-tool-query-row">
                <span className="intent-chip intent-chip-tool">{item.label}</span>
                <span className="intent-tool-query-text">{item.value}</span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {view.groups.map((group) =>
        group.id === "tool_queries" ? null : (
          <div key={group.id} className="intent-kw-block">
            <span className="intent-kw-label">{group.title}</span>
            <dl className="intent-kw-dl">
              {group.items.map((item) => (
                <div key={item.key} className="intent-kw-row">
                  <dt>{item.label}</dt>
                  <dd>{item.value}</dd>
                </div>
              ))}
            </dl>
          </div>
        ),
      )}

      {view.analysisTags.length > 0 ? (
        <div className="intent-kw-block">
          <span className="intent-kw-label">Yêu cầu phân tích</span>
          <div className="intent-tag-row">
            {view.analysisTags.map((tag) => (
              <span key={tag.key} className="intent-chip intent-chip-analysis">
                {tag.label}
              </span>
            ))}
          </div>
        </div>
      ) : null}

      {view.reasoningBrief ? (
        <p className="intent-reasoning">
          <span className="intent-kw-label">Lý do</span>
          {view.reasoningBrief}
        </p>
      ) : null}
    </section>
  );
}
