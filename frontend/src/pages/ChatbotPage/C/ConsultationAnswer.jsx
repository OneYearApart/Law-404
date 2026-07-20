import { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  FiAlertCircle,
  FiInfo,
  FiChevronDown,
  FiFileText,
  FiBookOpen,
  FiCompass,
  FiDollarSign,
  FiShield,
  FiClipboard,
  FiEdit3,
} from 'react-icons/fi';

import styles from './ConsultationAnswer.module.css';

/* ═══════════════════════════════════════════════════════════════════════
   백엔드가 보내는 텍스트를 구조화하기 위한 파서들.

   백엔드 출력에는 아래와 같은 규칙적 패턴이 있습니다:
     【제8조 - 보증금 중 일정액의 보호】   ← 블록 제목
     [원문] / 쉽게 말하면: / 당신의 상황:  ← 라벨
     ---                                   ← 블록 구분자
     반박 1: "..." / 당신의 증거: / 대응 방법:
     1단계: ... / 경로 1: ...
   이 패턴을 읽어 섹션별로 다르게 렌더링합니다.
   패턴이 안 맞으면 원문 그대로 보여주므로 깨지지 않습니다.
   ═══════════════════════════════════════════════════════════════════════ */

const BLOCK_SEPARATOR = /\n\s*-{3,}\s*\n/;

function splitBlocks(text) {
  return String(text || '')
    .split(BLOCK_SEPARATOR)
    .map((s) => s.trim())
    .filter(Boolean);
}

/** 【...】 형태의 블록 제목 추출 */
function extractBlockTitle(block) {
  const matched = block.match(/^【([^】]+)】/);
  return matched ? matched[1].trim() : null;
}

function stripBlockTitle(block) {
  return block.replace(/^【[^】]+】\s*/, '').trim();
}

/**
 * 라벨 기준으로 텍스트를 잘라 { 라벨: 내용 } 형태로 반환.
 * 예: extractLabeled(text, ['[원문]', '쉽게 말하면:', '당신의 상황:'])
 */
function extractLabeled(text, labels) {
  const source = String(text || '');
  const found = labels
    .map((label) => ({ label, index: source.indexOf(label) }))
    .filter((item) => item.index >= 0)
    .sort((a, b) => a.index - b.index);

  const result = {};
  found.forEach((item, i) => {
    const start = item.index + item.label.length;
    const end = i + 1 < found.length ? found[i + 1].index : source.length;
    result[item.label] = source.slice(start, end).trim();
  });
  result.__lead = found.length ? source.slice(0, found[0].index).trim() : source.trim();
  return result;
}

/** "관련 판례를 찾지 못했습니다" 같은 빈 안내 블록인지 */
function isEmptyNotice(text) {
  return /찾지\s*못했|해당(하는)?\s*내용이?\s*없|없습니다\.?$/.test(
    String(text || '').trim(),
  );
}

/* ── 인라인 강조 ────────────────────────────────────────────────────────
   **굵게** 표기를 <strong>으로 바꾸고,
   법 조항 / 금액은 자동으로 강조합니다. */

const AUTO_EMPHASIS =
  /((?:주택임대차보호법|민법|민사집행법|상가건물임대차보호법)?\s*제\s?\d+조(?:의\s?\d+)?(?:\s?제\s?\d+항)?|\d{1,3}(?:,\d{3})*\s*(?:억|만)?\s*원)/g;

function formatInline(text, keyPrefix = 'i') {
  const parts = String(text || '').split(/(\*\*[^*]+\*\*)/g);

  return parts.flatMap((part, partIndex) => {
    if (part.startsWith('**') && part.endsWith('**') && part.length > 4) {
      return [
        <strong key={`${keyPrefix}-b-${partIndex}`}>{part.slice(2, -2)}</strong>,
      ];
    }
    // 자동 강조
    const pieces = part.split(AUTO_EMPHASIS);
    return pieces.map((piece, pieceIndex) => {
      if (!piece) return null;
      if (AUTO_EMPHASIS.test(piece)) {
        AUTO_EMPHASIS.lastIndex = 0;
        return (
          <strong key={`${keyPrefix}-a-${partIndex}-${pieceIndex}`}>{piece}</strong>
        );
      }
      AUTO_EMPHASIS.lastIndex = 0;
      return piece;
    });
  });
}

