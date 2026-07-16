import { createContext, useContext } from 'react';

export const ChatConversationContext = createContext(null);

export function useChatConversation() {
  const context = useContext(ChatConversationContext);
  if (!context) {
    throw new Error('useChatConversation은 ChatConversationProvider 안에서 사용해야 합니다.');
  }
  return context;
}
