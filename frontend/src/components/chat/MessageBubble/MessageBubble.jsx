import { FiFileText, FiUser } from 'react-icons/fi';

import styles from './MessageBubble.module.css';

const DOCUMENT_TYPE_LABELS = {
  lease_contract: '임대차계약서',
  registry: '등기부등본',
};

function normalizeUserContent(content) {
  if (content && typeof content === 'object') {
    return {
      text: String(content.text || '').trim(),
      attachments: Array.isArray(content.attachments) ? content.attachments : [],
    };
  }

  return {
    text: String(content || '').trim(),
    attachments: [],
  };
}

function MessageBubble({
  role,
  content,
  AssistantAnswer,
  onQuickAnswer,
  isInteractive = false,
  shouldAnimate = false,
}) {
  const isUser = role === 'user';
  const isCompletedQuestion = !isUser && content?.displayMode === 'completed-question';
  const rowClassName = [
    styles.messageRow,
    isUser ? styles.userRow : styles.assistantRow,
    isCompletedQuestion ? styles.completedAssistantRow : '',
    shouldAnimate ? styles.messageEnter : '',
  ]
    .filter(Boolean)
    .join(' ');

  if (isUser) {
    const userContent = normalizeUserContent(content);

    return (
      <div className={rowClassName}>
        <div className={styles.userMessageGroup}>
          {userContent.attachments.length > 0 && (
            <div className={styles.userAttachments} aria-label="질문과 함께 첨부한 문서">
              {userContent.attachments.map((document) => (
                <div className={styles.userAttachment} key={document.document_id}>
                  <span className={styles.userAttachmentIcon} aria-hidden="true">
                    <FiFileText />
                  </span>
                  <span className={styles.userAttachmentCopy}>
                    <strong title={document.original_filename}>
                      {document.original_filename || '첨부 문서.pdf'}
                    </strong>
                    <small>
                      {DOCUMENT_TYPE_LABELS[document.document_type]
                        || document.document_type
                        || 'PDF 문서'}
                    </small>
                  </span>
                </div>
              ))}
            </div>
          )}
          <div className={styles.userBubble}>
            <FiUser className={styles.inlineIcon} aria-hidden="true" />
            <p>{userContent.text}</p>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className={rowClassName}>
      <span className={styles.avatar} aria-hidden="true">
        <img src="/images/explain.png" alt="" />
      </span>
      <AssistantAnswer
        content={content}
        onQuickAnswer={onQuickAnswer}
        isInteractive={isInteractive}
      />
    </div>
  );
}

export default MessageBubble;
