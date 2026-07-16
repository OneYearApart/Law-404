import { AnimatePresence, motion } from 'framer-motion';
import { FiCheckCircle, FiFileText, FiRefreshCw, FiTrash2 } from 'react-icons/fi';

import styles from './DocumentAttachmentList.module.css';

const DOCUMENT_TYPE_LABELS = {
  lease_contract: '임대차계약서',
  registry: '등기부등본',
};

function statusLabel(document) {
  if (document.analysis_status === 'completed') {
    return '분석 완료';
  }
  if (document.analysis_status === 'failed') {
    return '분석 실패';
  }
  if (document.processing_status === 'completed') {
    return '텍스트 추출 완료';
  }
  if (document.processing_status === 'failed') {
    return '추출 실패';
  }
  return '처리 중';
}

function DocumentAttachmentList({ documents, onDelete, onAnalyze, isBusy }) {
  if (!documents.length) {
    return null;
  }

  return (
    <motion.section
      className={styles.panel}
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      aria-label="업로드한 문서"
    >
      <div className={styles.headingRow}>
        <div>
          <strong>첨부 문서 {documents.length}개</strong>
          <span>이 상담의 질문은 같은 문서 분석 결과를 사용합니다.</span>
        </div>
        <motion.button
          type="button"
          className={styles.analyzeButton}
          onClick={onAnalyze}
          disabled={isBusy}
          whileHover={isBusy ? undefined : { y: -1 }}
          whileTap={isBusy ? undefined : { scale: 0.97 }}
        >
          <FiRefreshCw className={isBusy ? styles.spinning : undefined} aria-hidden="true" />
          <span>다시 분석</span>
        </motion.button>
      </div>

      <div className={styles.list}>
        <AnimatePresence initial={false}>
          {documents.map((document) => (
            <motion.article
              className={styles.item}
              key={document.document_id}
              layout
              initial={{ opacity: 0, scale: 0.98 }}
              animate={{ opacity: 1, scale: 1 }}
              exit={{ opacity: 0, x: -14 }}
            >
              <span className={styles.icon} aria-hidden="true">
                <FiFileText />
              </span>
              <div className={styles.info}>
                <strong title={document.original_filename}>{document.original_filename}</strong>
                <span>{DOCUMENT_TYPE_LABELS[document.document_type] || document.document_type}</span>
              </div>
              <span
                className={`${styles.status} ${
                  document.analysis_status === 'completed' ? styles.completed : ''
                }`}
              >
                {document.analysis_status === 'completed' && <FiCheckCircle aria-hidden="true" />}
                {statusLabel(document)}
              </span>
              <motion.button
                type="button"
                className={styles.deleteButton}
                aria-label={`${document.original_filename} 삭제`}
                onClick={() => onDelete(document.document_id)}
                disabled={isBusy}
                whileHover={isBusy ? undefined : { scale: 1.08 }}
                whileTap={isBusy ? undefined : { scale: 0.92 }}
              >
                <FiTrash2 aria-hidden="true" />
              </motion.button>
            </motion.article>
          ))}
        </AnimatePresence>
      </div>
    </motion.section>
  );
}

export default DocumentAttachmentList;
