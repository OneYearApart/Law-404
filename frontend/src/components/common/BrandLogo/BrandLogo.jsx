import { motion } from 'framer-motion';
import { Link } from 'react-router';

import { ROUTES } from '../../../constants/routes.js';
import styles from './BrandLogo.module.css';

function BrandLogo() {
  return (
    <motion.div whileHover={{ y: -2 }} whileTap={{ scale: 0.98 }}>
      <Link className={styles.logo} to={ROUTES.LANDING} aria-label="Law404 홈으로 이동">
        <img className={styles.image} src="/images/Logo.png" alt="Law404" />
      </Link>
    </motion.div>
  );
}

export default BrandLogo;
