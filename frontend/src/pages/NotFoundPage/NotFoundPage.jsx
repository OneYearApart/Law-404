import { Link } from 'react-router';

import { ROUTES } from '../../constants/routes.js';
import styles from './NotFoundPage.module.css';

function NotFoundPage() {
  return (
    <main className={styles.page}>
      <section className={styles.content}>
        <p className={styles.code}>404</p>
        <h1>페이지를 찾을 수 없습니다.</h1>
        <p>주소를 다시 확인하거나 랜딩 페이지로 이동해 주세요.</p>
        <Link className={styles.link} to={ROUTES.LANDING}>
          랜딩 페이지로 이동
        </Link>
      </section>
    </main>
  );
}

export default NotFoundPage;
