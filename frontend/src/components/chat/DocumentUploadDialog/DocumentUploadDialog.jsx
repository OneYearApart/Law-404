import { AnimatePresence, motion } from 'framer-motion';
import { FiFileText, FiTrash2, FiUpload, FiX } from 'react-icons/fi';

import styles from './DocumentUploadDialog.module.css';

const DOCUMENT_TYPE_OPTIONS = [
  { value: 'lease_contract', label: '주택 임대차계약서' },
  { value: 'registry', label: '등기부등본·등기사항증명서' },
];

function formatFileSize(size) {
  if (!Number.isFinite(size)) {
    return '';
  }

  if (size < 1024 * 1024) {
    return `${Math.max(1, Math.round(size / 1024))}KB`;
  }

  return `${(size / (1024 * 1024)).toFixed(1)}MB`;
}

function DocumentUploadDialog({
  isOpen,
  files,
  onTypeChange,
  onRemove,
  onCancel,
  onConfirm,
  isUploading,
}) {
  return (
    <AnimatePresence>
      {isOpen && (
        <motion.div
          className={styles.backdrop}
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          onMouseDown={(event) => {
            if (event.target === event.currentTarget && !isUploading) {
              onCancel();
            }
          }}
        >
          <motion.section
            className={styles.dialog}
            role="dialog"
            aria-modal="true"
            aria-labelledby="document-upload-title"
            initial={{ opacity: 0, y: 18, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 12, scale: 0.98 }}
            transition={{ duration: 0.2 }}
          >
            <header className={styles.header}>
              <div>
                <h2 id="document-upload-title">문서 종류 확인</h2>
                <p>각 PDF가 계약서인지 등기부등본인지 선택해 주세요.</p>
              </div>
              <motion.button
                type="button"
                className={styles.closeButton}
                aria-label="문서 업로드 창 닫기"
                onClick={onCancel}
                disabled={isUploading}
                whileHover={isUploading ? undefined : { rotate: 5, scale: 1.05 }}
                whileTap={isUploading ? undefined : { scale: 0.92 }}
              >
                <FiX aria-hidden="true" />
              </motion.button>
            </header>

            <div className={styles.fileList}>
              {files.map((item) => (
                <article className={styles.fileRow} key={item.id}>
                  <span className={styles.fileIcon} aria-hidden="true">
                    <FiFileText />
                  </span>
                  <div className={styles.fileInfo}>
                    <strong title={item.file.name}>{item.file.name}</strong>
                    <span>{formatFileSize(item.file.size)}</span>
                  </div>
                  <label className={styles.typeField}>
                    <span>문서 종류</span>
                    <select
                      value={item.documentType}
                      onChange={(event) => onTypeChange(item.id, event.target.value)}
                      disabled={isUploading}
                    >
                      {DOCUMENT_TYPE_OPTIONS.map((option) => (
                        <option key={option.value} value={option.value}>
                          {option.label}
                        </option>
                      ))}
                    </select>
                  </label>
                  <motion.button
                    type="button"
                    className={styles.removeButton}
                    aria-label={`${item.file.name} 선택 취소`}
                    onClick={() => onRemove(item.id)}
                    disabled={isUploading}
                    whileHover={isUploading ? undefined : { scale: 1.08 }}
                    whileTap={isUploading ? undefined : { scale: 0.92 }}
                  >
                    <FiTrash2 aria-hidden="true" />
                  </motion.button>
                </article>
              ))}
            </div>

            <div className={styles.guide}>
              PDF 파일만 업로드할 수 있으며 파일 하나당 최대 20MB까지 지원합니다.
            </div>

            <footer className={styles.actions}>
              <button type="button" className={styles.cancelButton} onClick={onCancel} disabled={isUploading}>
                취소
              </button>
              <motion.button
                type="button"
                className={styles.uploadButton}
                onClick={onConfirm}
                disabled={isUploading || files.length === 0}
                whileHover={isUploading || files.length === 0 ? undefined : { y: -1 }}
                whileTap={isUploading || files.length === 0 ? undefined : { scale: 0.98 }}
              >
                <FiUpload aria-hidden="true" />
                <span>{isUploading ? '업로드 중' : `${files.length}개 업로드`}</span>
              </motion.button>
            </footer>
          </motion.section>
        </motion.div>
      )}
    </AnimatePresence>
  );
}

export default DocumentUploadDialog;
