import styles from './AppFooter.module.css';

function AppFooter() {
  return (
    <footer className={styles.footer}>
      <div className={styles.inner}>
        <p className={styles.brand}>Law404</p>
        <p className={styles.description}>주택 임대차 계약의 확인 사항과 다음 행동을 안내합니다.</p>
        <p className={styles.notice}>현재 화면은 프론트엔드 UI 구조이며 상담 API는 다음 단계에서 연결합니다.</p>
      </div>
    </footer>
  );
}

export default AppFooter;
