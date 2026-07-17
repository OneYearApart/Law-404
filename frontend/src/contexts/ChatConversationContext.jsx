import { useCallback, useMemo, useState } from 'react';

import { listAConversations } from '../api/chat/A/aApi.js';
import { listConversations } from '../api/chat/conversationsApi.js';
import { ChatConversationContext } from './chatConversationContext.js';

function normalizeAPartConversation(conversation) {
  return {
    ...conversation,
    conversation_id: String(conversation.conversation_id),
    part: 'a',
  };
}

function mergeConversationLists(commonConversations, aConversations) {
  const mergedById = new Map(
    commonConversations.map((conversation) => [
      String(conversation.conversation_id),
      conversation,
    ]),
  );

  aConversations.forEach((conversation) => {
    const normalized = normalizeAPartConversation(conversation);
    const conversationId = String(normalized.conversation_id);
    const commonConversation = mergedById.get(conversationId);
    mergedById.set(
      conversationId,
      commonConversation
        ? { ...commonConversation, ...normalized, part: 'a' }
        : normalized,
    );
  });

  return [...mergedById.values()].sort((left, right) => {
    const leftTime = new Date(left.updated_at || left.created_at || 0).getTime();
    const rightTime = new Date(right.updated_at || right.created_at || 0).getTime();
    return rightTime - leftTime;
  });
}

async function loadConversationLists() {
  const [commonResult, aResult] = await Promise.allSettled([
    listConversations(),
    listAConversations(),
  ]);

  const commonConversations = commonResult.status === 'fulfilled' ? commonResult.value : [];
  const aConversations = aResult.status === 'fulfilled' ? aResult.value : [];

  if (commonResult.status === 'rejected' && aResult.status === 'rejected') {
    throw commonResult.reason;
  }

  return {
    commonConversations,
    aConversations,
    merged: mergeConversationLists(commonConversations, aConversations),
  };
}

export function ChatConversationProvider({ children }) {
  const [conversations, setConversations] = useState([]);
  const [aConversations, setAConversations] = useState([]);
  const [activeAConversationId, setActiveAConversationId] = useState(null);
  const [newConversationVersion, setNewConversationVersion] = useState(0);
  const [isHistoryLoading, setIsHistoryLoading] = useState(false);

  const refreshConversations = useCallback(async () => {
    setIsHistoryLoading(true);
    try {
      const result = await loadConversationLists();
      setAConversations(result.aConversations);
      setConversations(result.merged);
      return result.merged;
    } finally {
      setIsHistoryLoading(false);
    }
  }, []);

  const refreshAConversations = useCallback(async ({ selectLatest = false } = {}) => {
    setIsHistoryLoading(true);
    try {
      const result = await loadConversationLists();
      setAConversations(result.aConversations);
      setConversations(result.merged);
      if (selectLatest && result.aConversations.length) {
        setActiveAConversationId(
          (current) => current || result.aConversations[0].conversation_id,
        );
      }
      return result.aConversations;
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

  const notifyConversationSaved = useCallback(async () => {
    const refresh = async () => {
      try {
        await refreshConversations();
      } catch {
        // 대화 저장 성공 후 목록 갱신 실패가 상담 흐름을 막지 않게 한다.
      }
    };

    await refresh();
    window.setTimeout(refresh, 1200);
  }, [refreshConversations]);

  const notifyAConversationSaved = useCallback(async (conversationId) => {
    setActiveAConversationId(String(conversationId));
    await notifyConversationSaved();
  }, [notifyConversationSaved]);

  const value = useMemo(() => ({
    conversations,
    aConversations,
    activeAConversationId,
    newConversationVersion,
    isHistoryLoading,
    refreshConversations,
    refreshAConversations,
    activateAConversation,
    startNewAConversation,
    notifyConversationSaved,
    notifyAConversationSaved,
  }), [
    conversations,
    aConversations,
    activeAConversationId,
    newConversationVersion,
    isHistoryLoading,
    refreshConversations,
    refreshAConversations,
    activateAConversation,
    startNewAConversation,
    notifyConversationSaved,
    notifyAConversationSaved,
  ]);

  return (
    <ChatConversationContext.Provider value={value}>
      {children}
    </ChatConversationContext.Provider>
  );
}
