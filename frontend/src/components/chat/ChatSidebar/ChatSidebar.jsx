import { motion } from 'framer-motion';
import { useEffect, useMemo, useState } from 'react';
import {
  FiLoader,
  FiLogOut,
  FiMessageSquare,
  FiPlus,
  FiUser,
} from 'react-icons/fi';
import { useLocation, useNavigate } from 'react-router';

import { ROUTES } from '../../../constants/routes.js';
import { useAuth } from '../../../contexts/AuthContext.jsx';
import { useChatConversation } from '../../../contexts/chatConversationContext.js';
import styles from './ChatSidebar.module.css';

const CATEGORY_CONFIG = Object.freeze([
  {
    part: 'a',
    label: '계약 전',
    path: ROUTES.CHAT_BEFORE_CONTRACT,
  },
  {
    part: 'b',
    label: '계약 중',
    path: ROUTES.CHAT_DURING_CONTRACT,
  },
  {
    part: 'c',
    label: '계약 후',
    path: ROUTES.CHAT_AFTER_CONTRACT,
  },
  {
    part: 'd',
    label: '전세사기',
    path: ROUTES.CHAT_JEONSE_FRAUD,
  },
]);

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

function categoryFromPath(pathname) {
  return CATEGORY_CONFIG.find((category) => pathname.startsWith(category.path))
    || CATEGORY_CONFIG[0];
}

function ChatSidebar() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [isLoggingOut, setIsLoggingOut] = useState(false);
  const {
    conversations,
    activeAConversationId,
    isHistoryLoading,
    refreshConversations,
    activateAConversation,
    startNewAConversation,
  } = useChatConversation();

  const currentCategory = categoryFromPath(location.pathname);
  const selectedConversationId = String(
    location.state?.conversationId
      || (currentCategory.part === 'a' ? activeAConversationId : '')
      || '',
  );

  const currentConversations = useMemo(
    () => conversations.filter((conversation) => conversation.part === currentCategory.part),
    [conversations, currentCategory.part],
  );

  useEffect(() => {
    refreshConversations().catch(() => {
      // 상담 화면 자체는 사용할 수 있도록 사이드바 오류는 조용히 처리한다.
    });
  }, [refreshConversations]);

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

  const handleNewConversation = () => {
    if (currentCategory.part === 'a') {
      startNewAConversation();
    }
    navigate(currentCategory.path, {
      replace: currentCategory.path === location.pathname,
      state: { newConversationKey: Date.now() },
    });
  };

  const openConversation = (conversationId) => {
    const normalizedId = String(conversationId);
    if (currentCategory.part === 'a') {
      activateAConversation(normalizedId);
    }
    navigate(currentCategory.path, {
      state: {
        conversationId: normalizedId,
        conversationPart: currentCategory.part,
      },
    });
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
          onClick={handleNewConversation}
        >
          <FiPlus aria-hidden="true" />
          <span>새 {currentCategory.label} 상담</span>
        </button>

        <div className={styles.historySection}>
          <div className={styles.historyHeader}>
            <strong>{currentCategory.label} 대화</strong>
            <span>{currentConversations.length}</span>
          </div>

          {isHistoryLoading && !currentConversations.length ? (
            <p className={styles.loadingHistory}>
              <FiLoader aria-hidden="true" />
              대화를 불러오는 중입니다.
            </p>
          ) : currentConversations.length ? (
            <div className={styles.historyList} aria-label={`${currentCategory.label} 대화 목록`}>
              {currentConversations.map((conversation) => {
                const isActive = String(conversation.conversation_id) === selectedConversationId;
                return (
                  <button
                    type="button"
                    key={`${currentCategory.part}-${conversation.conversation_id}`}
                    className={isActive ? styles.activeHistory : ''}
                    onClick={() => openConversation(conversation.conversation_id)}
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
            <p className={styles.emptyHistory}>
              저장된 {currentCategory.label} 대화가 없습니다.
            </p>
          )}
        </div>
      </section>
    </motion.aside>
  );
}

export default ChatSidebar;
