import { AnimatePresence, motion } from 'framer-motion';
import { useEffect, useMemo, useState } from 'react';
import { createPortal } from 'react-dom';

import { splitDBody } from '../../../api/chat/D/dApi.js';
import styles from './AssistantAnswer.module.css';

// 스트림 진행 상태. done은 라벨을 붙이지 않는다 — 완료됐다는 사실 자체는 본문이 이미 말해주고,
// 여기에 '주의' 같은 위험 어휘를 넣으면 단순 요건 질문에도 경고가 붙는다(판정 배지는 별도).
const STATUS_LABELS = {
  loading: '분석 중',
  streaming: '답변 중',
  error: '오류',
};

// 화면 제목 ← [답변 성격][본문 머리글]. 머리글('### 해설' 등)은 모델과의 내부 계약이라
// 표시 문구와 분리한다 — 카피를 다듬을 때마다 프롬프트를 건드리면 LLM 출력 형식이 흔들린다.
//
// 성격별로 나누는 이유: 네 경로(판정/시나리오/특수상황/자유질의)가 같은 프롬프트를 태우지만
// 내용이 다르다. 판정이 없는 턴의 '상황적용'은 내 상황 판단이 아니라 일반 유의사항이라
// (response.md가 그렇게 지시한다), 전부 '내 상황은요'로 달면 내용과 어긋난다.
const SECTION_TITLES = {
  judgment: { 해설: '이런 사례가 있어요', 상황적용: '내 상황은요' },
  scenario: { 해설: '이런 사례가 있어요', 상황적용: '짚어볼 점' },
  special_case: { 해설: '이런 사례가 있어요', 상황적용: '짚어볼 점' },
  open_qa: { 해설: '설명', 상황적용: '확인하실 점' },
};
// 성격을 모르는 턴(백엔드가 answer_kind를 안 보냄)에는 어느 내용에도 틀리지 않는 제목을 쓴다.
const DEFAULT_SECTION_TITLES = { 해설: '설명', 상황적용: '짚어볼 점' };

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
  const {
    status, citations, judgment, text, appendix, disclaimer, terms, answerKind, errorMessage,
  } = content;
  const [selectedCitation, setSelectedCitation] = useState(null);
  const statusLabel = STATUS_LABELS[status];
  const bodySections = useMemo(() => splitDBody(text), [text]);
  const sectionTitles = SECTION_TITLES[answerKind] ?? DEFAULT_SECTION_TITLES;

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
        ) : bodySections.length ? (
          // 해설 → 상황적용. 머리글이 깨진 응답은 title이 null인 단일 섹션으로 온다(폴백).
          bodySections.map((section) => (
            <section className={styles.section} key={section.title ?? 'body'}>
              {section.title && (
                <h3 className={styles.sectionTitle}>
                  {sectionTitles[section.title] ?? section.title}
                </h3>
              )}
              <p className={styles.sectionBody}>{section.body}</p>
            </section>
          ))
        ) : status === 'loading' ? (
          // 첫 토큰까지 supervisor→victim_check→RAG→LLM을 다 거쳐 대기가 길다.
          // 멈춘 것처럼 보이지 않게 진행 중임을 계속 알린다.
          <div className={styles.loading} role="status" aria-live="polite">
            <span className={styles.loadingDots} aria-hidden="true" />
            <span>답변을 준비하고 있습니다</span>
          </div>
        ) : null}

        {/* 대응 — 백엔드가 큐레이션한 고정 텍스트라 프론트는 제목만 씌우고 문구는 손대지 않는다. */}
        {appendix && (
          <section className={styles.section}>
            <h3 className={styles.sectionTitle}>대응은요</h3>
            <p className={styles.sectionBody}>{appendix}</p>
          </section>
        )}

        {/* 관련 법률 용어 풀이 — 본문·대응에 실제로 등장한 용어만 백엔드가 골라 내려준다.
            문구는 DB 원문 그대로라 여기서 재가공하지 않는다. */}
        {terms.length > 0 && (
          <section className={styles.section}>
            <h3 className={styles.sectionTitle}>관련 법률 용어 풀이</h3>
            <dl className={styles.terms}>
              {terms.map((entry) => (
                <div key={entry.term}>
                  <dt>{entry.term}</dt>
                  <dd>{entry.description}</dd>
                </div>
              ))}
            </dl>
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
