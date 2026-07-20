import { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  FiCheckCircle,
  FiAlertCircle,
  FiInfo,
  FiChevronDown,
  FiFileText,
  FiBookOpen,
  FiCompass,
  FiDollarSign,
  FiShield,
  FiClipboard,
} from 'react-icons/fi';

import styles from './ConsultationAnswer.module.css';

/**
 * C파트(계약 후) 상담 답변.
 *
 * content 는 스트리밍이 채워가는 객체입니다 (부모가 streamCAsk 콜백으로 갱신):
 * {
 *   responseType: 'consultation' | 'definition' | 'off_topic' | null,
 *   outline: ['situation', ...],
 *   sections: { situation: {title,content,citations}, ... },
 *   faq: string[],
 *   message: string,
 *   meta: { confidence_score, deposit_amount, elapsed_seconds },
 *   isStreaming: boolean,
 *   error: string | null,
 * }
 *
 * 문자열이 오면(과거 저장된 대화 등) 기존 단순 카드로 표시합니다.
 */

const SECTION_META = {
  situation: { label: '상황 진단', Icon: FiCompass },
  legal_basis: { label: '관련 법 조문', Icon: FiBookOpen },
  precedents: { label: '관련 판례', Icon: FiFileText },
  action_steps: { label: '행동 절차', Icon: FiClipboard },
  expected_cost: { label: '예상 비용', Icon: FiDollarSign },
  anticipated_disputes: { label: '임대인 반박 & 대응', Icon: FiShield },
};

const DEFAULT_ORDER = [
  'situation',
  'legal_basis',
  'precedents',
  'action_steps',
  'expected_cost',
  'anticipated_disputes',
];

function CitationChips({ citations }) {
  if (!citations || citations.length === 0) return null;
  return (
    <div className={styles.citations}>
      {citations.map((cite, i) => (
        <span className={styles.citationChip} key={`${cite}-${i}`}>
          {cite}
        </span>
      ))}
    </div>
  );
}

function SectionCard({ sectionKey, section, index }) {
  const meta = SECTION_META[sectionKey] || { label: sectionKey, Icon: FiInfo };
  const { Icon } = meta;
  const isPending = !section || !section.content;

  return (
    <motion.article
      className={`${styles.sectionCard} ${isPending ? styles.pending : ''}`}
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.28, delay: Math.min(index * 0.03, 0.15) }}
      layout
    >
      <div className={styles.sectionHead}>
        <span className={styles.sectionIcon} aria-hidden="true">
          <Icon />
        </span>
        <span className={styles.sectionLabel}>{section?.title || meta.label}</span>
        {isPending && <span className={styles.writingTag}>작성 중</span>}
      </div>

      {isPending ? (
        <div className={styles.skeleton} aria-hidden="true">
          <span />
          <span />
          <span />
        </div>
      ) : (
        <>
          <p className={styles.sectionBody}>{section.content}</p>
          <CitationChips citations={section.citations} />
        </>
      )}
    </motion.article>
  );
}

