import { useEffect, useState } from "react";
import {
  buildLoadingPipeline,
  isAgentStep,
  loadingProgressPercent,
  splitPipelineSteps,
  type PipelineStep,
} from "../pipeline";
import { clientTimeoutSeconds } from "../types";

type PipelineProgressProps = {
  mode: "loading" | "completed";
  steps?: PipelineStep[];
  hint?: string;
};

const LOADING_PHASE_MS = 4_500;
const LOADING_MAX_PHASE = 4;

export function PipelineProgress({ mode, steps, hint }: PipelineProgressProps) {
  const [activeIndex, setActiveIndex] = useState(0);

  useEffect(() => {
    if (mode !== "loading") return;
    setActiveIndex(0);
    const timer = window.setInterval(() => {
      setActiveIndex((current) => Math.min(current + 1, LOADING_MAX_PHASE));
    }, LOADING_PHASE_MS);
    return () => window.clearInterval(timer);
  }, [mode]);

  const displaySteps = steps ?? (mode === "loading" ? buildLoadingPipeline(activeIndex) : []);
  const { pre, agents, post } = splitPipelineSteps(displaySteps);

  const doneCount = displaySteps.filter((step) => step.status === "done").length;
  const percent =
    mode === "loading"
      ? loadingProgressPercent(activeIndex)
      : Math.round((doneCount / Math.max(displaySteps.length, 1)) * 100);

  return (
    <div className="pipeline-panel" role={mode === "loading" ? "status" : "region"} aria-live="polite">
      <div className="pipeline-panel-head">
        <p className="pipeline-panel-title">
          {mode === "loading" ? "Đang xử lý pipeline" : "Luồng xử lý đã chạy"}
        </p>
        <span className="pipeline-panel-percent">{percent}%</span>
      </div>

      <div className="pipeline-bar" aria-hidden="true">
        <div className="pipeline-bar-fill" style={{ width: `${percent}%` }} />
      </div>

      <div className="pipeline-flow">
        {pre.map((step) => (
          <PipelineStepRow key={step.id} step={step} />
        ))}

        {agents.length > 0 ? (
          <div className="pipeline-parallel-block">
            <div className="pipeline-parallel-head">
              <span className="pipeline-parallel-badge">Chạy song song</span>
              <span className="pipeline-parallel-note">
                {agents.map((step) => step.label.replace("Agent ", "")).join(" · ")}
              </span>
            </div>
            <ul className="pipeline-steps pipeline-steps-nested">
              {agents.map((step) => (
                <PipelineStepRow key={step.id} step={step} nested />
              ))}
            </ul>
          </div>
        ) : null}

        {mode === "loading" && activeIndex === 2 && agents.length === 0 ? (
          <div className="pipeline-parallel-block pipeline-parallel-block-active">
            <div className="pipeline-parallel-head">
              <span className="pipeline-parallel-badge">Chạy song song</span>
              <span className="pipeline-parallel-note">Đang chạy agent được chọn…</span>
            </div>
          </div>
        ) : null}

        {post.map((step) => (
          <PipelineStepRow key={step.id} step={step} />
        ))}
      </div>

      {hint ? <p className="pipeline-hint">{hint}</p> : null}
      {mode === "loading" ? (
        <p className="pipeline-hint">
          Giới hạn chờ tối đa {clientTimeoutSeconds()} giây. Các agent (market / news / …) chạy độc lập, không
          theo thứ tự tuần tự.
        </p>
      ) : null}
    </div>
  );
}

function PipelineStepRow({ step, nested = false }: { step: PipelineStep; nested?: boolean }) {
  const Tag = nested ? "li" : "div";
  return (
    <Tag className={`pipeline-step pipeline-step-${step.status}`}>
      <span className="pipeline-step-dot" aria-hidden="true" />
      <span className="pipeline-step-body">
        <span className="pipeline-step-label">{step.label}</span>
        {step.detail ? <span className="pipeline-step-detail">{step.detail}</span> : null}
      </span>
      <span className="pipeline-step-badge">{statusLabel(step.status)}</span>
    </Tag>
  );
}

function statusLabel(status: PipelineStep["status"]): string {
  switch (status) {
    case "active":
      return "Đang chạy";
    case "done":
      return "Xong";
    case "error":
      return "Lỗi";
    case "skipped":
      return "Bỏ qua";
    default:
      return "Chờ";
  }
}
