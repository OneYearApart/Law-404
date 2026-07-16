import { useCallback, useMemo, useState } from 'react';

import { listAConversations } from '../api/chat/A/aApi.js';
import { ChatConversationContext } from './chatConversationContext.js';

export function ChatConversationProvider({ children }) {
  const [aConversations, setAConversations] = useState([]);
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
    activeAConversationId,
    newConversationVersion,
    isHistoryLoading,
    refreshAConversations,
    activateAConversation,
    startNewAConversation,
    notifyAConversationSaved,
  }), [
    aConversations,
    activeAConversationId,
    newConversationVersion,
    isHistoryLoading,
    refreshAConversations,
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
