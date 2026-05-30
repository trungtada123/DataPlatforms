import { buildCompletedPipeline, hasPipelineTrace } from "../pipeline";
import { normalizeLimitations } from "../textUtils";
import type { QueryResponse } from "../types";
import { extractSqlSnippets } from "../types";
import { AnswerBlock } from "./AnswerBlock";
import { DebugPanel } from "./DebugPanel";
import { IntentClassifierPanel } from "./IntentClassifierPanel";
import { MetaGrid } from "./MetaGrid";
import { PipelineProgress } from "./PipelineProgress";
import { SqlBlock } from "./SqlBlock";

type ResultPanelProps = {
  data: QueryResponse;
};

export function ResultPanel({ data }: ResultPanelProps) {
  const sqlSnippets = extractSqlSnippets(data);

  const pipelineSteps = hasPipelineTrace(data) ? buildCompletedPipeline(data) : [];
  const limitations = normalizeLimitations(data.limitations ?? []);

  return (
    <section className="card result-card">
      {pipelineSteps.length > 0 ? (
        <PipelineProgress
          mode="completed"
          steps={pipelineSteps}
          hint={
            data.tools_used?.length
              ? `Công cụ đã dùng: ${data.tools_used.join(", ")}`
              : undefined
          }
        />
      ) : null}

      <AnswerBlock answer={data.answer ?? ""} />

      <MetaGrid traceId={data.trace_id} status={data.status} toolsUsed={data.tools_used} />

      <IntentClassifierPanel plan={data.intent_plan} />

      <SqlBlock snippets={sqlSnippets} />

      {limitations.length > 0 ? (
        <section className="limitations">
          <h3 className="section-label limitations-label">
            <span className="limitations-icon" aria-hidden="true">
              ⚠
            </span>{" "}
            Lưu ý
          </h3>
          <ul className="limitations-list">
            {limitations.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </section>
      ) : null}

      <DebugPanel
        intentPlan={data.intent_plan}
        debugTrace={data.debug_trace}
        results={data.results}
        rawResponse={data}
      />
    </section>
  );
}
