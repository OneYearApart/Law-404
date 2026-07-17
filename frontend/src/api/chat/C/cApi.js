import { getAccessToken } from '../../common/authToken.js';
import { API_BASE_URL, ApiError, apiRequest } from '../../common/apiClient.js';

/**
 * C파트(계약 후 - 보증금 반환·경매·배당) API 클라이언트.
 */

const C_BASE_PATH = '/c-part';

// ════════════════════════════════════════════════════════════════════════════
// 【대화 관리】
// ════════════════════════════════════════════════════════════════════════════

/**
 * 새 C파트 대화방을 만들고 conversation_id를 돌려준다.
 */
export async function createCConversation() {
  const payload = await apiRequest(`${C_BASE_PATH}/conversations`, {
    method: 'POST',
  });
  return payload; // { conversation_id }
}

// ════════════════════════════════════════════════════════════════════════════
// 【상담 - SSE 스트리밍】
// ════════════════════════════════════════════════════════════════════════════

function createSSEParser() {
  let buffer = '';

  return {
    /** 새 chunk를 넣으면, 그 안에서 완성된 이벤트들의 배열을 돌려준다. */
    push(chunk) {
      buffer += chunk;
      const events = [];

      let boundary;
      // \n\n 을 경계로 하나씩 떼어낸다. (\r\n\r\n 도 방어)
      while (
        (boundary = buffer.indexOf('\n\n')) !== -1 ||
        (boundary = buffer.indexOf('\r\n\r\n')) !== -1
      ) {
        const rawEvent = buffer.slice(0, boundary);
        const sepLength = buffer.startsWith('\r\n\r\n', boundary) ? 4 : 2;
        buffer = buffer.slice(boundary + sepLength);

        const parsed = parseSSEBlock(rawEvent);
        if (parsed) {
          events.push(parsed);
        }
      }
      return events;
    },
  };
}

/** "event: x\ndata: {...}" 한 블록을 {event, data}로 파싱. 주석(: ping)은 무시. */
function parseSSEBlock(rawEvent) {
  const lines = rawEvent.split(/\r?\n/);
  let eventName = 'message';
  const dataLines = [];

  for (const line of lines) {
    if (!line || line.startsWith(':')) {
      // 빈 줄이거나 주석(keep-alive ping) → 무시
      continue;
    }
    if (line.startsWith('event:')) {
      eventName = line.slice(6).trim();
    } else if (line.startsWith('data:')) {
      dataLines.push(line.slice(5).trim());
    }
  }

  if (dataLines.length === 0) {
    return null;
  }

  const dataStr = dataLines.join('\n');
  try {
    return { event: eventName, data: JSON.parse(dataStr) };
  } catch {
    // JSON이 아니면 문자열 그대로
    return { event: eventName, data: dataStr };
  }
}

/**
 * 상담 질문을 보내고, 응답을 스트리밍으로 받는다.
 *
 * @param {object}   args
 * @param {string}   args.question         사용자 질문
 * @param {number}   args.conversationId   createCConversation으로 받은 id
 * @param {AbortSignal} [args.signal]       중단용 (사용자가 취소/이탈 시)
 * @param {object}   handlers               이벤트별 콜백
 * @param {(type:string)=>void}      [handlers.onClassified]  'definition'|'off_topic'|'consultation'
 * @param {(sections:string[])=>void}[handlers.onOutline]     섹션 자리 순서 힌트
 * @param {(section:object)=>void}   [handlers.onSection]     {key,title,content,citations}
 * @param {(faq:string[])=>void}     [handlers.onFaq]         FAQ 목록
 * @param {(text:string)=>void}      [handlers.onMessage]     definition/off_topic 단문
 * @param {(meta:object)=>void}      [handlers.onMeta]        {confidence_score,...}
 * @param {(err:Error)=>void}        [handlers.onError]
 * @param {(info:object)=>void}      [handlers.onDone]        {conversation_id}
 */
