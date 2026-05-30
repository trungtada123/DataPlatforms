type ErrorBoxProps = {
  message: string;
};

export function ErrorBox({ message }: ErrorBoxProps) {
  return (
    <div className="error-box" role="alert">
      <span className="error-box-icon" aria-hidden="true">
        ×
      </span>
      <div>
        <p className="error-box-title">Đã xảy ra lỗi</p>
        <p className="error-box-message">{message}</p>
        <p className="error-box-hint">Gợi ý: Kiểm tra kết nối proxy /api và trạng thái container backend.</p>
      </div>
    </div>
  );
}
