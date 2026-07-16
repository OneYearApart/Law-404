import { AnimatePresence, motion } from 'framer-motion';
import { useEffect, useMemo, useState } from 'react';
import { createPortal } from 'react-dom';

import styles from './AssistantAnswer.module.css';

function textValue(value) {
  return String(value ?? '').replace(/\s+/g, ' ').trim();
}

function cleanItem(value) {
  return textValue(
    typeof value === 'string'
      ? value
      : value?.question || value?.label || value?.text || value?.title,
  ).replace(/^\[[^\]]+\]\s*/, '');
}

function uniqueItems(values = [], limit = 10) {
  return [...new Set(values.map(cleanItem).filter(Boolean))].slice(0, limit);
}

function articleNumber(reference) {
  const combined = [reference?.title, reference?.document_id, reference?.text_preview]
    .filter(Boolean)
    .join(' ');
  const match = combined.match(/제\s*(\d+)\s*조(?:의\s*(\d+))?/u);
  if (!match) {
    return '';
  }
  return `제${match[1]}조${match[2] ? `의${match[2]}` : ''}`;
}

function sourceTitle(reference) {
  const rawTitle = textValue(reference?.title || reference?.document_id || '공식 근거 자료')
    .replace(/\s*게시글\s*$/u, '')
    .replace(/__part_\d+$/iu, '');
  const article = articleNumber(reference);

  if (/^민법(?:\s|$)/u.test(rawTitle) && article && !rawTitle.includes(article)) {
    return `민법 ${article}`;
  }
  return rawTitle;
}

function sentenceList(raw) {
  return raw
    .replace(/\s+/g, ' ')
    .split(/(?<=[.!?])\s+/u)
    .map((sentence) => sentence.trim())
    .filter((sentence) => sentence.length >= 12);
}

function relevantKeywords(reference) {
  const issueId = textValue(reference?.issue_id);
  if (issueId.includes('owner_proxy')) {
    return ['대리', '위임', '권한', '본인', '계약', '수령', '인감증명'];
  }
  if (issueId.includes('payment') || issueId.includes('account')) {
    return ['계좌', '예금주', '송금', '수령', '권한', '계약금', '잔금'];
  }
  return ['계약', '임대인', '임차인', '확인', '권한', '보증금'];
}

function cleanReferenceContent(reference) {
  const title = sourceTitle(reference);
  let raw = String(reference?.text_preview || '')
    .replace(/\r/g, '')
    .replace(/^\s*\d+\s*\|\s*/u, '')
    .replace(/\n{3,}/g, '\n\n')
    .replace(/[ \t]+/g, ' ')
    .trim();

  if (!raw) {
    return '';
  }

  const article = articleNumber(reference);
  if (/^민법/u.test(title) && article) {
    const escaped = article.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    const start = raw.search(new RegExp(escaped.replace('제', '제\\s*').replace('조', '\\s*조'), 'u'));
    if (start >= 0) {
      const selected = raw.slice(start);
      const nextArticle = selected.slice(article.length).search(/제\s*\d+\s*조(?:의\s*\d+)?/u);
      raw = nextArticle >= 0
        ? selected.slice(0, nextArticle + article.length)
        : selected;
    }
  }

  const sentences = sentenceList(raw);
  const keywords = relevantKeywords(reference);
  const relevant = sentences.filter((sentence) =>
    keywords.some((keyword) => sentence.includes(keyword)),
  );
  const selected = (relevant.length ? relevant : sentences).slice(0, 5);
  const cleaned = [...new Set(selected)]
    .map((sentence) => sentence.replace(/^Q\s*\d+\s*[.．]\s*/iu, '').trim())
    .filter(Boolean)
    .join('\n\n');

  const result = cleaned || raw;
  return result.length > 900 ? `${result.slice(0, 899).trim()}…` : result;
}

function referenceRank(reference) {
  const title = textValue(reference?.displayTitle || reference?.title);

  if (title.includes('주택임대차보호법 해설집')) {
    return 0;
  }
  if (/민법\s*제114조/u.test(title)) {
    return 1;
  }
  if (/민법\s*제130조/u.test(title)) {
    return 2;
  }
  if (/민법\s*제135조/u.test(title)) {
    return 3;
  }
  return 10;
}

function normalizeReferences(values = []) {
  const seen = new Set();
  const result = [];

  values.forEach((item, index) => {
    const reference = typeof item === 'string' ? { title: item } : item || {};
    const title = sourceTitle(reference);
    const content = cleanReferenceContent(reference);
    if (!content) {
      return;
    }

    const key = `${title}|${content.slice(0, 120)}`;
    if (seen.has(key)) {
      return;
    }

    seen.add(key);
    result.push({
      ...reference,
      modalId: `${reference.evidence_id || reference.document_id || index}-${index}`,
      displayTitle: title,
      content,
    });
  });

  return result
    .map((reference, index) => ({ reference, index }))
    .sort((left, right) =>
      referenceRank(left.reference) - referenceRank(right.reference) || left.index - right.index,
    )
    .map(({ reference }) => reference)
    .slice(0, 4);
}

