import { Navigate, Outlet, useLocation } from 'react-router';

import { ROUTES } from '../../constants/routes.js';
import { useAuth } from '../../contexts/AuthContext.jsx';

function ProtectedRoute() {
  const { status } = useAuth();
  const location = useLocation();

  if (status === 'loading') {
    // 세션 복원(silent refresh)이 끝나기 전엔 판단을 보류한다.
    return null;
  }

  if (status === 'anonymous') {
    // 로그인 후 원래 가려던 곳으로 되돌아올 수 있게 from을 넘긴다.
    return <Navigate to={ROUTES.LOGIN} state={{ from: location }} replace />;
  }

  return <Outlet />;
}

export default ProtectedRoute;
