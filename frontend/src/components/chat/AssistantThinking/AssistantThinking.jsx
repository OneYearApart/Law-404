import { motion } from 'framer-motion';

import styles from './AssistantThinking.module.css';

const DOT_DELAYS = [0, 0.18, 0.36];

function AssistantThinking({
  title = '답변을 생각하고 있어요',
  description = '질문과 관련 근거를 확인하고 있습니다.',
}) {
  return (
    <motion.div
      className={styles.thinkingRow}
      role="status"
      aria-live="polite"
      initial={{ opacity: 0, x: -18, y: 8 }}
      animate={{ opacity: 1, x: 0, y: 0 }}
      exit={{ opacity: 0, x: -10, y: -4 }}
      transition={{ duration: 0.28, ease: 'easeOut' }}
    >
      <motion.div
        className={styles.character}
        aria-hidden="true"
        animate={{ y: [0, -4, 0] }}
        transition={{ duration: 1.8, repeat: Infinity, ease: 'easeInOut' }}
      >
        <img src="/images/thinking.png" alt="" />
      </motion.div>

      <div className={styles.bubble}>
        <div className={styles.titleLine}>
          <strong>{title}</strong>
          <span className={styles.dots} aria-hidden="true">
            {DOT_DELAYS.map((delay) => (
              <motion.span
                key={delay}
                animate={{ opacity: [0.25, 1, 0.25], y: [0, -3, 0] }}
                transition={{
                  duration: 0.9,
                  repeat: Infinity,
                  ease: 'easeInOut',
                  delay,
                }}
              />
            ))}
          </span>
        </div>
        <p>{description}</p>
      </div>
    </motion.div>
  );
}

export default AssistantThinking;
