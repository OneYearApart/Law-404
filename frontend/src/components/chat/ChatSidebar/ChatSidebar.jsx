import { motion } from 'framer-motion';
import { FiClock, FiUser } from 'react-icons/fi';

import styles from './ChatSidebar.module.css';

function ChatSidebar() {
  return (
    <motion.aside
      className={styles.sidebar}
      initial={{ x: -20, opacity: 0 }}
      animate={{ x: 0, opacity: 1 }}
      transition={{ duration: 0.35, ease: 'easeOut' }}
    >
      <section className={styles.memberSection} aria-label="회원 정보">
        <div className={styles.avatar} aria-hidden="true">
          <FiUser />
        </div>
        <strong className={styles.nickname}>사용자</strong>
        <span className={styles.userId}>인증 연동 전</span>
      </section>

      <section className={styles.recentSection}>
        <h2 className={styles.sectionTitle}>
          <FiClock aria-hidden="true" />
          <span>최근 대화</span>
        </h2>
        <p className={styles.emptyHistory}>최근 상담이 없습니다.</p>
      </section>
    </motion.aside>
  );
}

export default ChatSidebar;
