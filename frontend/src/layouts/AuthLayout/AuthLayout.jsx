import { Outlet } from 'react-router';

import AppHeader from '../../components/common/AppHeader/AppHeader.jsx';
import styles from './AuthLayout.module.css';

function AuthLayout() {
  return (
    <div className={styles.layout}>
      <AppHeader />

      <main className={styles.page}>
        <div className={styles.formArea}>
          <Outlet />
        </div>
      </main>
    </div>
  );
}

export default AuthLayout;