export async function streamCAsk(
  { question, conversationId, signal },
  handlers = {},
) {
  const token = getAccessToken();
  const url = `${API_BASE_URL}${C_BASE_PATH}/ask/stream`;

  let response;
  try {
    response = await fetch(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Accept: 'text/event-stream',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify({ question, conversation_id: conversationId }),
      signal,
    });
  } catch (error) {
    if (error.name === 'AbortError') throw error;
    throw new ApiError({
      message: '백엔드 서버에 연결할 수 없습니다. 서버 실행 상태를 확인해 주세요.',
      code: 'NETWORK_ERROR',
      retryable: true,
      payload: error,
    });
  }

  if (!response.ok) {
    // 스트림 시작 전 에러(401, 404 등)는 일반 JSON 에러로 온다.
    let payload = null;
    try {
      payload = await response.json();
    } catch {
      /* 무시 */
    }
    const message =
      payload?.detail?.message ||
      (typeof payload?.detail === 'string' ? payload.detail : null) ||
      '상담 요청을 처리하지 못했습니다.';
    throw new ApiError({ message, status: response.status, payload });
  }

  if (!response.body) {
    throw new ApiError({ message: '스트리밍을 지원하지 않는 응답입니다.', code: 'NO_STREAM' });
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder('utf-8');
  const parser = createSSEParser();

  const dispatch = ({ event, data }) => {
    switch (event) {
      case 'classified':
        handlers.onClassified?.(data.response_type);
        break;
      case 'outline':
        handlers.onOutline?.(data.sections || []);
        break;
      case 'section':
        handlers.onSection?.(data);
        break;
      case 'faq':
        handlers.onFaq?.(data.follow_up_questions || []);
        break;
      case 'message':
        handlers.onMessage?.(data.text || '');
        break;
      case 'meta':
        handlers.onMeta?.(data);
        break;
      case 'error':
        handlers.onError?.(new ApiError({ message: data.message || '오류가 발생했습니다.' }));
        break;
      case 'done':
        handlers.onDone?.(data);
        break;
      default:
        break;
    }
  };

  try {
    // eslint-disable-next-line no-constant-condition
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;

      const text = decoder.decode(value, { stream: true });
      for (const evt of parser.push(text)) {
        dispatch(evt);
      }
    }
  } catch (error) {
    if (error.name === 'AbortError') {
      // 사용자가 의도적으로 중단 → 조용히 종료
      return;
    }
    handlers.onError?.(error);
  } finally {
    reader.releaseLock?.();
  }
}

// ════════════════════════════════════════════════════════════════════════════
// 【문서 생성 - 텍스트】
// ════════════════════════════════════════════════════════════════════════════

/**
 * 내용증명 생성 대화. 한 번 호출 = 한 번의 되묻기 또는 완성.
 */
export async function sendCDocumentMessage({ userMessage, conversationId }) {
  const payload = await apiRequest(`${C_BASE_PATH}/document`, {
    method: 'POST',
    body: {
      user_message: userMessage,
      conversation_id: conversationId,
    },
  });
  return payload;
}

// ════════════════════════════════════════════════════════════════════════════
// 【문서 생성 - 이미지 OCR (Clova)】
// ════════════════════════════════════════════════════════════════════════════

/**
 * File 객체를 base64 문자열로 변환. (data: 접두어 제거된 순수 base64)
 */
export function fileToBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const result = String(reader.result || '');
      const comma = result.indexOf(',');
      resolve(comma >= 0 ? result.slice(comma + 1) : result);
    };
    reader.onerror = () => reject(new Error('이미지를 읽지 못했습니다.'));
    reader.readAsDataURL(file);
  });
}

/** 파일명 확장자로 image_format 추론 (jpg/png/pdf). 기본 jpg. */
export function guessImageFormat(fileName = '') {
  const ext = fileName.split('.').pop()?.toLowerCase();
  if (ext === 'png') return 'png';
  if (ext === 'pdf') return 'pdf';
  if (ext === 'jpeg' || ext === 'jpg') return 'jpg';
  return 'jpg';
}

/**
 * 계약서 이미지에서 내용증명 정보를 자동 추출한다.
 * 못 찾은 항목은 이후 sendCDocumentMessage로 되묻게 된다.
 *
 * @param {File}   file            사용자가 올린 이미지/PDF
 * @param {number} conversationId
 */
export async function sendCDocumentImage({ file, conversationId }) {
  const imageBase64 = await fileToBase64(file);
  const imageFormat = guessImageFormat(file.name);

  const payload = await apiRequest(`${C_BASE_PATH}/document/ocr`, {
    method: 'POST',
    body: {
      image_base64: imageBase64,
      image_format: imageFormat,
      conversation_id: conversationId,
    },
  });
  return payload; // { status, extracted_from_image, missing_labels, progress, next_question, document, conversation_id }
}

// ════════════════════════════════════════════════════════════════════════════
// 【비용 조회】GPT 없음, 즉시 응답
// ════════════════════════════════════════════════════════════════════════════

/**
 * 절차별 수수료 + 지역 기준. deposit을 주면 경로별 계산까지 돌려준다.
 * @param {number} [deposit] 보증금 액수(원). 주면 calculations 포함.
 */
export async function getCCosts(deposit) {
  const query =
    deposit && deposit > 0 ? `?${new URLSearchParams({ deposit: String(deposit) })}` : '';
  const payload = await apiRequest(`${C_BASE_PATH}/costs${query}`);
  return payload;
}

// ════════════════════════════════════════════════════════════════════════════
// 【헬퍼】상담 응답 섹션 순서/라벨 (프론트 표시용 기본값)
// ════════════════════════════════════════════════════════════════════════════

export const C_SECTION_ORDER = [
  'situation',
  'legal_basis',
  'precedents',
  'action_steps',
  'expected_cost',
  'anticipated_disputes',
];

export const C_SECTION_LABELS = {
  situation: '상황 진단',
  legal_basis: '관련 법 조문',
  precedents: '관련 판례',
  action_steps: '행동 절차',
  expected_cost: '예상 비용',
  anticipated_disputes: '임대인 반박 & 대응',
};