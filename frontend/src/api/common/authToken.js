// access token은 XSS 노출을 줄이기 위해 localStorage가 아니라 JS 메모리에만 둔다.
// (refresh token은 백엔드가 httpOnly 쿠키로 관리하므로, 새로고침 시 /auth/refresh로 재발급받는다.)
// apiClient(요청에 Bearer 첨부)와 AuthContext(로그인/갱신 시 set) 사이의 순환 import를 피하는 얇은 중재층.
let accessToken = null;

export function getAccessToken() {
  return accessToken;
}

export function setAccessToken(token) {
  accessToken = token ?? null;
}
