import { motion } from 'framer-motion';
import {
  FiAlertTriangle,
  FiArrowRight,
  FiCheckCircle,
  FiClipboard,
  FiEdit3,
  FiLogIn,
  FiMessageCircle,
} from 'react-icons/fi';
import { Link } from 'react-router';

import { CHAT_ROUTES, ROUTES } from '../../constants/routes.js';
import styles from './LandingPage.module.css';

const descriptions = {
  'before-contract': '임대인, 대리 권한, 등기부와 계약금 계좌를 확인합니다.',
  'during-contract': '계약 금액, 특약, 서명과 대금 지급 조건을 점검합니다.',
  'after-contract': '전입신고, 확정일자와 임대차 신고 순서를 확인합니다.',
  'jeonse-fraud': '권리관계, 시세와 보증 가입 위험 신호를 확인합니다.',
};

const categoryIcons = {
  'before-contract': FiClipboard,
  'during-contract': FiEdit3,
  'after-contract': FiCheckCircle,
  'jeonse-fraud': FiAlertTriangle,
};

function LandingPage() {
  return (
    <main className={styles.page}>
      <section className={styles.hero}>
        <motion.div
          className={styles.heroInner}
          initial={{ opacity: 0, y: 24 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5, ease: 'easeOut' }}
        >
          <span className={styles.badge}>
            <FiMessageCircle aria-hidden="true" />
            계약 단계별 AI 상담
          </span>
          <h1 className={styles.title}>
            주택 임대차 계약을
            <br />더 안전하게 확인하세요.
          </h1>
          <p className={styles.description}>
            계약 전부터 계약 후까지 현재 상황에 필요한 확인 사항과 다음 행동을 한 화면에서 안내합니다.
          </p>
          <div className={styles.actions}>
            <motion.div whileHover={{ y: -3, scale: 1.02 }} whileTap={{ scale: 0.98 }}>
              <Link className={styles.primaryButton} to={ROUTES.CHAT_BEFORE_CONTRACT}>
                <FiMessageCircle aria-hidden="true" />
                상담 시작
              </Link>
            </motion.div>
            <motion.div whileHover={{ y: -3, scale: 1.02 }} whileTap={{ scale: 0.98 }}>
              <Link className={styles.secondaryButton} to={ROUTES.LOGIN}>
                <FiLogIn aria-hidden="true" />
                로그인
              </Link>
            </motion.div>
          </div>
        </motion.div>
      </section>

      <section className={styles.categorySection}>
        <div className={styles.sectionInner}>
          <div className={styles.sectionHeading}>
            <span>4가지 상담 흐름</span>
            <h2>현재 계약 단계에 맞춰 바로 시작하세요.</h2>
          </div>

          <div className={styles.categoryGrid}>
            {CHAT_ROUTES.map((route, index) => {
              const Icon = categoryIcons[route.key];

              return (
                <motion.div
                  key={route.key}
                  initial={{ opacity: 0, y: 18 }}
                  whileInView={{ opacity: 1, y: 0 }}
                  viewport={{ once: true, amount: 0.25 }}
                  transition={{ delay: index * 0.08 }}
                  whileHover={{ y: -6 }}
                >
                  <Link className={styles.categoryCard} to={route.path}>
                    <div className={styles.cardTop}>
                      <span className={styles.cardNumber}>{String(index + 1).padStart(2, '0')}</span>
                      <span className={styles.cardIcon}>
                        <Icon aria-hidden="true" />
                      </span>
                    </div>
                    <h3>{route.label}</h3>
                    <p>{descriptions[route.key]}</p>
                    <span className={styles.cardLink}>
                      상담 열기
                      <FiArrowRight aria-hidden="true" />
                    </span>
                  </Link>
                </motion.div>
              );
            })}
          </div>
        </div>
      </section>
    </main>
  );
}

export default LandingPage;
