import { API_BASE_URL, ApiError, refreshAccessToken } from '../../common/apiClient.js';
import { getAccessToken } from '../../common/authToken.js';
import { createConversation } from '../../common/conversationsApi.js';

export const D_API_PATH = '/chat/d/';

// D파트는 대화방을 만들어주지 않는다. conversation_id는 반드시 먼저 발급받아 보내야 한다.
export async function createDConversation() {
  return createConversation('d');
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
  return {
    status: 'loading',
    citations: [],
    judgment: null,
    text: '',
    appendix: '',
    disclaimer: '',
    terms: [],
    answerKind: null,
    errorMessage: '',
  };
}

// 본문 머리글은 response.md가 강제하는 계약이다. 여기 바꾸면 프롬프트도 같이 바꿔야 한다.
const BODY_SECTION_MARKER = /^###\s*(해설|상황적용)\s*$/gm;

/**
 * LLM 본문을 머리글 기준으로 섹션 배열로 쪼갠다.
 *
 * 대응·면책과 달리 본문은 모델이 그 자리에서 쓰는 글이라 형식이 보장되지 않는다. 머리글이
 * 없거나 깨지면 전체를 제목 없는 단일 섹션으로 반환한다 — 렌더가 실패해 답이 안 보이는 것보다
 * 스타일이 덜 예쁜 게 낫다. 스트리밍 중 부분 텍스트에도 그대로 동작한다(마지막 섹션이 자라는 중).
 */
export function splitDBody(text) {
  if (!text) {
    return [];
  }

  const sections = [];
  let lastIndex = 0;
  let lastTitle = null;

  BODY_SECTION_MARKER.lastIndex = 0;
  let match = BODY_SECTION_MARKER.exec(text);
  while (match) {
    if (lastTitle !== null) {
      sections.push({ title: lastTitle, body: text.slice(lastIndex, match.index).trim() });
    }
    lastTitle = match[1];
    lastIndex = match.index + match[0].length;
    match = BODY_SECTION_MARKER.exec(text);
  }

  if (lastTitle === null) {
    return [{ title: null, body: text.trim() }];   // 머리글 없음 → 통째로 한 블록(폴백)
  }
  sections.push({ title: lastTitle, body: text.slice(lastIndex).trim() });
  return sections.filter((section) => section.body);
}

// 스트림 이벤트를 화면 상태로 접는다. done/error는 배타적 종료 이벤트다.
export function reduceDAnswer(answer, event) {
  switch (event.type) {
    case 'loading':
      return { ...answer, status: 'loading' };
    // META는 여러 번 온다(본문 앞: 근거·판정 / 본문 뒤: 대응·면책)는 점이 중요하다.
    // 각 키는 선택적이라 없는 키를 기본값으로 덮어쓰면 앞선 META가 실어온 값이 날아간다.
    // 빠진 키는 반드시 기존 값을 유지할 것.
    case 'meta':
      return {
        ...answer,
        citations: event.data?.citations ?? answer.citations,
        judgment: event.data?.judgment ?? answer.judgment,
        appendix: event.data?.appendix ?? answer.appendix,
        disclaimer: event.data?.disclaimer ?? answer.disclaimer,
        terms: event.data?.terms ?? answer.terms,
        answerKind: event.data?.answer_kind ?? answer.answerKind,
      };
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
