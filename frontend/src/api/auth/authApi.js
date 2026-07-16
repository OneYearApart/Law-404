import { apiRequest } from '../common/apiClient.js';

const AUTH_BASE_PATH = '/auth';

// refresh token은 httpOnly 쿠키로 오간다 → credentials: 'include'로 쿠키 set/전송을 허용해야 한다.
const WITH_COOKIE = { credentials: 'include' };

export async function signup({ username, nickname, password }) {
  return apiRequest(`${AUTH_BASE_PATH}/signup`, {
    method: 'POST',
    body: { username, nickname, password },
    ...WITH_COOKIE,
  });
}

export async function login({ username, password }) {
  return apiRequest(`${AUTH_BASE_PATH}/login`, {
    method: 'POST',
    body: { username, password },
    ...WITH_COOKIE,
  });
}

export async function logout() {
  return apiRequest(`${AUTH_BASE_PATH}/logout`, {
    method: 'POST',
    ...WITH_COOKIE,
  });
}

export async function refreshSession() {
  return apiRequest(`${AUTH_BASE_PATH}/refresh`, {
    method: 'POST',
    ...WITH_COOKIE,
  });
}

export async function getMe() {
  return apiRequest(`${AUTH_BASE_PATH}/me`);
}
