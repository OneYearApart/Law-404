import { FiUser } from 'react-icons/fi';

import styles from './MessageBubble.module.css';

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
    return (
      <div className={rowClassName}>
        <div className={styles.userBubble}>
          <FiUser className={styles.inlineIcon} aria-hidden="true" />
          <p>{content}</p>
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
