import { motion } from 'framer-motion';
import { FiUser } from 'react-icons/fi';
import { RiRobot2Line } from 'react-icons/ri';

import styles from './MessageBubble.module.css';

function MessageBubble({ role, content, AssistantAnswer }) {
  const isUser = role === 'user';

  if (isUser) {
    return (
      <motion.div
        className={`${styles.messageRow} ${styles.userRow}`}
        initial={{ opacity: 0, x: 18, y: 6 }}
        animate={{ opacity: 1, x: 0, y: 0 }}
        transition={{ duration: 0.25 }}
      >
        <div className={styles.userBubble}>
          <FiUser className={styles.inlineIcon} aria-hidden="true" />
          <p>{content}</p>
        </div>
      </motion.div>
    );
  }

  return (
    <motion.div
      className={`${styles.messageRow} ${styles.assistantRow}`}
      initial={{ opacity: 0, x: -18, y: 6 }}
      animate={{ opacity: 1, x: 0, y: 0 }}
      transition={{ duration: 0.3 }}
    >
      <span className={styles.avatar} aria-hidden="true">
        <RiRobot2Line />
      </span>
      <AssistantAnswer content={content} />
    </motion.div>
  );
}

export default MessageBubble;
