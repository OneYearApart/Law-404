import { motion } from 'framer-motion';
import { FiCalendar, FiCheckCircle, FiEdit3 } from 'react-icons/fi';

import styles from './AssistantAnswer.module.css';

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

function getCalendarStatusText(calendarToolResult) {
  if (!calendarToolResult) {
    return '';
  }

  const registeredCount =
    calendarToolResult.registered_event_count ??
    calendarToolResult.created_count ??
    calendarToolResult.registered_events?.length ??
    0;

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
    return 'Google Calendar 연결이 필요합니다. 아래 연결 정보를 먼저 저장해 주세요.';
  }

  return '';
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
      <p className={styles.answerText}>
        {text || '답변을 생성하고 있습니다.'}
      </p>
      {canRegister && (
        <button
          className={styles.calendarButton}
          type="button"
          onClick={() => onRegisterCalendar?.(pendingAction)}
        >
          <FiCalendar aria-hidden="true" />
          캘린더에 등록하기
        </button>
      )}
      {calendarStatusText && (
        <p className={styles.calendarStatus}>
          <FiCheckCircle aria-hidden="true" />
          {calendarStatusText}
        </p>
      )}
    </motion.article>
  );
}

export default BAssistantAnswer;
