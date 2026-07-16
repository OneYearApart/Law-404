import { motion } from 'framer-motion';
import { FiAlertTriangle } from 'react-icons/fi';

import styles from './AssistantAnswer.module.css';

function DAssistantAnswer({ content }) {
  return (
    <motion.article className={styles.answer} initial={{ opacity: 0 }} animate={{ opacity: 1 }} whileHover={{ y: -2 }}>
      <header className={styles.header}>
        <span className={styles.label}>
          <FiAlertTriangle aria-hidden="true" />
          위험 신호 확인
        </span>
        <span className={styles.status}>주의</span>
      </header>
      <p>{content}</p>
    </motion.article>
  );
}

export default DAssistantAnswer;
