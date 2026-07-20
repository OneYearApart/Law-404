import ConsultationAnswer from './ConsultationAnswer.jsx';
import DocumentAnswer from './DocumentAnswer.jsx';

/**
 * C파트(계약 후) 답변 디스패처.
 *
 * C파트는 답변이 두 종류입니다:
 *   - 상담(/ask/stream)  → ConsultationAnswer (6섹션 + FAQ, 또는 정의/범위밖 단문)
 *   - 문서(/document)     → DocumentAnswer (진행바 + 되묻기 + 완성 내용증명)
 *
 * answerVariants.js 에는 이 컴포넌트 하나만 매핑되어 있고,
 * 여기서 content 모양을 보고 알맞은 컴포넌트로 넘깁니다.
 * (그래서 answerVariants.js / MessageBubble 은 건드릴 필요가 없습니다.)
 *
 * 구분 규칙:
 *   content.kind === 'document'  → 문서
 *   그 외(문자열 포함)            → 상담
 */
function AssistantAnswer(props) {
  const { content } = props;

  const isDocument =
    content && typeof content === 'object' && content.kind === 'document';

  if (isDocument) {
    return <DocumentAnswer content={content} />;
  }

  return <ConsultationAnswer {...props} />;
}

export default AssistantAnswer;