function ReferenceModal({ reference, onClose }) {
  useEffect(() => {
    const onKeyDown = (event) => {
      if (event.key === 'Escape') {
        onClose();
      }
    };
    document.body.classList.add('modal-open');
    window.addEventListener('keydown', onKeyDown);
    return () => {
      document.body.classList.remove('modal-open');
      window.removeEventListener('keydown', onKeyDown);
    };
  }, [onClose]);

  if (!reference) {
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
        className={styles.referenceModal}
        role="dialog"
        aria-modal="true"
        aria-labelledby="reference-title"
        onMouseDown={(event) => event.stopPropagation()}
        initial={{ opacity: 0, y: 12, scale: 0.99 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        exit={{ opacity: 0, y: 8, scale: 0.99 }}
      >
        <header className={styles.modalHeader}>
          <h2 id="reference-title">{reference.displayTitle}</h2>
          <button type="button" onClick={onClose} aria-label="근거 내용 닫기">
            닫기
          </button>
        </header>
        <div className={styles.referenceContent}>
          {reference.content.split('\n\n').map((paragraph) => (
            <p key={paragraph}>{paragraph}</p>
          ))}
        </div>
      </motion.section>
    </motion.div>,
    document.body,
  );
}

function InformationRows({ items, emptyText }) {
  if (!items.length) {
    return <p className={styles.emptyText}>{emptyText}</p>;
  }

  return (
    <div className={styles.informationRows}>
      {items.map((item) => (
        <div key={`${item.issue_id}-${item.slot_key}`}>
          <span>{cleanItem(item.label)}</span>
          <strong>{textValue(item.display_value || item.value || '확인함')}</strong>
        </div>
      ))}
    </div>
  );
}

function ProgressPanel({ progress, riskLevel }) {
  const confirmed = progress?.confirmed_items || [];
  const unresolved = progress?.unresolved_items || [];
  const remaining = [
    ...(progress?.conflict_items || []),
    ...(progress?.remaining_items || []),
  ];
  const completed = Number(progress?.completed_count || confirmed.length + unresolved.length);
  const total = Number(progress?.total_count || completed + remaining.length);

  return (
    <div className={styles.progressPanel}>
      <header className={styles.progressHeader}>
        <div>
          <span>계약 전 확인 중</span>
          <strong>{completed} / {total}</strong>
        </div>
        <b>{riskLevel}</b>
      </header>

      <div className={styles.progressContent}>
        <section className={styles.progressSection}>
          <h3>현재 확인된 정보</h3>
          <InformationRows items={confirmed} emptyText="아직 확인된 정보가 없습니다." />
        </section>

        {unresolved.length > 0 && (
          <section className={styles.progressSection}>
            <h3>확인하지 못한 정보</h3>
            <InformationRows items={unresolved} emptyText="" />
          </section>
        )}

        <section className={styles.progressSection}>
          <h3>남은 확인 항목 {remaining.length}개</h3>
          {remaining.length ? (
            <div className={styles.remainingRows}>
              {remaining.map((item) => (
                <span key={`${item.issue_id}-${item.slot_key}`}>{cleanItem(item.label)}</span>
              ))}
            </div>
          ) : (
            <p className={styles.emptyText}>모든 질문에 답했습니다.</p>
          )}
        </section>
      </div>
    </div>
  );
}

function CompletedQuestionCard({ question, answerText, result }) {
  if (!question?.question) {
    return null;
  }

  return (
    <article className={styles.completedQuestionCard}>
      <span className={styles.completedBadge}>확인 완료</span>
      <p className={styles.completedQuestion}>{question.question}</p>

      <dl className={styles.completedDetails}>
        <div>
          <dt>선택한 답변</dt>
          <dd>{textValue(answerText) || '답변 내용이 저장되었습니다.'}</dd>
        </div>
        {result && (
          <div>
            <dt>상담 반영</dt>
            <dd>
              {cleanItem(result.label)}
              <span>·</span>
              {textValue(result.displayValue || result.groupLabel)}
            </dd>
          </div>
        )}
      </dl>
    </article>
  );
}

function QuestionCard({ question, completedCount, totalCount, onAnswer, disabled }) {
  const [customValue, setCustomValue] = useState('');
  if (!question?.question) {
    return null;
  }

  const submitCustom = (event) => {
    event.preventDefault();
    const value = customValue.trim();
    if (!value || disabled) {
      return;
    }
    onAnswer?.(value);
    setCustomValue('');
  };

  return (
    <div className={styles.questionCard}>
      <span className={styles.questionProgress}>
        질문 {Math.min(completedCount + 1, totalCount)} / {totalCount}
      </span>
      <h2>{question.question}</h2>

      {question.options?.length > 0 && (
        <div className={styles.choiceGrid}>
          {question.options.map((option) => (
            <button
              type="button"
              key={`${question.question_key || question.slot_key}-${option.label}`}
              onClick={() => onAnswer?.(option.answer_text || option.label)}
              disabled={disabled}
            >
              {option.label}
            </button>
          ))}
        </div>
      )}

      {question.allow_custom_input !== false && (
        <form className={styles.customAnswer} onSubmit={submitCustom}>
          <input
            type="text"
            value={customValue}
            onChange={(event) => setCustomValue(event.target.value)}
            placeholder={question.placeholder || '직접 답변을 입력해 주세요.'}
            disabled={disabled}
          />
          <button type="submit" disabled={!customValue.trim() || disabled}>입력</button>
        </form>
      )}
    </div>
  );
}

function TextSection({ title, items }) {
  const values = uniqueItems(items);
  if (!values.length) {
    return null;
  }
  return (
    <section className={styles.finalSection}>
      <h3>{title}</h3>
      <div className={styles.textRows}>
        {values.map((item) => <p key={`${title}-${item}`}>{item}</p>)}
      </div>
    </section>
  );
}

function DocumentSummary({ summary }) {
  if (!summary?.sections?.length) {
    return null;
  }
  return (
    <section className={styles.finalSection}>
      <h3>첨부 문서 분석 결과</h3>
      <div className={styles.documentSections}>
        {summary.sections.map((section, index) => (
          <div key={`${section.title}-${index}`}>
            <strong>{section.title}</strong>
            {uniqueItems(section.items).map((item) => <p key={item}>{item}</p>)}
          </div>
        ))}
      </div>
    </section>
  );
}

function FinalAnswer({ answer, references, onSelectReference }) {
  return (
    <article className={styles.finalAnswer}>
      <header className={styles.finalHeader}>
        <span>계약 전 확인 완료</span>
        <strong>{answer.riskLevel}</strong>
      </header>

      <section className={styles.conclusion}>
        <h2>핵심 결론</h2>
        <p>{answer.coreJudgment}</p>
      </section>

      <TextSection title="확인된 사실" items={answer.knownFacts} />
      <TextSection title="확인하지 못한 사실" items={answer.unresolvedFacts} />
      <TextSection title="지금 해야 할 행동" items={answer.immediateActions} />
      <TextSection title="아직 보류할 일" items={answer.holdActions} />
      <TextSection title="판단 이유" items={answer.reasons} />
      <DocumentSummary summary={answer.documentSummary} />

      {references.length > 0 && (
        <section className={styles.finalSection}>
          <h3>참고 근거</h3>
          <div className={styles.referenceButtons}>
            {references.map((reference) => (
              <button
                type="button"
                key={reference.modalId}
                onClick={() => onSelectReference(reference)}
              >
                {reference.displayTitle}
              </button>
            ))}
          </div>
        </section>
      )}
    </article>
  );
}

function AAssistantAnswer({ content, onQuickAnswer, isInteractive = false }) {
  const answer = typeof content === 'string'
    ? { coreJudgment: content, isComplete: true, answerPhase: 'complete' }
    : content || {};
  const [selectedReference, setSelectedReference] = useState(null);
  const references = useMemo(() => normalizeReferences(answer.references), [answer.references]);
  const progress = answer.consultationProgress || {
    completed_count: 0,
    total_count: answer.remainingQuestionCount || 0,
    confirmed_items: [],
    unresolved_items: [],
    remaining_items: [],
    conflict_items: [],
  };

  if (answer.displayMode === 'completed-question') {
    return (
      <CompletedQuestionCard
        question={answer.nextQuestion}
        answerText={answer.completedAnswer}
        result={answer.completedResult}
      />
    );
  }

  return (
    <>
      <div
        className={`${styles.answerStack} ${
          answer.isComplete ? styles.finalAnswerStack : styles.collectingAnswerStack
        }`}
      >
        {answer.isComplete ? (
          <>
            <FinalAnswer
              answer={answer}
              references={references}
              onSelectReference={setSelectedReference}
            />
          </>
        ) : (
          <section className={styles.collectingCard}>
            <ProgressPanel progress={progress} riskLevel={answer.riskLevel} />
            <QuestionCard
              question={answer.nextQuestion}
              completedCount={Number(progress.completed_count || 0)}
              totalCount={Number(progress.total_count || 0)}
              onAnswer={onQuickAnswer}
              disabled={!isInteractive}
            />
          </section>
        )}
      </div>

      <AnimatePresence>
        {selectedReference && (
          <ReferenceModal reference={selectedReference} onClose={() => setSelectedReference(null)} />
        )}
      </AnimatePresence>
    </>
  );
}

export default AAssistantAnswer;
