import { motion } from 'framer-motion';
import {
  FiAlertTriangle,
  FiCheckCircle,
  FiClipboard,
  FiEdit3,
  FiLogIn,
  FiUserPlus,
} from 'react-icons/fi';
import { NavLink } from 'react-router';

import { CHAT_ROUTES, ROUTES } from '../../../constants/routes.js';
import { useAuth } from '../../../contexts/AuthContext.jsx';
import BrandLogo from '../BrandLogo/BrandLogo.jsx';
import styles from './AppHeader.module.css';

const CHAT_ICONS = {
  'before-contract': FiClipboard,
  'during-contract': FiEdit3,
  'after-contract': FiCheckCircle,
  'jeonse-fraud': FiAlertTriangle,
};

function navClassName({ isActive }) {
  return `${styles.navLink} ${isActive ? styles.active : ''}`;
}

function AppHeader({ variant = 'public' }) {
  const isChat = variant === 'chat';
  const { status } = useAuth();
  const showAuthActions = !isChat && status === 'anonymous';

  const authActions = showAuthActions ? (
    <>
      <motion.div whileHover={{ y: -2 }} whileTap={{ scale: 0.97 }}>
        <NavLink className={navClassName} to={ROUTES.LOGIN}>
          <FiLogIn aria-hidden="true" />
          <span>로그인</span>
        </NavLink>
      </motion.div>
      <motion.div whileHover={{ y: -2 }} whileTap={{ scale: 0.97 }}>
        <NavLink className={`${styles.navLink} ${styles.signupLink}`} to={ROUTES.SIGNUP}>
          <FiUserPlus aria-hidden="true" />
          <span>회원가입</span>
        </NavLink>
      </motion.div>
    </>
  ) : null;

  return (
    <motion.header
      className={styles.header}
      initial={{ y: -18, opacity: 0 }}
      animate={{ y: 0, opacity: 1 }}
      transition={{ duration: 0.35, ease: 'easeOut' }}
    >
      <div className={styles.inner}>
        <BrandLogo />

        <nav className={styles.navigation} aria-label={isChat ? '상담 카테고리' : '회원 메뉴'}>
          {isChat &&
            CHAT_ROUTES.map((route) => {
              const Icon = CHAT_ICONS[route.key];

              return (
                <motion.div key={route.key} whileHover={{ y: -2 }} whileTap={{ scale: 0.97 }}>
                  <NavLink className={navClassName} to={route.path}>
                    <Icon aria-hidden="true" />
                    <span>{route.label}</span>
                  </NavLink>
                </motion.div>
              );
            })}

          {authActions}
        </nav>
      </div>
    </motion.header>
  );
}

export default AppHeader;
