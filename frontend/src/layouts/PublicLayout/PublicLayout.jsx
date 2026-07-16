import { Outlet } from 'react-router';

import AppFooter from '../../components/common/AppFooter/AppFooter.jsx';
import AppHeader from '../../components/common/AppHeader/AppHeader.jsx';
import styles from './PublicLayout.module.css';

function PublicLayout() {
  return (
    <div className={styles.layout}>
      <AppHeader />
      <div className={styles.content}>
        <Outlet />
      </div>
      <AppFooter />
    </div>
  );
}

export default PublicLayout;
