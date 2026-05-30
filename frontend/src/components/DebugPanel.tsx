import type { DebugTrace, IntentPlan, ToolExecutionResult } from "../types";

type DebugPanelProps = {
  intentPlan?: IntentPlan;
  debugTrace?: DebugTrace | null;
  results?: ToolExecutionResult[];
  rawResponse: unknown;
};

export function DebugPanel({ intentPlan, debugTrace, results, rawResponse }: DebugPanelProps) {
  const hasIntent = Boolean(intentPlan && Object.keys(intentPlan).length > 0);
  const hasDebug = Boolean(debugTrace || (results && results.length > 0));

  return (
    <div className="debug-panel">
      {hasIntent ? <IntentPlanSection plan={intentPlan!} /> : null}

      {hasDebug ? (
        <details className="debug-details">
          <summary className="debug-summary">Chi tiết kỹ thuật</summary>
          <pre className="code-block">{JSON.stringify({ debug_trace: debugTrace, results }, null, 2)}</pre>
        </details>
      ) : null}

      <details className="debug-details">
        <summary className="debug-summary">Phản hồi thô</summary>
        <pre className="code-block">{JSON.stringify(rawResponse, null, 2)}</pre>
      </details>
    </div>
  );
}

function IntentPlanSection({ plan }: { plan: IntentPlan }) {
  const tools =
    plan.tools_to_use && plan.tools_to_use.length > 0
      ? plan.tools_to_use.join(", ")
      : "—";

  return (
    <details className="intent-details">
      <summary className="debug-summary">Kế hoạch phân tích</summary>
      <dl className="intent-dl">
        <dt>Truy vấn gốc</dt>
        <dd>{plan.original_query ?? "—"}</dd>
        <dt>Truy vấn chuẩn hóa</dt>
        <dd>{plan.normalized_query ?? "—"}</dd>
        <dt>Công cụ sử dụng</dt>
        <dd>{tools}</dd>
        <dt>Ý định chính</dt>
        <dd>{plan.primary_intent ?? "—"}</dd>
        <dt>Chế độ phân loại</dt>
        <dd>{plan.classifier_mode ?? "—"}</dd>
        <dt>Lý do</dt>
        <dd>{plan.reasoning_brief ?? "—"}</dd>
        {plan.tool_queries && Object.keys(plan.tool_queries).length > 0 ? (
          <>
            <dt>Truy vấn nhánh</dt>
            <dd>
              <pre className="intent-json-inline">
                {JSON.stringify(plan.tool_queries, null, 2)}
              </pre>
            </dd>
          </>
        ) : null}
        {plan.entities && Object.keys(plan.entities).length > 0 ? (
          <>
            <dt>Entities</dt>
            <dd>
              <pre className="intent-json-inline">
                {JSON.stringify(plan.entities, null, 2)}
              </pre>
            </dd>
          </>
        ) : null}
        {plan.time_constraints && Object.keys(plan.time_constraints).length > 0 ? (
          <>
            <dt>Thời gian</dt>
            <dd>
              <pre className="intent-json-inline">
                {JSON.stringify(plan.time_constraints, null, 2)}
              </pre>
            </dd>
          </>
        ) : null}
        {plan.analysis_requirements && Object.keys(plan.analysis_requirements).length > 0 ? (
          <>
            <dt>Phân tích</dt>
            <dd>
              <pre className="intent-json-inline">
                {JSON.stringify(plan.analysis_requirements, null, 2)}
              </pre>
            </dd>
          </>
        ) : null}
      </dl>
    </details>
  );
}
