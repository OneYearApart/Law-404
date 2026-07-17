import { AnimatePresence, motion } from 'framer-motion';
import { useEffect, useState } from 'react';
import { createPortal } from 'react-dom';

import styles from './AssistantAnswer.module.css';

// 스트림 진행 상태. done은 라벨을 붙이지 않는다 — 완료됐다는 사실 자체는 본문이 이미 말해주고,
// 여기에 '주의' 같은 위험 어휘를 넣으면 단순 요건 질문에도 경고가 붙는다(판정 배지는 별도).
const STATUS_LABELS = {
  loading: '분석 중',
  streaming: '답변 중',
  error: '오류',
};

function CitationModal({ citation, onClose }) {
  useEffect(() => {
    const onKeyDown = (event) => {
      if (event.key === 'Escape') {
        onClose();
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [onClose]);

  if (!citation) {
    return null;
  }

  return createPortal(
    <motion.div
      className={styles.modalBackdrop}
      role="presentation"
      onMouseDown={onClose}
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
    >
      <motion.section
        className={styles.citationModal}
        role="dialog"
        aria-modal="true"
        aria-labelledby="citation-title"
        onMouseDown={(event) => event.stopPropagation()}
        initial={{ opacity: 0, y: 12, scale: 0.99 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        exit={{ opacity: 0, y: 8, scale: 0.99 }}
      >
        <header className={styles.modalHeader}>
          <h2 id="citation-title">
            {citation.label}
            <span className={styles.modalSourceType}>{citation.source_type}</span>
            {citation.is_excerpt && <span className={styles.excerpt}>발췌</span>}
          </h2>
          <button type="button" onClick={onClose} aria-label="근거 내용 닫기">
            닫기
          </button>
        </header>
        <div className={styles.citationContent}>
          <p>{citation.content}</p>
        </div>
      </motion.section>
    </motion.div>,
    document.body,
  );
}

function DAssistantAnswer({ content }) {
  const { status, citations, judgment, text, appendix, disclaimer, errorMessage } = content;
  const [selectedCitation, setSelectedCitation] = useState(null);
  const statusLabel = STATUS_LABELS[status];

  return (
    <>
      <motion.article className={styles.answer} initial={{ opacity: 0 }} animate={{ opacity: 1 }}>
        <header className={styles.header}>
          <span className={styles.label}>전세사기 상담</span>
          {/* 판정 배지는 victim_check가 이번 턴에 판단을 새로 확정했을 때만 백엔드가 내려준다. */}
          {judgment ? (
            <span className={styles.judgmentGroup}>
              <span className={styles.judgmentCaption}>전세사기 위험도</span>
              <strong className={styles.judgment}>{judgment}</strong>
            </span>
          ) : (
            statusLabel && <span className={styles.status}>{statusLabel}</span>
          )}
        </header>

        {status === 'error' ? (
          <p className={styles.errorMessage}>{errorMessage}</p>
        ) : (
          <p className={styles.body}>
            {text || (status === 'loading' ? '답변을 준비하고 있습니다.' : null)}
          </p>
        )}

        {/* 해설·상황적용(LLM 본문) 다음의 3번 블록. 내용은 백엔드가 큐레이션한 고정 텍스트라
            프론트는 제목만 씌우고 문구는 손대지 않는다. */}
        {appendix && (
          <section className={styles.appendix}>
            <h3 className={styles.appendixTitle}>대응</h3>
            <p className={styles.appendixBody}>{appendix}</p>
          </section>
        )}

        {citations.length > 0 && (
          <section className={styles.citations}>
            <h3 className={styles.citationsTitle}>참고 근거</h3>
            <div className={styles.citationButtons}>
              {citations.map((citation) => (
                <button
                  type="button"
                  key={`${citation.source_type}-${citation.label}`}
                  onClick={() => setSelectedCitation(citation)}
                >
                  {citation.label}
                </button>
              ))}
            </div>
          </section>
        )}

        {/* 면책은 §9.3상 법률 정보 응답에 반드시 따라붙어야 한다. 백엔드가 스트림에 인라인하지 않고
            슬롯으로 넘기므로, 내려온 턴에는 이 블록이 빠짐없이 렌더돼야 한다. */}
        {disclaimer && <p className={styles.disclaimer}>{disclaimer}</p>}
      </motion.article>

      <AnimatePresence>
        {selectedCitation && (
          <CitationModal citation={selectedCitation} onClose={() => setSelectedCitation(null)} />
        )}
      </AnimatePresence>
    </>
  );
}

export default DAssistantAnswer;
