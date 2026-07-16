import { motion } from 'framer-motion';
import { useState } from 'react';
import { FiAlertTriangle, FiLoader, FiLock, FiLogIn, FiUser } from 'react-icons/fi';
import { Link, useLocation, useNavigate } from 'react-router';

import AuthField from '../../components/auth/AuthField/AuthField.jsx';
import { ROUTES } from '../../constants/routes.js';
import { useAuth } from '../../contexts/AuthContext.jsx';
import styles from './LoginPage.module.css';

function LoginPage() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();

  const [form, setForm] = useState({ userId: '', password: '' });
  const [error, setError] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);

  const handleChange = (event) => {
    const { name, value } = event.target;
    setForm((current) => ({ ...current, [name]: value }));
    setError('');
  };

  const handleSubmit = async (event) => {
    event.preventDefault();
    if (isSubmitting) return;

    setError('');
    setIsSubmitting(true);
    try {
      await login({ username: form.userId, password: form.password });
      const redirectTo = location.state?.from?.pathname ?? ROUTES.LANDING;
      navigate(redirectTo, { replace: true });
    } catch (submitError) {
      setError(submitError?.message ?? '로그인에 실패했습니다. 잠시 후 다시 시도해 주세요.');
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <motion.section
      className={styles.formSection}
      initial={{ opacity: 0, y: 18 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35, ease: 'easeOut' }}
    >
      <h1 className={styles.title}>로그인</h1>

      <form className={styles.form} onSubmit={handleSubmit}>
        <AuthField
          id="login-user-id"
          label="아이디"
          name="userId"
          value={form.userId}
          onChange={handleChange}
          placeholder="아이디를 입력해 주세요."
          autoComplete="username"
          Icon={FiUser}
        />
        <AuthField
          id="login-password"
          label="비밀번호"
          type="password"
          name="password"
          value={form.password}
          onChange={handleChange}
          placeholder="비밀번호를 입력해 주세요."
          autoComplete="current-password"
          Icon={FiLock}
        />

        {error && (
          <motion.p
            className={styles.error}
            initial={{ opacity: 0, y: -4 }}
            animate={{ opacity: 1, y: 0 }}
          >
            <FiAlertTriangle aria-hidden="true" />
            <span>{error}</span>
          </motion.p>
        )}

        <motion.button
          className={styles.submitButton}
          type="submit"
          disabled={isSubmitting}
          whileHover={isSubmitting ? undefined : { y: -2, scale: 1.01 }}
          whileTap={isSubmitting ? undefined : { scale: 0.98 }}
        >
          {isSubmitting ? (
            <FiLoader className={styles.spinner} aria-hidden="true" />
          ) : (
            <FiLogIn aria-hidden="true" />
          )}
          <span>{isSubmitting ? '로그인 중…' : '로그인'}</span>
        </motion.button>
      </form>

      <p className={styles.switchText}>
        아직 계정이 없나요?
        <Link to={ROUTES.SIGNUP}>회원가입</Link>
      </p>
    </motion.section>
  );
}

export default LoginPage;
