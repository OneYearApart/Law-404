import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react';

import * as authApi from '../api/auth/authApi.js';
import { registerTokenRefresher } from '../api/common/apiClient.js';
import { setAccessToken } from '../api/common/authToken.js';

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [status, setStatus] = useState('loading'); // 'loading' | 'authenticated' | 'anonymous'

  // 진행 중인 refresh를 공유해 단일-flight로 만든다.
  // - refresh rotation은 매 호출마다 쿠키를 폐기하므로, 동시 다발 refresh는 서로를 무효화한다.
  // - StrictMode 이중 마운트, 그리고 여러 보호 요청의 동시 401 재시도가 대표적인 중복 유발 지점.
  const refreshInFlight = useRef(null);

  const refresh = useCallback(async () => {
    if (!refreshInFlight.current) {
      refreshInFlight.current = (async () => {
        try {
          const { access_token: accessToken } = await authApi.refreshSession();
          setAccessToken(accessToken);
          return accessToken;
        } catch {
          setAccessToken(null);
          return null;
        } finally {
          refreshInFlight.current = null;
        }
      })();
    }
    return refreshInFlight.current;
  }, []);

  // apiClient가 401을 만났을 때 호출할 갱신 함수를 등록한다.
  useEffect(() => {
    registerTokenRefresher(refresh);
  }, [refresh]);

  // 앱 로드 시 쿠키로 세션 복원(silent refresh). didInit ref로 StrictMode 이중 실행을 막는다.
  const didInit = useRef(false);
  useEffect(() => {
    if (didInit.current) return;
    didInit.current = true;

    (async () => {
      const token = await refresh();
      if (!token) {
        setStatus('anonymous');
        return;
      }
      try {
        setUser(await authApi.getMe());
        setStatus('authenticated');
      } catch {
        setAccessToken(null);
        setStatus('anonymous');
      }
    })();
  }, [refresh]);

  const login = useCallback(async ({ username, password }) => {
    const { access_token: accessToken } = await authApi.login({ username, password });
    setAccessToken(accessToken);
    const me = await authApi.getMe();
    setUser(me);
    setStatus('authenticated');
    return me;
  }, []);

  const signup = useCallback(
    async ({ username, nickname, password }) => {
      await authApi.signup({ username, nickname, password });
      // 가입 직후 그대로 로그인까지 이어준다.
      return login({ username, password });
    },
    [login],
  );

  const logout = useCallback(async () => {
    try {
      await authApi.logout();
    } catch {
      // 서버 폐기에 실패해도 클라이언트 세션은 비운다.
    }
    setAccessToken(null);
    setUser(null);
    setStatus('anonymous');
  }, []);

  const value = useMemo(
    () => ({ user, status, login, signup, logout }),
    [user, status, login, signup, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

// eslint-disable-next-line react-refresh/only-export-components -- Provider와 훅을 한 파일에서 함께 노출 (HMR 전용 경고)
export function useAuth() {
  const ctx = useContext(AuthContext);
  if (ctx == null) {
    throw new Error('useAuth는 AuthProvider 안에서만 사용할 수 있습니다.');
  }
  return ctx;
}
