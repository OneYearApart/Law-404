import { motion } from 'framer-motion';
import { useState } from 'react';
import { FiInfo, FiLock, FiLogIn, FiUser } from 'react-icons/fi';
import { Link } from 'react-router';

import AuthField from '../../components/auth/AuthField/AuthField.jsx';
import { ROUTES } from '../../constants/routes.js';
import styles from './LoginPage.module.css';

function LoginPage() {
  const [form, setForm] = useState({ userId: '', password: '' });
  const [notice, setNotice] = useState('');

  const handleChange = (event) => {
    const { name, value } = event.target;
    setForm((current) => ({ ...current, [name]: value }));
    setNotice('');
  };

  const handleSubmit = (event) => {
    event.preventDefault();
    setNotice('로그인 API는 팀 인증 기능이 연결된 뒤 적용됩니다. 현재 A 상담은 로그인 없이 테스트할 수 있습니다.');
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

        {notice && (
          <motion.p
            className={styles.success}
            initial={{ opacity: 0, y: -4 }}
            animate={{ opacity: 1, y: 0 }}
          >
            <FiInfo aria-hidden="true" />
            <span>{notice}</span>
          </motion.p>
        )}

        <motion.button
          className={styles.submitButton}
          type="submit"
          whileHover={{ y: -2, scale: 1.01 }}
          whileTap={{ scale: 0.98 }}
        >
          <FiLogIn aria-hidden="true" />
          <span>로그인</span>
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
