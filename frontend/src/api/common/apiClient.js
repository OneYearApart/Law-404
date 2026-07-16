import { getAccessToken } from './authToken.js';

const configuredBaseUrl = import.meta.env.VITE_API_BASE_URL?.trim();
export const API_BASE_URL = (configuredBaseUrl || '/api').replace(/\/$/, '');

// AuthContext가 등록하는 토큰 갱신 함수. 반환값은 새 access token(또는 실패 시 null).
// 단일-flight 보장은 등록하는 쪽(AuthContext)에서 책임진다.
let tokenRefresher = null;

export function registerTokenRefresher(refresher) {
  tokenRefresher = refresher;
}

// login/signup/refresh/logout은 쿠키 기반이라 Bearer를 붙이지도, 401 재시도를 하지도 않는다
// (특히 /auth/refresh 재시도는 무한루프가 된다). /auth/me는 Bearer가 필요하므로 제외 대상이 아니다.
function isCookieAuthEndpoint(path) {
  return /^\/?auth\/(login|signup|refresh|logout)\b/.test(path);
}

export class ApiError extends Error {
  constructor({
    message,
    status = 0,
    code = 'API_ERROR',
    retryable = false,
    details = {},
    payload = null,
  }) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
    this.retryable = retryable;
    this.details = details;
    this.payload = payload;
  }
}

function buildUrl(path) {
  if (/^https?:\/\//.test(path)) {
    return path;
  }

  return `${API_BASE_URL}${path.startsWith('/') ? path : `/${path}`}`;
}

async function parseResponse(response) {
  if (response.status === 204) {
    return null;
  }

  const contentType = response.headers.get('content-type') || '';

  if (contentType.includes('application/json')) {
    return response.json();
  }

  const text = await response.text();
  return text || null;
}

function toApiError(response, payload) {
  const errorBody = payload?.error;
  const detail = payload?.detail;
  const detailMessage = typeof detail === 'string' ? detail : detail?.message;

  return new ApiError({
    message:
      errorBody?.message ||
      detailMessage ||
      (typeof payload === 'string' ? payload : null) ||
      '요청을 처리하지 못했습니다.',
    status: response.status,
    code: errorBody?.code || detail?.code || `HTTP_${response.status}`,
    retryable: Boolean(errorBody?.retryable || response.status >= 500),
    details: errorBody?.details || detail?.details || {},
    payload,
  });
}

export async function apiRequest(path, options = {}) {
  const {
    method = 'GET',
    body,
    headers = {},
    signal,
    credentials,
    _retried = false,
  } = options;

  const requestHeaders = new Headers(headers);
  requestHeaders.set('Accept', 'application/json');

  // 로그인된 상태면 보호 요청에 access token을 자동 첨부한다.
  // 쿠키 기반 auth 엔드포인트와, 호출부가 직접 Authorization을 지정한 경우는 건드리지 않는다.
  if (!requestHeaders.has('Authorization') && !isCookieAuthEndpoint(path)) {
    const token = getAccessToken();
    if (token) {
      requestHeaders.set('Authorization', `Bearer ${token}`);
    }
  }

  let requestBody = body;
  const isFormData = body instanceof FormData;

  if (body !== undefined && body !== null && !isFormData && typeof body !== 'string') {
    requestHeaders.set('Content-Type', 'application/json');
    requestBody = JSON.stringify(body);
  }

  let response;

  try {
    response = await fetch(buildUrl(path), {
      method,
      body: requestBody,
      headers: requestHeaders,
      signal,
      ...(credentials ? { credentials } : {}),
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

  // access token 만료 등으로 401을 받으면 refresh로 한 번 갱신한 뒤 원 요청을 1회 재시도한다.
  if (
    response.status === 401 &&
    !_retried &&
    !isCookieAuthEndpoint(path) &&
    tokenRefresher
  ) {
    const newToken = await tokenRefresher();
    if (newToken) {
      return apiRequest(path, { ...options, _retried: true });
    }
  }

  const payload = await parseResponse(response);

  if (!response.ok) {
    throw toApiError(response, payload);
  }

  return payload;
}
