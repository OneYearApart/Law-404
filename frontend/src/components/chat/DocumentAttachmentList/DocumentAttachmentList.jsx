import { AnimatePresence, motion } from 'framer-motion';
import { FiFileText, FiTrash2 } from 'react-icons/fi';

import styles from './DocumentAttachmentList.module.css';

const DOCUMENT_TYPE_LABELS = {
  lease_contract: '임대차계약서',
  registry: '등기부등본',
};

function DocumentAttachmentList({ documents, onDelete, isBusy }) {
  if (!documents.length) {
    return null;
  }

  return (
    <section className={styles.panel} aria-label="첨부한 문서">
      <div className={styles.list}>
        <AnimatePresence initial={false}>
          {documents.map((document) => (
            <motion.article
              className={styles.item}
              key={document.document_id}
              layout
              initial={{ opacity: 0, y: 4 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, x: -10 }}
            >
              <button
                type="button"
                className={styles.deleteButton}
                aria-label={`${document.original_filename} 삭제`}
                onClick={() => onDelete(document.document_id)}
                disabled={isBusy}
              >
                <FiTrash2 aria-hidden="true" />
              </button>
              <span className={styles.icon} aria-hidden="true">
                <FiFileText />
              </span>
              <strong className={styles.fileName} title={document.original_filename}>
                {document.original_filename}
              </strong>
              <span className={styles.documentType}>
                {DOCUMENT_TYPE_LABELS[document.document_type] || document.document_type}
              </span>
            </motion.article>
          ))}
        </AnimatePresence>
      </div>
    </section>
  );
}

export default DocumentAttachmentList;
