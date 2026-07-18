import { apiRequest, API_BASE_URL, ApiError } from '../../common/apiClient.js';
import { getAccessToken } from '../../common/authToken.js';

export const B_API_PATH = '/chat/b/';

function unwrap(payload) {
  return payload?.data ?? payload;
}

function buildUrl(path) {
  if (/^https?:\/\//.test(path)) {
    return path;
  }

  return `${API_BASE_URL}${path.startsWith('/') ? path : `/${path}`}`;
}

function parseSseEvent(rawEvent) {
  const dataLines = rawEvent
    .split('\n')
    .filter((line) => line.startsWith('data:'))
    .map((line) => line.slice(5).trimStart());

  if (!dataLines.length) {
    return null;
  }

  try {
    return JSON.parse(dataLines.join('\n'));
  } catch {
    return null;
  }
}

async function readBStream(response, handlers = {}) {
  const reader = response.body?.getReader();
  if (!reader) {
    throw new ApiError({
      message: '스트리밍 응답을 읽을 수 없습니다.',
      code: 'B_STREAM_UNAVAILABLE',
    });
  }

  const decoder = new TextDecoder('utf-8');
  let buffer = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) {
      break;
    }

    buffer += decoder.decode(value, { stream: true });
    const parts = buffer.split(/\r?\n\r?\n/);
    buffer = parts.pop() ?? '';

    for (const part of parts) {
      const event = parseSseEvent(part);
      if (!event) {
        continue;
      }

      if (event.type === 'meta') {
        handlers.onMeta?.(event.data ?? {});
      } else if (event.type === 'token') {
        handlers.onToken?.(String(event.data ?? ''));
      } else if (event.type === 'error') {
        throw new ApiError({
          message: String(event.data || 'B파트 답변 생성 중 오류가 발생했습니다.'),
          code: 'B_STREAM_ERROR',
          payload: event,
        });
      } else if (event.type === 'done') {
        handlers.onDone?.();
      }
    }
  }
}

export async function createBConversation() {
  const payload = await apiRequest('/conversations/', {
    method: 'POST',
    body: { part: 'b' },
  });

  const conversation = unwrap(payload);
  return conversation?.conversation_id ?? conversation?.id;
}

export async function sendBChat({
  message,
  conversationId = null,
  pendingAction = null,
  calendarMode = 'dry_run',
  calendarProvider = 'smithery_googlecalendar',
  calendarId = 'primary',
  topK = 5,
  onMeta,
  onToken,
  onDone,
} = {}) {
  const token = getAccessToken();
  const response = await fetch(buildUrl(B_API_PATH), {
    method: 'POST',
    headers: {
      Accept: 'text/event-stream',
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify({
      message,
      conversation_id: conversationId,
      pending_action: pendingAction,
      calendar_mode: calendarMode,
      calendar_provider: calendarProvider,
      calendar_id: calendarId,
      top_k: topK,
    }),
  });

  if (!response.ok) {
    let payload;
    try {
      payload = await response.json();
    } catch {
      payload = await response.text();
    }

    throw new ApiError({
      message:
        payload?.detail ||
        payload?.error?.message ||
        (typeof payload === 'string' ? payload : null) ||
        'B파트 상담 요청을 처리하지 못했습니다.',
      status: response.status,
      code: `HTTP_${response.status}`,
      payload,
    });
  }

  await readBStream(response, { onMeta, onToken, onDone });
}
