import { motion } from 'framer-motion';
import {
  FiAlertTriangle,
  FiCheckCircle,
  FiFileText,
  FiHelpCircle,
  FiInfo,
  FiLayers,
  FiLink,
  FiShield,
} from 'react-icons/fi';

import styles from './AssistantAnswer.module.css';

function toDisplayText(item) {
  if (typeof item === 'string') {
    return item;
  }

  if (!item || typeof item !== 'object') {
    return String(item ?? '');
  }

  return item.question || item.title || item.text || item.label || JSON.stringify(item);
}

function AnswerList({ title, items, Icon }) {
  if (!items?.length) {
    return null;
  }

  return (
    <section className={styles.section}>
      <h3>
        <Icon aria-hidden="true" />
        <span>{title}</span>
      </h3>
      <ul>
        {items.map((item, index) => (
          <li key={`${title}-${index}`}>{toDisplayText(item)}</li>
        ))}
      </ul>
    </section>
  );
}

function DocumentSummary({ summary }) {
  if (!summary?.sections?.length) {
    return null;
  }

  return (
    <section className={styles.documentSummary}>
      <h3>
        <FiLayers aria-hidden="true" />
        <span>첨부 문서 분석 결과</span>
      </h3>
      <div className={styles.documentSections}>
        {summary.sections.map((section, index) => (
          <article key={`${section.title}-${index}`}>
            <strong>{section.title}</strong>
            <ul>
              {(section.items || []).map((item, itemIndex) => (
                <li key={`${section.title}-${itemIndex}`}>{toDisplayText(item)}</li>
              ))}
            </ul>
          </article>
        ))}
      </div>
    </section>
  );
}

function AAssistantAnswer({ content }) {
  const answer = typeof content === 'string' ? { coreJudgment: content } : content;

  return (
    <motion.article
      className={styles.answer}
      initial={{ opacity: 0, scale: 0.98 }}
      animate={{ opacity: 1, scale: 1 }}
      whileHover={{ y: -2 }}
      transition={{ duration: 0.25 }}
    >
      <header className={styles.header}>
        <span className={styles.label}>
          <FiShield aria-hidden="true" />
          계약 전 확인
        </span>
        {answer.riskLevel && <span className={styles.risk}>{answer.riskLevel}</span>}
      </header>

      <p className={styles.judgment}>{answer.coreJudgment}</p>

      <DocumentSummary summary={answer.documentSummary} />

      <div className={styles.sections}>
        <AnswerList title="지금 확인할 일" items={answer.immediateActions} Icon={FiCheckCircle} />
        <AnswerList title="일단 보류할 일" items={answer.holdActions} Icon={FiAlertTriangle} />
        <AnswerList title="판단 이유" items={answer.reasons} Icon={FiInfo} />
        <AnswerList title="추가로 필요한 정보" items={answer.requiredInformation} Icon={FiFileText} />
        <AnswerList title="추가 확인 질문" items={answer.followUpQuestions} Icon={FiHelpCircle} />
        <AnswerList title="참고 근거" items={answer.references} Icon={FiLink} />
      </div>

      {answer.warnings?.length > 0 && (
        <div className={styles.warning}>
          <FiAlertTriangle aria-hidden="true" />
          <ul>
            {answer.warnings.map((warning, index) => (
              <li key={`warning-${index}`}>{toDisplayText(warning)}</li>
            ))}
          </ul>
        </div>
      )}
    </motion.article>
  );
}

export default AAssistantAnswer;
