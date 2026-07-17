import { apiRequest } from '../common/apiClient.js';

const PART_LABELS = Object.freeze({
  a: '계약 전',
  b: '계약 중',
  c: '계약 후',
  d: '전세사기',
});

function normalizeConversation(item = {}) {
  const part = String(item.part || '').toLowerCase();
  const state = item.state && typeof item.state === 'object' ? item.state : {};
  const fallbackTitle = state.initial_query
    || state.user_input
    || state.question
    || `새 ${PART_LABELS[part] || '상담'}`;

  return {
    ...item,
    conversation_id: String(item.conversation_id ?? item.id ?? ''),
    part,
    title: String(item.title || fallbackTitle).trim(),
  };
}

export async function createConversation({ part, title }) {
  const payload = await apiRequest('/conversations/', {
    method: 'POST',
    body: { part, title },
  });
  return normalizeConversation(payload);
}

export async function saveConversationMessage({ conversationId, part, role, content }) {
  return apiRequest(`/conversations/${conversationId}/messages`, {
    method: 'POST',
    body: { part, role, content },
  });
}

export async function listConversations() {
  const payload = await apiRequest('/conversations/');
  return Array.isArray(payload) ? payload.map(normalizeConversation) : [];
}

export async function loadConversation(conversationId) {
  const payload = await apiRequest(`/conversations/${conversationId}`);
  return Array.isArray(payload) ? payload : [];
}
