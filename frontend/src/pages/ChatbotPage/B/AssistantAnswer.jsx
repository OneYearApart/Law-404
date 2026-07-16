import { motion } from 'framer-motion';
import { FiEdit3 } from 'react-icons/fi';

import styles from './AssistantAnswer.module.css';

function BAssistantAnswer({ content }) {
  return (
    <motion.article className={styles.answer} initial={{ opacity: 0 }} animate={{ opacity: 1 }} whileHover={{ y: -2 }}>
      <span className={styles.label}>
        <FiEdit3 aria-hidden="true" />
        계약 중 점검
      </span>
      <p>{content}</p>
    </motion.article>
  );
}

export default BAssistantAnswer;
