import { motion } from 'framer-motion';
import {
  FiCalendar,
  FiCheckCircle,
  FiEdit3,
  FiExternalLink,
} from 'react-icons/fi';

import styles from './AssistantAnswer.module.css';

const GOOGLE_CALENDAR_URL = 'https://calendar.google.com/calendar/u/0/r';
const SECTION_HEADING_PATTERN = /^([①②③④⑤⑥⑦⑧])\s*(.+)$/u;

function normalizeContent(content) {
  if (content && typeof content === 'object') {
    return {
      text: content.text || '',
      pendingAction: content.pendingAction || null,
      calendarToolResult: content.calendarToolResult || null,
      isStreaming: Boolean(content.isStreaming),
      onRegisterCalendar: content.onRegisterCalendar,
    };
  }

  return {
    text: String(content ?? ''),
    pendingAction: null,
    calendarToolResult: null,
    isStreaming: false,
    onRegisterCalendar: null,
  };
}

function getRegisteredCount(calendarToolResult) {
  return (
    calendarToolResult?.registered_event_count ??
    calendarToolResult?.created_count ??
    calendarToolResult?.registered_events?.length ??
    0
  );
}

function getCalendarStatusText(calendarToolResult) {
  if (!calendarToolResult) {
    return '';
  }

  const registeredCount = getRegisteredCount(calendarToolResult);

  if (calendarToolResult.status === 'registered') {
    return `캘린더 등록 완료: ${registeredCount}건`;
  }

  if (calendarToolResult.status === 'partial_success') {
    return `일부 일정만 등록되었습니다: ${registeredCount}건`;
  }

  if (calendarToolResult.status === 'failed') {
    return '캘린더 등록에 실패했습니다. 연결 상태를 확인해 주세요.';
  }

  if (calendarToolResult.status === 'dry_run') {
    return '캘린더 등록 준비가 완료되었습니다.';
  }

  if (calendarToolResult.status === 'calendar_connection_required') {
    return 'Google Calendar 연결이 필요합니다.';
  }

  return '';
}

function getGoogleCalendarUrl(calendarToolResult) {
  const firstRegisteredEvent = calendarToolResult?.registered_events?.find(
    (event) => event?.html_link,
  );
  return firstRegisteredEvent?.html_link || GOOGLE_CALENDAR_URL;
}

function renderFormattedText(text) {
  let isCalendarSection = false;

  return String(text || '')
    .split(/\r?\n/)
    .map((line, index) => {
      const trimmed = line.trim();
      const sectionHeading = trimmed.match(SECTION_HEADING_PATTERN);

      if (sectionHeading) {
        isCalendarSection = sectionHeading[2].includes('캘린더');
        return (
          <h3 className={styles.answerHeading} key={`${line}-${index}`}>
            <span className={styles.headingNumber}>{sectionHeading[1]}</span>
            <span className={styles.headingTitle}>{sectionHeading[2]}</span>
          </h3>
        );
      }

      if (isCalendarSection && trimmed.startsWith('-')) {
        return null;
      }

      if (!trimmed) {
        return <span className={styles.answerSpacer} key={`space-${index}`} />;
      }

      if (isCalendarSection && /^\d+\.\s+.+:\s*\d{4}-\d{2}-\d{2}$/u.test(trimmed)) {
        return (
          <span className={styles.calendarEventLine} key={`${line}-${index}`}>
            {line}
          </span>
        );
      }

      return (
        <span className={styles.answerLine} key={`${line}-${index}`}>
          {line}
        </span>
      );
    });
}

function BAssistantAnswer({ content }) {
  const {
    text,
    pendingAction,
    calendarToolResult,
    isStreaming,
    onRegisterCalendar,
  } = normalizeContent(content);
  const calendarStatusText = getCalendarStatusText(calendarToolResult);
  const canRegister = pendingAction?.status === 'pending' && !isStreaming;
  const canOpenCalendar =
    calendarToolResult?.status === 'registered' ||
    calendarToolResult?.status === 'partial_success';

  if (isStreaming && !text.trim()) {
    return null;
  }

  return (
    <motion.article
      className={styles.answer}
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      whileHover={{ y: -2 }}
    >
      <span className={styles.label}>
        <FiEdit3 aria-hidden="true" />
        계약 중 점검
      </span>

      <div className={styles.answerText}>
        {renderFormattedText(text || '답변을 생성하고 있습니다.')}
      </div>

      {canRegister && (
        <button
          className={styles.calendarButton}
          type="button"
          onClick={() => onRegisterCalendar?.(pendingAction)}
        >
          <FiCalendar aria-hidden="true" />
          일정 등록하기
        </button>
      )}

      {(calendarStatusText || canOpenCalendar) && (
        <div className={styles.calendarResultActions}>
          {calendarStatusText && (
            <p className={styles.calendarStatus}>
              <FiCheckCircle aria-hidden="true" />
              {calendarStatusText}
            </p>
          )}
          {canOpenCalendar && (
            <a
              className={styles.calendarLink}
              href={getGoogleCalendarUrl(calendarToolResult)}
              target="_blank"
              rel="noreferrer"
            >
              <FiExternalLink aria-hidden="true" />
              Google Calendar에서 확인하기
            </a>
          )}
        </div>
      )}
    </motion.article>
  );
}

export default BAssistantAnswer;
