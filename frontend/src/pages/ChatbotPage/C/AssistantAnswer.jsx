import { motion } from 'framer-motion';
import { FiCheckCircle } from 'react-icons/fi';

import styles from './AssistantAnswer.module.css';

function CAssistantAnswer({ content }) {
  return (
    <motion.article className={styles.answer} initial={{ opacity: 0 }} animate={{ opacity: 1 }} whileHover={{ y: -2 }}>
      <span className={styles.icon} aria-hidden="true">
        <FiCheckCircle />
      </span>
      <div>
        <span className={styles.label}>계약 후 절차</span>
        <p>{content}</p>
      </div>
    </motion.article>
  );
}

export default CAssistantAnswer;
