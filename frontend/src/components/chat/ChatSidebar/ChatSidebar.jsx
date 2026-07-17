import { motion } from 'framer-motion';
import { useEffect, useState } from 'react';
import { FiClock, FiLoader, FiLogOut, FiMessageSquare, FiPlus, FiUser } from 'react-icons/fi';
import { useNavigate } from 'react-router';

import { ROUTES } from '../../../constants/routes.js';
import { useAuth } from '../../../contexts/AuthContext.jsx';
import { useChatConversation } from '../../../contexts/chatConversationContext.js';
import styles from './ChatSidebar.module.css';

function formatUpdatedAt(value) {
  if (!value) {
    return '';
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return '';
  }
  return new Intl.DateTimeFormat('ko-KR', {
    month: 'numeric',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  }).format(date);
}

function ChatSidebar() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const [isLoggingOut, setIsLoggingOut] = useState(false);
  const {
    aConversations,
    activeAConversationId,
    isHistoryLoading,
    refreshAConversations,
    activateAConversation,
    startNewAConversation,
  } = useChatConversation();

  useEffect(() => {
    refreshAConversations({ selectLatest: true }).catch(() => {
      // 상담 화면 자체는 사용할 수 있도록 사이드바 오류는 조용히 처리한다.
    });
  }, [refreshAConversations]);

  const handleLogout = async () => {
    if (isLoggingOut) {
      return;
    }
    setIsLoggingOut(true);
    try {
      await logout();
      navigate(ROUTES.LOGIN, { replace: true });
    } finally {
      setIsLoggingOut(false);
    }
  };

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
        <strong className={styles.nickname}>{user?.nickname || '사용자'}</strong>
        <button
          type="button"
          className={styles.logoutButton}
          onClick={handleLogout}
          disabled={isLoggingOut}
        >
          <FiLogOut aria-hidden="true" />
          <span>{isLoggingOut ? '로그아웃 중' : '로그아웃'}</span>
        </button>
      </section>

      <section className={styles.recentSection}>
        <button
          type="button"
          className={styles.newConversationButton}
          onClick={startNewAConversation}
        >
          <FiPlus aria-hidden="true" />
          <span>새 상담</span>
        </button>

        <h2 className={styles.sectionTitle}>
          <FiClock aria-hidden="true" />
          <span>최근 대화</span>
        </h2>

        {isHistoryLoading && !aConversations.length ? (
          <p className={styles.loadingHistory}>
            <FiLoader aria-hidden="true" />
            대화를 불러오는 중입니다.
          </p>
        ) : aConversations.length ? (
          <div className={styles.historyList}>
            {aConversations.map((conversation) => {
              const isActive = String(conversation.conversation_id) === String(activeAConversationId);
              return (
                <button
                  type="button"
                  key={conversation.conversation_id}
                  className={isActive ? styles.activeHistory : ''}
                  onClick={() => activateAConversation(conversation.conversation_id)}
                  title={conversation.title}
                >
                  <FiMessageSquare aria-hidden="true" />
                  <span className={styles.historyText}>
                    <strong>{conversation.title}</strong>
                    <small>{formatUpdatedAt(conversation.updated_at)}</small>
                  </span>
                </button>
              );
            })}
          </div>
        ) : (
          <p className={styles.emptyHistory}>저장된 상담이 없습니다.</p>
        )}
      </section>
    </motion.aside>
  );
}

export default ChatSidebar;
