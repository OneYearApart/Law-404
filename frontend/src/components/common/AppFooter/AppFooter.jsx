import { FiShield } from 'react-icons/fi';

import BrandLogo from '../BrandLogo/BrandLogo.jsx';
import styles from './AppFooter.module.css';

function AppFooter() {
  return (
    <footer className={styles.footer}>
      <div className={styles.inner}>
        <div className={styles.brandArea}>
          <BrandLogo />
          <p>주택 임대차 계약의 확인 사항과 다음 행동을 단계별로 안내합니다.</p>
        </div>

        <nav className={styles.links} aria-label="하단 메뉴">
          <a href="#consultation-fields">상담 기능</a>
          <a href="#questions">대표 질문</a>
          <a href="#answer-method">답변 구성</a>
        </nav>

        <div className={styles.noticeArea}>
          <FiShield aria-hidden="true" />
          <p>
            <span>중요한 결정 전에는 공식 기관이나 전문가의 확인이 필요합니다.</span>
            <span>Law404는 사용자가 확인할 사실과 다음 행동을 놓치지 않도록 돕는 안내 서비스입니다.</span>
          </p>
        </div>
      </div>

      <div className={styles.bottom}>
        <span>© 2026 Law404. All rights reserved.</span>
        <span>주택 임대차 AI 상담 서비스</span>
      </div>
    </footer>
  );
}

export default AppFooter;
