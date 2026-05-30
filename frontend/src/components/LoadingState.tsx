import { PipelineProgress } from "./PipelineProgress";

export function LoadingState() {
  return (
    <div className="loading-state">
      <span className="spinner" aria-hidden="true" />
      <div className="loading-state-body">
        <p className="loading-state-title">Đang phân tích…</p>
        <p className="loading-state-detail">Hệ thống đang xử lý câu hỏi của bạn</p>
        <PipelineProgress mode="loading" />
      </div>
    </div>
  );
}