/** 문단 + 불릿 목록을 렌더링 */
function RichText({ text, className }) {
  const lines = String(text || '').split('\n');
  const nodes = [];
  let bullets = [];

  const flushBullets = (key) => {
    if (bullets.length === 0) return;
    nodes.push(
      <ul className={styles.bulletList} key={`ul-${key}`}>
        {bullets.map((item, i) => (
          <li key={`li-${key}-${i}`}>{formatInline(item, `li-${key}-${i}`)}</li>
        ))}
      </ul>,
    );
    bullets = [];
  };

  lines.forEach((rawLine, index) => {
    const line = rawLine.trim();
    if (!line) {
      flushBullets(index);
      return;
    }
    const bulletMatch = line.match(/^[-•*]\s+(.*)$/);
    if (bulletMatch) {
      bullets.push(bulletMatch[1]);
      return;
    }
    flushBullets(index);
    nodes.push(
      <p className={styles.paragraph} key={`p-${index}`}>
        {formatInline(line, `p-${index}`)}
      </p>,
    );
  });
  flushBullets('end');

  return <div className={className}>{nodes}</div>;
}

/* ── 공용 토글 ─────────────────────────────────────────────────────────── */

function Toggle({ label, children, defaultOpen = false, tone = 'plain' }) {
  const [isOpen, setIsOpen] = useState(defaultOpen);

  return (
    <div className={`${styles.toggle} ${tone === 'quote' ? styles.toggleQuote : ''}`}>
      <button
        type="button"
        className={styles.toggleButton}
        aria-expanded={isOpen}
        onClick={() => setIsOpen((v) => !v)}
      >
        <span className={styles.toggleLabel}>{label}</span>
        <FiChevronDown
          className={`${styles.toggleChevron} ${isOpen ? styles.toggleChevronOpen : ''}`}
          aria-hidden="true"
        />
      </button>
      <AnimatePresence initial={false}>
        {isOpen && (
          <motion.div
            className={styles.togglePanel}
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2 }}
          >
            <div className={styles.togglePanelInner}>{children}</div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

/* ── 섹션별 렌더러 ─────────────────────────────────────────────────────── */

/** 관련 법 조문: 조항명 + [원문] 토글 + 쉽게 말하면 + 당신의 상황 */
function LegalBasisBody({ text }) {
  const blocks = splitBlocks(text).filter((b) => !isEmptyNotice(stripBlockTitle(b)));

  if (blocks.length === 0) {
    return <p className={styles.emptyNote}>참고할 조문을 찾지 못했습니다.</p>;
  }

  return (
    <div className={styles.blockList}>
      {blocks.map((block, index) => {
        const title = extractBlockTitle(block);
        const body = stripBlockTitle(block);
        const parts = extractLabeled(body, ['[원문]', '쉽게 말하면:', '당신의 상황:']);
        const original = parts['[원문]'];
        const simple = parts['쉽게 말하면:'];
        const yours = parts['당신의 상황:'];
        const lead = parts.__lead;

        return (
          <article className={styles.lawBlock} key={`law-${index}`}>
            {title && <h4 className={styles.blockTitle}>{title}</h4>}

            {original && (
              <Toggle label="법 조문 원문 보기">
                <RichText text={original} className={styles.originalText} />
              </Toggle>
            )}

            {simple && (
              <div className={styles.subSection}>
                <h4 className={styles.subHeading}>쉽게 말하면</h4>
                <RichText text={simple} />
              </div>
            )}

            {yours && (
              <div className={`${styles.subSection} ${styles.yourCase}`}>
                <h4 className={styles.subHeading}>당신의 상황</h4>
                <RichText text={yours} />
              </div>
            )}

            {!original && !simple && !yours && lead && <RichText text={lead} />}
          </article>
        );
      })}
    </div>
  );
}

/** 관련 판례: 가장 유사한 1건만 */
function PrecedentBody({ text }) {
  const blocks = splitBlocks(text).filter((b) => !isEmptyNotice(stripBlockTitle(b)));

  if (blocks.length === 0) {
    return <p className={styles.emptyNote}>유사한 판례를 찾지 못했습니다.</p>;
  }

  // 가장 먼저 제시된(가장 유사한) 판례 1건만 사용
  const block = blocks[0];
  const title = extractBlockTitle(block);
  const body = stripBlockTitle(block);
  const parts = extractLabeled(body, [
    '상황:',
    '법원의 판단:',
    '결론:',
    '당신과의 유사점:',
  ]);

  const similarity = parts['당신과의 유사점:'];
  const conclusion = parts['결론:'];
  const judgment = parts['법원의 판단:'];
  const situation = parts['상황:'];

  return (
    <article className={styles.caseBlock}>
      {title && <h4 className={styles.blockTitle}>{title}</h4>}

      {similarity && (
        <div className={`${styles.subSection} ${styles.yourCase}`}>
          <h4 className={styles.subHeading}>내 상황과 비슷한 점</h4>
          <RichText text={similarity} />
        </div>
      )}

      {conclusion && (
        <p className={styles.caseResult}>{formatInline(conclusion, 'case-result')}</p>
      )}

      {(situation || judgment) && (
        <Toggle label="사건 내용과 법원 판단 보기">
          {situation && (
            <div className={styles.subSection}>
              <h4 className={styles.subHeading}>어떤 사건이었나</h4>
              <RichText text={situation} />
            </div>
          )}
          {judgment && (
            <div className={styles.subSection}>
              <h4 className={styles.subHeading}>법원의 판단</h4>
              <RichText text={judgment} />
            </div>
          )}
        </Toggle>
      )}

      {!similarity && !conclusion && !situation && !judgment && <RichText text={body} />}
    </article>
  );
}

/**
 * 번호가 붙은 항목(1단계 / 경로 1 / 반박 1 등)을 잘라낸다.
 * @returns [{ index, heading, body }]
 */
function splitNumbered(text, pattern) {
  const source = String(text || '');
  const lines = source.split('\n');
  const items = [];
  let current = null;

  lines.forEach((rawLine) => {
    const line = rawLine.trim();
    const matched = line.match(pattern);
    if (matched) {
      if (current) items.push(current);
      current = {
        index: matched[1],
        heading: (matched[2] || '').trim(),
        body: '',
      };
      return;
    }
    if (current) {
      current.body += `${rawLine}\n`;
    } else if (line) {
      // 첫 항목 전에 나오는 도입 문장
      items.push({ index: null, heading: null, body: line, lead: true });
    }
  });
  if (current) items.push(current);

  return items;
}

/** 구체적 행동 절차: N단계를 h4 카드로 */
function ActionStepsBody({ text }) {
  const items = splitNumbered(text, /^(\d+)\s*단계\s*[:：.]?\s*(.*)$/);
  const steps = items.filter((item) => !item.lead && item.index);

  if (steps.length === 0) {
    return <RichText text={text} />;
  }

  const leads = items.filter((item) => item.lead);

  return (
    <div className={styles.stepList}>
      {leads.map((item, i) => (
        <RichText text={item.body} key={`step-lead-${i}`} />
      ))}
      {steps.map((step, i) => (
        <article className={styles.stepItem} key={`step-${i}`}>
          <span className={styles.stepNumber} aria-hidden="true">
            {step.index}
          </span>
          <div className={styles.stepContent}>
            {step.heading && <h4 className={styles.stepHeading}>{step.heading}</h4>}
            <RichText text={step.body} />
          </div>
        </article>
      ))}
    </div>
  );
}

/** 예상 비용: 경로 N을 h4 카드로 */
function ExpectedCostBody({ text }) {
  const items = splitNumbered(text, /^경로\s*(\d+)\s*[:：.]?\s*(.*)$/);
  const routes = items.filter((item) => !item.lead && item.index);

  if (routes.length === 0) {
    return <RichText text={text} />;
  }

  const leads = items.filter((item) => item.lead);

  return (
    <div className={styles.routeList}>
      {leads.map((item, i) => (
        <RichText text={item.body} key={`cost-lead-${i}`} />
      ))}
      {routes.map((route, i) => (
        <article className={styles.routeItem} key={`route-${i}`}>
          <div className={styles.routeHead}>
            <span className={styles.routeBadge}>경로 {route.index}</span>
            {route.heading && <h4 className={styles.routeHeading}>{route.heading}</h4>}
          </div>
          <RichText text={route.body} />
        </article>
      ))}
    </div>
  );
}

/** 임대인 반박 & 대응: 반박별 토글 안에 증거/대응 */
function DisputesBody({ text }) {
  const items = splitNumbered(text, /^반박\s*(\d+)\s*[:：.]?\s*(.*)$/);
  const disputes = items.filter((item) => !item.lead && item.index);

  if (disputes.length === 0) {
    return <RichText text={text} />;
  }

  return (
    <div className={styles.disputeList}>
      {disputes.map((dispute, i) => {
        const parts = extractLabeled(dispute.body, ['당신의 증거:', '대응 방법:']);
        const evidence = parts['당신의 증거:'];
        const response = parts['대응 방법:'];
        const claim = dispute.heading.replace(/^["“]|["”]$/g, '');

        return (
          <Toggle
            key={`dispute-${i}`}
            tone="quote"
            label={
              <span className={styles.disputeLabel}>
                <span className={styles.disputeBadge}>반박 {dispute.index}</span>
                <span className={styles.disputeClaim}>“{claim}”</span>
              </span>
            }
          >
            {evidence && (
              <div className={styles.subSection}>
                <h4 className={styles.subHeading}>준비할 증거</h4>
                <RichText text={evidence} />
              </div>
            )}
            {response && (
              <div className={styles.subSection}>
                <h4 className={styles.subHeading}>대응 방법</h4>
                <RichText text={response} />
              </div>
            )}
            {!evidence && !response && <RichText text={dispute.body} />}
          </Toggle>
        );
      })}
    </div>
  );
}

/* ── 섹션 카드 ─────────────────────────────────────────────────────────── */

const SECTION_META = {
  situation: { label: '상황 진단', Icon: FiCompass },
  legal_basis: { label: '관련 법 조문', Icon: FiBookOpen },
  precedents: { label: '관련 판례', Icon: FiFileText },
  action_steps: { label: '구체적 행동 절차', Icon: FiClipboard },
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

const SECTION_BODIES = {
  legal_basis: LegalBasisBody,
  precedents: PrecedentBody,
  action_steps: ActionStepsBody,
  expected_cost: ExpectedCostBody,
  anticipated_disputes: DisputesBody,
};

function SectionCard({ sectionKey, section, index }) {
  const meta = SECTION_META[sectionKey] || { label: sectionKey, Icon: FiInfo };
  const { Icon } = meta;
  const isPending = !section || !section.content;
  const Body = SECTION_BODIES[sectionKey];

  return (
    <motion.section
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
        <h3 className={styles.sectionTitle}>{meta.label}</h3>
        {isPending && <span className={styles.writingTag}>작성 중</span>}
      </div>

      {isPending ? (
        <div className={styles.skeleton} aria-hidden="true">
          <span />
          <span />
          <span />
        </div>
      ) : (
        <div className={styles.sectionBody}>
          {Body ? <Body text={section.content} /> : <RichText text={section.content} />}
        </div>
      )}
    </motion.section>
  );
}

/* ── FAQ: Q 보이고 클릭하면 A ───────────────────────────────────────────── */

function splitQA(raw) {
  const text = String(raw || '').trim();
  const withoutQ = text.replace(/^Q\s*[:：]\s*/, '');
  const matched = withoutQ.split(/\s*A\s*[:：]\s*/);

  if (matched.length >= 2) {
    return { question: matched[0].trim(), answer: matched.slice(1).join(' ').trim() };
  }
  return { question: withoutQ.trim(), answer: '' };
}

function FaqSection({ faq }) {
  const [openIndex, setOpenIndex] = useState(null);
  if (!faq || faq.length === 0) return null;

  return (
    <section className={styles.faqBlock} aria-label="이어서 확인하면 좋은 질문">
      <div className={styles.sectionHead}>
        <span className={styles.sectionIcon} aria-hidden="true">
          <FiInfo />
        </span>
        <h3 className={styles.sectionTitle}>이어서 확인하면 좋은 질문</h3>
      </div>

      <ul className={styles.faqList}>
        {faq.map((item, i) => {
          const { question, answer } = splitQA(item);
          const isOpen = openIndex === i;

          return (
            <li className={styles.faqItem} key={`faq-${i}`}>
              <button
                type="button"
                className={styles.faqQuestion}
                aria-expanded={isOpen}
                onClick={() => setOpenIndex(isOpen ? null : i)}
              >
                <span className={styles.faqQMark} aria-hidden="true">
                  Q
                </span>
                <span className={styles.faqQText}>{question}</span>
                <FiChevronDown
                  className={`${styles.toggleChevron} ${isOpen ? styles.toggleChevronOpen : ''}`}
                  aria-hidden="true"
                />
              </button>

              <AnimatePresence initial={false}>
                {isOpen && answer && (
                  <motion.div
                    className={styles.faqAnswer}
                    initial={{ height: 0, opacity: 0 }}
                    animate={{ height: 'auto', opacity: 1 }}
                    exit={{ height: 0, opacity: 0 }}
                    transition={{ duration: 0.2 }}
                  >
                    <div className={styles.faqAnswerInner}>
                      <span className={styles.faqAMark} aria-hidden="true">
                        A
                      </span>
                      <RichText text={answer} />
                    </div>
                  </motion.div>
                )}
              </AnimatePresence>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

/* ── 내용증명 작성 제안 ─────────────────────────────────────────────────
   분류기가 문서 작성 의도를 감지했을 때 답변 아래에 붙는 카드.
   자동으로 문서 모드로 넘기지 않고, 사용자가 버튼을 눌러야 전환된다.
   onStart 는 ChatbotPage 가 넘겨주는 onQuickAnswer 콜백이다. */

function DocumentSuggestion({ onStart }) {
  if (!onStart) return null;

  return (
    <motion.div
      className={styles.suggestCard}
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
    >
      <span className={styles.suggestIcon} aria-hidden="true">
        <FiEdit3 />
      </span>
      <div className={styles.suggestText}>
        <strong>내용증명 작성을 도와드릴까요?</strong>
        <span>몇 가지 정보만 확인하면 초안을 만들어 드려요.</span>
      </div>
      <button
        type="button"
        className={styles.suggestButton}
        onClick={() => onStart('start_document')}
      >
        작성 시작하기
      </button>
    </motion.div>
  );
}

/* ── 단문 응답 (정의 / 절차 안내 / 문서 안내 / 범위 밖) ─────────────────── */

function SimpleMessage({ variant, text }) {
  const isOffTopic = variant === 'off_topic';
  const isGuide = variant === 'guide';
  const isDocIntent = variant === 'document_intent';

  const Icon = isOffTopic
    ? FiAlertCircle
    : isDocIntent
      ? FiEdit3
      : isGuide
        ? FiClipboard
        : FiInfo;

  const eyebrow = isOffTopic
    ? '안내'
    : isDocIntent
      ? '내용증명 작성'
      : isGuide
        ? '절차 안내'
        : '용어 설명';

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
        <h3 className={styles.simpleEyebrow}>{eyebrow}</h3>
      </div>
      <RichText text={text} className={styles.simpleBody} />
    </motion.article>
  );
}

/* ── 메인 ──────────────────────────────────────────────────────────────── */

function ConsultationAnswer({ content, onQuickAnswer }) {
  if (typeof content === 'string') {
    return (
      <motion.article className={styles.answer} initial={{ opacity: 0 }} animate={{ opacity: 1 }}>
        <RichText text={content} />
      </motion.article>
    );
  }

  const {
    responseType = null,
    outline,
    sections = {},
    faq = [],
    message = '',
    suggestDocument = false,
    error = null,
  } = content || {};

  if (error) {
    return (
      <div className={`${styles.simpleCard} ${styles.offTopic}`}>
        <div className={styles.simpleHead}>
          <span className={styles.simpleIcon} aria-hidden="true">
            <FiAlertCircle />
          </span>
          <h3 className={styles.simpleEyebrow}>오류</h3>
        </div>
        <p className={styles.simpleBody}>{error}</p>
      </div>
    );
  }

  // 분류 전 상태는 AssistantThinking("생각 중")이 담당 → 아무것도 그리지 않음
  if (!responseType) {
    return null;
  }

  if (responseType === 'definition') {
    return (
      <div className={styles.stack}>
        <SimpleMessage variant="definition" text={message} />
        {suggestDocument && <DocumentSuggestion onStart={onQuickAnswer} />}
      </div>
    );
  }

  if (responseType === 'guide') {
    return (
      <div className={styles.stack}>
        <SimpleMessage variant="guide" text={message} />
        {suggestDocument && <DocumentSuggestion onStart={onQuickAnswer} />}
      </div>
    );
  }

  // 문서 작성 요청 감지 → 안내 + 전환 버튼 (자동 전환하지 않음)
  if (responseType === 'document_intent') {
    return (
      <div className={styles.stack}>
        <SimpleMessage variant="document_intent" text={message} />
        <DocumentSuggestion onStart={onQuickAnswer} />
      </div>
    );
  }

  if (responseType === 'off_topic') {
    return <SimpleMessage variant="off_topic" text={message} />;
  }

  const order = outline && outline.length ? outline : DEFAULT_ORDER;

  return (
    <div className={styles.consultation}>
      <div className={styles.sectionGrid}>
        {order.map((key, i) => (
          <SectionCard key={key} sectionKey={key} section={sections[key]} index={i} />
        ))}
      </div>

      <AnimatePresence>{faq.length > 0 && <FaqSection faq={faq} />}</AnimatePresence>

      {suggestDocument && <DocumentSuggestion onStart={onQuickAnswer} />}

      <p className={styles.disclaimer}>
        이 답변은 일반적인 법률 정보이며, 개별 사안의 법적 판단을 대신하지 않습니다.
      </p>
    </div>
  );
}

export default ConsultationAnswer;