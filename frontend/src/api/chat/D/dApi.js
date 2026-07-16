import { API_BASE_URL, ApiError, apiRequest, refreshAccessToken } from '../../common/apiClient.js';
import { getAccessToken } from '../../common/authToken.js';

export const D_API_PATH = '/chat/d/';

const CONVERSATIONS_PATH = '/conversations/';

// D파트는 대화방을 만들어주지 않는다. conversation_id는 반드시 먼저 발급받아 보내야 한다.
export async function createDConversation() {
  const conversation = await apiRequest(CONVERSATIONS_PATH, {
    method: 'POST',
    body: { part: 'd' },
  });

  return conversation.id;
}

// EventSource는 GET 전용이고 Authorization 헤더를 붙일 수 없다. D파트는 POST + Bearer라서
// fetch + ReadableStream으로 직접 읽는다. 그 대가로 apiRequest의 401 자동 갱신을 못 쓰므로
// 여기서 같은 refresher를 한 번만 태워 재시도한다.
async function openDStream({ conversationId, userInput, signal, retried = false }) {
  const headers = new Headers({
    'Content-Type': 'application/json',
    Accept: 'text/event-stream',
  });

  const token = getAccessToken();
  if (token) {
    headers.set('Authorization', `Bearer ${token}`);
  }

  let response;

  try {
    response = await fetch(`${API_BASE_URL}${D_API_PATH}`, {
      method: 'POST',
      headers,
      body: JSON.stringify({ conversation_id: conversationId, user_input: userInput }),
      signal,
    });
  } catch (error) {
    if (error.name === 'AbortError') {
      throw error;
    }

    throw new ApiError({
      message: '백엔드 서버에 연결할 수 없습니다. 서버 실행 상태를 확인해 주세요.',
      code: 'NETWORK_ERROR',
      retryable: true,
      payload: error,
    });
  }

  if (response.status === 401 && !retried) {
    const newToken = await refreshAccessToken();
    if (newToken) {
      return openDStream({ conversationId, userInput, signal, retried: true });
    }
  }

  if (!response.ok) {
    // D파트는 main.py의 오류 envelope 대상이 아니라 FastAPI 기본 바디({detail})가 온다.
    const payload = await response.json().catch(() => null);
    const detail = payload?.detail;

    throw new ApiError({
      message:
        (typeof detail === 'string' ? detail : detail?.message) ||
        '상담 답변을 불러오지 못했습니다.',
      status: response.status,
      code: `HTTP_${response.status}`,
      retryable: response.status >= 500,
      payload,
    });
  }

  return response;
}

// 백엔드는 `data: {json}\n\n` 한 줄짜리 data 필드만 내보낸다(event: 필드 없음).
function parseEventBlock(block) {
  const data = block
    .split('\n')
    .filter((line) => line.startsWith('data:'))
    .map((line) => line.slice('data:'.length).trim())
    .join('');

  if (!data) {
    return null;
  }

  try {
    return JSON.parse(data);
  } catch {
    return null;
  }
}

export async function streamDChat({ conversationId, userInput, signal, onEvent }) {
  const response = await openDStream({ conversationId, userInput, signal });
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  for (;;) {
    const { value, done } = await reader.read();

    if (done) {
      break;
    }

    buffer += decoder.decode(value, { stream: true });

    let boundary = buffer.indexOf('\n\n');
    while (boundary !== -1) {
      const event = parseEventBlock(buffer.slice(0, boundary));
      buffer = buffer.slice(boundary + 2);

      if (event) {
        onEvent(event);
      }

      boundary = buffer.indexOf('\n\n');
    }
  }
}

export function createEmptyDAnswer() {
  return { status: 'loading', citations: [], text: '', errorMessage: '' };
}

// 스트림 이벤트를 화면 상태로 접는다. done/error는 배타적 종료 이벤트다.
export function reduceDAnswer(answer, event) {
  switch (event.type) {
    case 'loading':
      return { ...answer, status: 'loading' };
    case 'meta':
      return { ...answer, citations: event.data?.citations ?? [] };
    case 'token':
      return { ...answer, status: 'streaming', text: answer.text + (event.data ?? '') };
    case 'done':
      return { ...answer, status: 'done' };
    case 'error':
      return {
        ...answer,
        status: 'error',
        errorMessage:
          typeof event.data === 'string'
            ? event.data
            : '일시적인 오류로 응답을 생성하지 못했습니다.',
      };
    default:
      return answer;
  }
}
