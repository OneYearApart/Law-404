import { motion } from 'framer-motion';
import { FiAlertTriangle } from 'react-icons/fi';

import styles from './AssistantAnswer.module.css';

const STATUS_LABELS = {
  loading: '분석 중',
  streaming: '답변 중',
  done: '주의',
  error: '오류',
};

function DAssistantAnswer({ content }) {
  const { status, citations, text, errorMessage } = content;

  return (
    <motion.article className={styles.answer} initial={{ opacity: 0 }} animate={{ opacity: 1 }} whileHover={{ y: -2 }}>
      <header className={styles.header}>
        <span className={styles.label}>
          <FiAlertTriangle aria-hidden="true" />
          위험 신호 확인
        </span>
        <span className={styles.status}>{STATUS_LABELS[status]}</span>
      </header>

      {citations.length > 0 && (
        <section className={styles.citations}>
          <h3 className={styles.citationsTitle}>근거 자료</h3>
          {citations.map((citation) => (
            <article className={styles.citation} key={`${citation.source_type}-${citation.label}`}>
              <div className={styles.citationHead}>
                <span className={styles.sourceType}>{citation.source_type}</span>
                <span className={styles.citationLabel}>{citation.label}</span>
                {citation.is_excerpt && <span className={styles.excerpt}>발췌</span>}
              </div>
              <p className={styles.citationContent}>{citation.content}</p>
            </article>
          ))}
        </section>
      )}

      {status === 'error' ? (
        <p className={styles.errorMessage}>{errorMessage}</p>
      ) : (
        <p className={styles.body}>
          {text || (status === 'loading' ? '답변을 준비하고 있습니다.' : null)}
        </p>
      )}
    </motion.article>
  );
}

export default DAssistantAnswer;
