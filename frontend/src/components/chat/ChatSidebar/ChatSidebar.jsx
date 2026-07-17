import { motion } from 'framer-motion';
import { useEffect, useState } from 'react';
import { FiClock, FiLoader, FiLogOut, FiMessageSquare, FiPlus, FiUser } from 'react-icons/fi';
import { useLocation, useNavigate } from 'react-router';

import { CONSULTATION_TYPE_TO_PART } from '../../../constants/chatbot.js';
import { CHAT_ROUTES, ROUTES } from '../../../constants/routes.js';
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
  const { pathname } = useLocation();
  const [isLoggingOut, setIsLoggingOut] = useState(false);
  const {
    aConversations,
    conversations,
    activeAConversationId,
    isHistoryLoading,
    refreshAConversations,
    refreshConversations,
    activateAConversation,
    startNewAConversation,
  } = useChatConversation();

  // ChatLayout 안이라 consultationType prop이 없다 — 라우트에서 역산한다.
  const consultationType = CHAT_ROUTES.find((route) => route.path === pathname)?.key;
  const isAPart = consultationType === 'before-contract';

  // A는 전용 라우트를 계속 쓴다(제목 폴백·전용 필드 유지). 나머지 파트는 전 파트를 주는
  // 공용 목록에서 자기 part만 골라 쓴다 — 클릭 복원은 아직 A에만 있다.
  const historyItems = isAPart
    ? aConversations
    : conversations
      .filter((conversation) => conversation.part === CONSULTATION_TYPE_TO_PART[consultationType])
      .map((conversation) => ({
        conversation_id: conversation.id,
        title: conversation.title,
        updated_at: conversation.updated_at,
      }));

  useEffect(() => {
    refreshAConversations({ selectLatest: true }).catch(() => {
      // 상담 화면 자체는 사용할 수 있도록 사이드바 오류는 조용히 처리한다.
    });
    refreshConversations();
  }, [refreshAConversations, refreshConversations]);

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

        {isHistoryLoading && !historyItems.length ? (
          <p className={styles.loadingHistory}>
            <FiLoader aria-hidden="true" />
            대화를 불러오는 중입니다.
          </p>
        ) : historyItems.length ? (
          <div className={styles.historyList}>
            {historyItems.map((conversation) => {
              const isActive = isAPart
                && String(conversation.conversation_id) === String(activeAConversationId);
              return (
                <button
                  type="button"
                  key={conversation.conversation_id}
                  className={isActive ? styles.activeHistory : ''}
                  // 클릭 복원은 A 전용 경로(getAConversation)라 나머지 파트는 아직 열 수 없다.
                  // 목록만 보여주고 누르면 아무 일도 안 하도록 둔다(404보다 낫다).
                  disabled={!isAPart}
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
