import { motion } from 'framer-motion';
import { useState } from 'react';
import { FiAlertTriangle, FiLoader, FiLock, FiSmile, FiUser, FiUserPlus } from 'react-icons/fi';
import { Link, useNavigate } from 'react-router';

import AuthField from '../../components/auth/AuthField/AuthField.jsx';
import { ROUTES } from '../../constants/routes.js';
import { useAuth } from '../../contexts/AuthContext.jsx';
import styles from './SignupPage.module.css';

function SignupPage() {
  const { signup } = useAuth();
  const navigate = useNavigate();

  const [form, setForm] = useState({ nickname: '', userId: '', password: '' });
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
      await signup({
        username: form.userId,
        nickname: form.nickname,
        password: form.password,
      });
      // 가입 직후 자동 로그인되므로 곧바로 서비스로 진입한다.
      navigate(ROUTES.LANDING, { replace: true });
    } catch (submitError) {
      setError(submitError?.message ?? '회원가입에 실패했습니다. 잠시 후 다시 시도해 주세요.');
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
      <h1 className={styles.title}>회원가입</h1>

      <form className={styles.form} onSubmit={handleSubmit}>
        <AuthField
          id="signup-nickname"
          label="닉네임"
          name="nickname"
          value={form.nickname}
          onChange={handleChange}
          placeholder="사용할 닉네임을 입력해 주세요."
          autoComplete="nickname"
          Icon={FiSmile}
        />
        <AuthField
          id="signup-user-id"
          label="아이디"
          name="userId"
          value={form.userId}
          onChange={handleChange}
          placeholder="사용할 아이디를 입력해 주세요."
          autoComplete="username"
          Icon={FiUser}
        />
        <AuthField
          id="signup-password"
          label="비밀번호"
          type="password"
          name="password"
          value={form.password}
          onChange={handleChange}
          placeholder="비밀번호를 입력해 주세요."
          autoComplete="new-password"
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
            <FiUserPlus aria-hidden="true" />
          )}
          <span>{isSubmitting ? '가입 중…' : '회원가입'}</span>
        </motion.button>
      </form>

      <p className={styles.switchText}>
        이미 계정이 있나요?
        <Link to={ROUTES.LOGIN}>로그인</Link>
      </p>
    </motion.section>
  );
}

export default SignupPage;
