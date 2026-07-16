import { motion } from 'framer-motion';
import { useRef } from 'react';
import { FiPaperclip, FiSend } from 'react-icons/fi';

import styles from './ChatComposer.module.css';

function ChatComposer({
  value,
  onChange,
  onSubmit,
  placeholder,
  isLoading = false,
  onFilesSelected,
  fileButtonDisabled = false,
}) {
  const fileInputRef = useRef(null);

  const handleKeyDown = (event) => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      event.currentTarget.form?.requestSubmit();
    }
  };

  const handleFileChange = (event) => {
    const files = Array.from(event.target.files ?? []);
    event.target.value = '';

    if (files.length > 0) {
      onFilesSelected?.(files);
    }
  };

  return (
    <form className={styles.composer} onSubmit={onSubmit}>
      <input
        ref={fileInputRef}
        className={styles.fileInput}
        type="file"
        accept="application/pdf,.pdf"
        multiple
        onChange={handleFileChange}
        tabIndex="-1"
        aria-hidden="true"
      />

      <motion.button
        className={styles.addButton}
        type="button"
        aria-label="계약서 또는 등기부등본 PDF 추가"
        onClick={() => fileInputRef.current?.click()}
        disabled={fileButtonDisabled}
        whileHover={fileButtonDisabled ? undefined : { scale: 1.08, rotate: -5 }}
        whileTap={fileButtonDisabled ? undefined : { scale: 0.92 }}
      >
        <FiPaperclip aria-hidden="true" />
      </motion.button>

      <textarea
        className={styles.textarea}
        value={value}
        onChange={onChange}
        onKeyDown={handleKeyDown}
        placeholder={placeholder}
        rows="1"
        aria-label="상담 질문 입력"
        disabled={isLoading}
      />

      <motion.button
        className={styles.sendButton}
        type="submit"
        disabled={!value.trim() || isLoading}
        aria-label="메시지 전송"
        whileHover={!value.trim() || isLoading ? undefined : { scale: 1.08, y: -1 }}
        whileTap={!value.trim() || isLoading ? undefined : { scale: 0.92 }}
      >
        <FiSend aria-hidden="true" />
      </motion.button>
    </form>
  );
}

export default ChatComposer;
