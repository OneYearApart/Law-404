import { apiRequest } from './apiClient.js';

export const CONVERSATIONS_PATH = '/conversations/';

/**
 * 로그인한 사용자의 **전 파트** 대화 목록(최신순). 각 항목에 part가 실려 오므로
 * 호출부가 파트별로 골라 쓴다 — 파트마다 요청을 나누지 않는 게 이 라우트의 설계다.
 *
 * A파트는 자체 라우트(/chat/a/conversations)를 쓴다. 그쪽은 risk_level 같은 전용 필드와
 * state 기반 제목 폴백이 있어 여기로 합치려면 별도 검토가 필요하다.
 */
export async function listConversations() {
  const conversations = await apiRequest(CONVERSATIONS_PATH);
  return Array.isArray(conversations) ? conversations : [];
}

export async function createConversation(part) {
  const conversation = await apiRequest(CONVERSATIONS_PATH, {
    method: 'POST',
    body: { part },
  });

  return conversation.id;
}
