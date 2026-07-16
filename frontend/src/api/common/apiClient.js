const configuredBaseUrl = import.meta.env.VITE_API_BASE_URL?.trim();
export const API_BASE_URL = (configuredBaseUrl || '/api').replace(/\/$/, '');

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

export async function apiRequest(
  path,
  {
    method = 'GET',
    body,
    headers = {},
    signal,
  } = {},
) {
  const requestHeaders = new Headers(headers);
  requestHeaders.set('Accept', 'application/json');

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

  const payload = await parseResponse(response);

  if (!response.ok) {
    throw toApiError(response, payload);
  }

  return payload;
}