function FaqAccordion({ faq }) {
  const [openIndex, setOpenIndex] = useState(null);
  if (!faq || faq.length === 0) return null;

  return (
    <section className={styles.faqBlock} aria-label="자주 묻는 질문">
      <div className={styles.faqHeading}>
        <FiInfo aria-hidden="true" />
        <span>이어서 확인하면 좋은 질문</span>
      </div>
      <ul className={styles.faqList}>
        {faq.map((item, i) => {
          const isOpen = openIndex === i;
          return (
            <li className={styles.faqItem} key={`${item}-${i}`}>
              <button
                type="button"
                className={styles.faqQuestion}
                aria-expanded={isOpen}
                onClick={() => setOpenIndex(isOpen ? null : i)}
              >
                <span>{item}</span>
                <FiChevronDown
                  className={`${styles.faqChevron} ${isOpen ? styles.faqChevronOpen : ''}`}
                  aria-hidden="true"
                />
              </button>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

function MetaBar({ meta }) {
  if (!meta) return null;
  const { confidence_score: score, deposit_amount: deposit, elapsed_seconds: elapsed } = meta;

  const confidenceLabel =
    score >= 0.7 ? '근거 충분' : score >= 0.4 ? '근거 보통' : '근거 제한적';

  return (
    <div className={styles.metaBar}>
      <span className={styles.metaItem}>
        <FiCheckCircle aria-hidden="true" />
        {confidenceLabel}
      </span>
      {typeof deposit === 'number' && deposit > 0 && (
        <span className={styles.metaItem}>보증금 {deposit.toLocaleString()}원 기준</span>
      )}
      {typeof elapsed === 'number' && elapsed > 0 && (
        <span className={styles.metaItemMuted}>{elapsed.toFixed(1)}초</span>
      )}
    </div>
  );
}

// ── 단문 응답 (정의 / 범위 밖) ──────────────────────────────────────────────

function SimpleMessage({ variant, text }) {
  const isOffTopic = variant === 'off_topic';
  const Icon = isOffTopic ? FiAlertCircle : FiInfo;
  const eyebrow = isOffTopic ? '안내' : '용어 설명';

  return (
    <motion.article
      className={`${styles.simpleCard} ${isOffTopic ? styles.offTopic : styles.definition}`}
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
    >
      <div className={styles.simpleHead}>
        <span className={styles.simpleIcon} aria-hidden="true">
          <Icon />
        </span>
        <span className={styles.simpleEyebrow}>{eyebrow}</span>
      </div>
      <p className={styles.simpleBody}>{text}</p>
    </motion.article>
  );
}

// ── 메인 ────────────────────────────────────────────────────────────────────

function ConsultationAnswer({ content }) {
  // 문자열이면(과거 저장된 대화 복원 등) 기존 단순 카드 형태로 표시
  if (typeof content === 'string') {
    return (
      <motion.article
        className={styles.answer}
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
      >
        <span className={styles.icon} aria-hidden="true">
          <FiCheckCircle />
        </span>
        <div>
          <span className={styles.label}>계약 후 절차</span>
          <p>{content}</p>
        </div>
      </motion.article>
    );
  }

  const {
    responseType = null,
    outline,
    sections = {},
    faq = [],
    message = '',
    meta = null,
    isStreaming = false,
    error = null,
  } = content || {};

  if (error) {
    return (
      <div className={`${styles.simpleCard} ${styles.offTopic}`}>
        <div className={styles.simpleHead}>
          <span className={styles.simpleIcon} aria-hidden="true">
            <FiAlertCircle />
          </span>
          <span className={styles.simpleEyebrow}>오류</span>
        </div>
        <p className={styles.simpleBody}>{error}</p>
      </div>
    );
  }

  // 아직 분류 전 → 생각 중 표시
  if (!responseType) {
    return (
      <div className={styles.classifying}>
        <span className={styles.pulseDot} />
        <span className={styles.pulseDot} />
        <span className={styles.pulseDot} />
        <span className={styles.classifyingText}>질문을 살펴보고 있어요</span>
      </div>
    );
  }

  if (responseType === 'definition') {
    return <SimpleMessage variant="definition" text={message} />;
  }
  if (responseType === 'off_topic') {
    return <SimpleMessage variant="off_topic" text={message} />;
  }

  // consultation
  const order = outline && outline.length ? outline : DEFAULT_ORDER;

  return (
    <div className={styles.consultation}>
      <div className={styles.answerEyebrow}>
        <span className={styles.eyebrowDot} />
        계약 후 상담 결과
      </div>

      <div className={styles.sectionGrid}>
        {order.map((key, i) => (
          <SectionCard key={key} sectionKey={key} section={sections[key]} index={i} />
        ))}
      </div>

      <AnimatePresence>{faq.length > 0 && <FaqAccordion faq={faq} />}</AnimatePresence>

      {!isStreaming && <MetaBar meta={meta} />}

      <p className={styles.disclaimer}>
        이 답변은 일반적인 법률 정보이며, 개별 사안의 법적 판단을 대신하지 않습니다.
      </p>
    </div>
  );
}

export default ConsultationAnswer;