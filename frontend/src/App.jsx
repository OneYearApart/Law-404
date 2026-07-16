import { BrowserRouter, Route, Routes } from 'react-router';

import ProtectedRoute from './components/auth/ProtectedRoute.jsx';
import { ROUTES } from './constants/routes.js';
import { AuthProvider } from './contexts/AuthContext.jsx';
import AuthLayout from './layouts/AuthLayout/AuthLayout.jsx';
import ChatLayout from './layouts/ChatLayout/ChatLayout.jsx';
import PublicLayout from './layouts/PublicLayout/PublicLayout.jsx';
import ChatbotPage from './pages/ChatbotPage/ChatbotPage.jsx';
import LandingPage from './pages/LandingPage/LandingPage.jsx';
import LoginPage from './pages/LoginPage/LoginPage.jsx';
import NotFoundPage from './pages/NotFoundPage/NotFoundPage.jsx';
import SignupPage from './pages/SignupPage/SignupPage.jsx';

function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <Routes>
          <Route element={<PublicLayout />}>
            <Route path={ROUTES.LANDING} element={<LandingPage />} />
            <Route path="*" element={<NotFoundPage />} />
          </Route>

          <Route element={<AuthLayout />}>
            <Route path={ROUTES.LOGIN} element={<LoginPage />} />
            <Route path={ROUTES.SIGNUP} element={<SignupPage />} />
          </Route>

          <Route element={<ProtectedRoute />}>
            <Route element={<ChatLayout />}>
              <Route
                path={ROUTES.CHAT_BEFORE_CONTRACT}
                element={<ChatbotPage consultationType="before-contract" />}
              />
              <Route
                path={ROUTES.CHAT_DURING_CONTRACT}
                element={<ChatbotPage consultationType="during-contract" />}
              />
              <Route
                path={ROUTES.CHAT_AFTER_CONTRACT}
                element={<ChatbotPage consultationType="after-contract" />}
              />
              <Route
                path={ROUTES.CHAT_JEONSE_FRAUD}
                element={<ChatbotPage consultationType="jeonse-fraud" />}
              />
            </Route>
          </Route>
        </Routes>
      </AuthProvider>
    </BrowserRouter>
  );
}

export default App;
