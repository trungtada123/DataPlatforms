import { MarkdownLite } from "../markdownLite";

type AnswerBlockProps = {
  answer: string;
};

export function AnswerBlock({ answer }: AnswerBlockProps) {
  const content = answer?.trim();

  return (
    <section className="answer-block">
      <h3 className="section-label">Câu trả lời</h3>
      <hr className="answer-divider" />
      {content ? (
        <MarkdownLite text={content} />
      ) : (
        <p className="md-p">Không có nội dung trả lời.</p>
      )}
    </section>
  );
}