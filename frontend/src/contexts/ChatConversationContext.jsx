import { useCallback, useMemo, useState } from 'react';

import { listAConversations } from '../api/chat/A/aApi.js';
import { listConversations } from '../api/common/conversationsApi.js';
import { ChatConversationContext } from './chatConversationContext.js';

export function ChatConversationProvider({ children }) {
  const [aConversations, setAConversations] = useState([]);
  // 공용 라우트가 전 파트를 한 번에 준다 — 파트별로 나눠 담지 않고 소비하는 쪽이 part로 고른다.
  // A는 전용 라우트(aConversations)를 계속 쓴다: 그쪽 제목 폴백·전용 필드를 잃지 않기 위함.
  const [conversations, setConversations] = useState([]);
  const [activeAConversationId, setActiveAConversationId] = useState(null);
  const [newConversationVersion, setNewConversationVersion] = useState(0);
  const [isHistoryLoading, setIsHistoryLoading] = useState(false);

  const refreshAConversations = useCallback(async ({ selectLatest = false } = {}) => {
    setIsHistoryLoading(true);
    try {
      const conversations = await listAConversations();
      setAConversations(conversations);
      if (selectLatest && conversations.length) {
        setActiveAConversationId((current) => current || conversations[0].conversation_id);
      }
      return conversations;
    } finally {
      setIsHistoryLoading(false);
    }
  }, []);

  // 전 파트 목록. A와 달리 selectLatest가 없다 — A만 마지막 대화를 자동 복원하고,
  // 나머지 파트는 아직 복원 경로가 없어 목록 표시 용도로만 쓴다.
  const refreshConversations = useCallback(async () => {
    try {
      setConversations(await listConversations());
    } catch {
      // 상담 화면 자체는 쓸 수 있도록 사이드바 오류는 조용히 처리한다(A 경로와 동일 방침).
    }
  }, []);

  const activateAConversation = useCallback((conversationId) => {
    setActiveAConversationId(String(conversationId));
  }, []);

  const startNewAConversation = useCallback(() => {
    setActiveAConversationId(null);
    setNewConversationVersion((current) => current + 1);
  }, []);

  const notifyAConversationSaved = useCallback(async (conversationId) => {
    setActiveAConversationId(String(conversationId));

    const refresh = async () => {
      try {
        const conversations = await listAConversations();
        setAConversations(conversations);
      } catch {
        // 대화 자체는 저장됐으므로 목록 갱신 실패가 상담 흐름을 막지 않게 한다.
      }
    };

    await refresh();
    window.setTimeout(refresh, 2500);
    window.setTimeout(refresh, 6000);
  }, []);

  const value = useMemo(() => ({
    aConversations,
    conversations,
    activeAConversationId,
    newConversationVersion,
    isHistoryLoading,
    refreshAConversations,
    refreshConversations,
    activateAConversation,
    startNewAConversation,
    notifyAConversationSaved,
  }), [
    aConversations,
    conversations,
    activeAConversationId,
    newConversationVersion,
    isHistoryLoading,
    refreshAConversations,
    refreshConversations,
    activateAConversation,
    startNewAConversation,
    notifyAConversationSaved,
  ]);

  return (
    <ChatConversationContext.Provider value={value}>
      {children}
    </ChatConversationContext.Provider>
  );
}
