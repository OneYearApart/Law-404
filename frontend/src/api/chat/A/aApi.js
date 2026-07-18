import { apiRequest } from '../../common/apiClient.js';

const A_BASE_PATH = '/chat/a';

const INTERNAL_WARNING_MARKERS = [
  '슬롯',
  'RAG',
  'rag',
  'document_ids',
  'generation_status',
  '검색기',
];

function unwrap(payload) {
  return payload?.data ?? payload;
}

function normalizePublicWarnings(items) {
  return [...new Set((items || []).filter((warning) => {
    const text = String(warning || '').trim();
    return text && !INTERNAL_WARNING_MARKERS.some((marker) => text.includes(marker));
  }))];
}

function displayProgressValue(value, status) {
  if (status === 'not_applicable') {
    return '해당 없음';
  }
  if (value === true) {
    return '확인함';
  }
  if (value === false) {
    return '확인하지 못함';
  }
  if (Array.isArray(value)) {
    return value.join(', ');
  }
  return String(value ?? '확인함');
}

function deriveConsultationProgress(state = {}, consultation = {}) {
  const confirmedItems = [];
  const unresolvedItems = [];
  const remainingItems = [];
  const conflictItems = [];
  const issueSlots = state.issue_slots || {};

  Object.entries(issueSlots).forEach(([issueId, slots]) => {
    Object.values(slots || {}).forEach((slot) => {
      const base = {
        issue_id: issueId,
        slot_key: slot.key,
        label: slot.label || slot.key,
        status: slot.status || 'unknown',
        source: slot.source || null,
      };

      if (slot.status === 'conflict') {
        conflictItems.push(base);
        return;
      }

      const answeredButUnresolved =
        (slot.status === 'confirmed' && slot.value === false) ||
        (slot.status === 'uncertain' && slot.source === 'user');

      if (answeredButUnresolved) {
        unresolvedItems.push({
          ...base,
          value: slot.value,
          display_value: displayProgressValue(slot.value, slot.status),
        });
      } else if (slot.status === 'confirmed' || slot.status === 'not_applicable') {
        confirmedItems.push({
          ...base,
          value: slot.value,
          display_value: displayProgressValue(slot.value, slot.status),
        });
      } else {
        remainingItems.push(base);
      }
    });
  });

  return {
    completed_count: confirmedItems.length + unresolvedItems.length,
    total_count:
      confirmedItems.length + unresolvedItems.length + remainingItems.length + conflictItems.length,
    confirmed_items: confirmedItems,
    unresolved_items: unresolvedItems,
    remaining_items: remainingItems,
    conflict_items: conflictItems,
    risk_level: consultation.risk_assessment?.risk_level || null,
    public_conclusion: null,
    is_complete: remainingItems.length === 0 && conflictItems.length === 0,
  };
}


function publicCoreJudgment(answer = {}, progress = {}) {
  const raw = String(answer.core_judgment || '').trim();
  if (raw && !/핵심 확인 항목이 남아 있습니다|남은 항목을 확인한 뒤/u.test(raw)) {
    return raw;
  }

  const labels = (progress?.unresolved_items || [])
    .map((item) => item.label)
    .filter(Boolean)
    .slice(0, 3);
  if (labels.length) {
    return `${labels.join(', ')}을 확인하지 못했습니다. 해당 권한과 자료를 확인하기 전에는 계약서 서명과 송금을 보류하세요.`;
  }
  return raw || '입력한 사실과 관련 근거를 종합해 결론을 만들지 못했습니다.';
}

function normalizeNextQuestion(value, followUpQuestions = []) {
  const question = value || followUpQuestions[0] || null;
  if (!question) {
    return null;
  }
  if (typeof question === 'string') {
    return {
      question,
      label: '추가 확인',
      input_type: 'text',
      options: [],
      allow_custom_input: true,
    };
  }
  return {
    ...question,
    question: question.question || question.text || question.label || '',
    input_type: question.input_type || 'text',
    options: question.options || [],
    allow_custom_input: question.allow_custom_input !== false,
  };
}

function buildMappedAnswer({
  answer = {},
  consultation = {},
  state = {},
  processingStatus = null,
  answerReady = true,
  resultWarnings = [],
  consultationProgress = null,
  nextQuestion = null,
  isComplete = null,
}) {
  const followUpQuestions = (
    answer.follow_up_questions || consultation.follow_up_questions || []
  ).slice(0, 1);
  const progress = consultationProgress || deriveConsultationProgress(state, consultation);
  const normalizedNextQuestion = normalizeNextQuestion(nextQuestion, followUpQuestions);
  const completed = typeof isComplete === 'boolean'
    ? isComplete
    : Boolean(progress?.is_complete || !normalizedNextQuestion);

  const issueSlots = state.issue_slots || {};
  const confirmedUpdates = (consultation.applied_updates || []).map((update) => {
    const issueId = update.issue_id || update.issueId;
    const slotKey = update.slot_key || update.slotKey;
    const slot = issueSlots?.[issueId]?.[slotKey] || {};
    return {
      issueId,
      slotKey,
      label: slot.label || update.label || slotKey,
      value: update.current_value ?? update.value,
      status: update.current_status || update.status,
      conflictCreated: Boolean(update.conflict_created || update.conflictCreated),
      conflictResolved: Boolean(update.conflict_resolved || update.conflictResolved),
    };
  });

  const missingFacts = consultation.missing_facts || [];
  const knownFacts = consultation.known_facts || [];
  const requiredInformation = answer.required_information || [];

  const confirmedFacts = (progress?.confirmed_items || []).map(
    (item) => `${item.label}: ${item.display_value || displayProgressValue(item.value, item.status)}`,
  );
  const unresolvedFacts = (progress?.unresolved_items || []).map(
    (item) => `${item.label}: ${item.display_value || '확인하지 못함'}`,
  );

  return {
    riskLevel: answer.risk_level || consultation.risk_assessment?.risk_level || '확인 필요',
    coreJudgment: publicCoreJudgment(answer, progress),
    confirmationMessage: answer.confirmation_message || null,
    immediateActions: answer.immediate_actions || [],
    holdActions: answer.hold_actions || [],
    reasons: answer.reasons || [],
    requiredInformation,
    followUpQuestions,
    references: answer.references || [],
    documentSummary: answer.document_summary || null,
    knownFacts: confirmedFacts.length ? confirmedFacts : knownFacts,
    unresolvedFacts,
    missingFacts,
    confirmedUpdates,
    remainingQuestionCount:
      (progress?.remaining_items?.length || 0) + (progress?.conflict_items?.length || 0),
    reviewItems: missingFacts.length ? missingFacts : requiredInformation,
    consultationProgress: progress,
    nextQuestion: normalizedNextQuestion,
    isComplete: completed,
    turnCount: Number(state.turn_count || consultation.turn_count || 1),
    answerPhase: completed ? 'complete' : 'collecting',
    warnings: normalizePublicWarnings([
      ...resultWarnings,
      ...(consultation.warnings || []),
    ]),
    evidenceStatus: consultation.rag_response?.evidence_status,
    generationStatus: consultation.rag_response?.generation_status,
    processingStatus,
    answerReady,
  };
}

export async function createAConversation({
  primaryIssueId = 'q15_after_contract_procedure',
  relatedIssueIds = [],
} = {}) {
  const payload = await apiRequest(`${A_BASE_PATH}/conversations`, {
    method: 'POST',
    body: {
      primary_issue_id: primaryIssueId,
      related_issue_ids: relatedIssueIds,
    },
  });

  return unwrap(payload);
}

export async function listAConversations() {
  const payload = await apiRequest(`${A_BASE_PATH}/conversations`);
  const data = unwrap(payload);
  return Array.isArray(data) ? data : [];
}

export async function sendATurn({
  question,
  conversationId = null,
  issueId = null,
  relatedIssueIds = [],
  checklistUpdates = [],
  documentIds = [],
  attachedDocumentIds = [],
  analyzeDocuments = false,
  forceDocumentAnalysis = false,
}) {
  const payload = await apiRequest(`${A_BASE_PATH}/turn`, {
    method: 'POST',
    body: {
      question,
      conversation_id: conversationId,
      issue_id: issueId,
      related_issue_ids: relatedIssueIds,
      checklist_updates: checklistUpdates,
      document_ids: documentIds,
      attached_document_ids: attachedDocumentIds,
      analyze_documents: analyzeDocuments,
      force_document_analysis: forceDocumentAnalysis,
    },
  });

  return unwrap(payload);
}

export async function getAConversation(conversationId) {
  const payload = await apiRequest(`${A_BASE_PATH}/conversations/${conversationId}`);
  return unwrap(payload);
}

export async function uploadADocument({
  conversationId,
  file,
  documentType,
}) {
  const formData = new FormData();
  formData.append('document_type', documentType);
  formData.append('file', file);

  const payload = await apiRequest(
    `${A_BASE_PATH}/conversations/${conversationId}/documents`,
    {
      method: 'POST',
      body: formData,
    },
  );

  return unwrap(payload);
}

export async function listADocuments(conversationId) {
  const payload = await apiRequest(
    `${A_BASE_PATH}/conversations/${conversationId}/documents`,
  );

  return unwrap(payload);
}

export async function deleteADocument({ conversationId, documentId }) {
  const payload = await apiRequest(
    `${A_BASE_PATH}/conversations/${conversationId}/documents/${documentId}`,
    { method: 'DELETE' },
  );

  return unwrap(payload);
}

export function normalizeADocument(document) {
  if (!document || typeof document !== 'object') {
    return null;
  }

  return {
    ...document,
    document_id: document.document_id || document.id,
    original_filename: document.original_filename || document.safe_filename || '첨부 문서.pdf',
    document_type: document.document_type || 'lease_contract',
    processing_status: document.processing_status || 'uploaded',
    analysis_status: document.analysis_status || 'pending',
  };
}

export function getUploadedADocument(uploadResult) {
  return normalizeADocument(
    uploadResult?.upload?.document ||
      uploadResult?.document ||
      uploadResult?.upload ||
      uploadResult,
  );
}

export function normalizeADocumentList(payload) {
  const list = Array.isArray(payload)
    ? payload
    : payload?.documents || payload?.state?.documents || [];

  return list.map(normalizeADocument).filter(Boolean);
}

export function mapATurnToAnswer(result) {
  const consultation = result?.consultation ?? {};
  const ragResponse = consultation.rag_response ?? {};
  return buildMappedAnswer({
    answer: ragResponse.answer ?? {},
    consultation,
    state: consultation.state ?? {},
    processingStatus: result?.processing_status,
    answerReady: result?.answer_ready,
    resultWarnings: result?.warnings || [],
    consultationProgress: result?.consultation_progress || null,
    nextQuestion: result?.next_question || null,
    isComplete: result?.is_complete,
  });
}

export function mapAHistorySnapshotToAnswer(snapshot) {
  return buildMappedAnswer({
    answer: snapshot?.answer || {},
    consultation: {
      applied_updates: snapshot?.applied_updates || [],
      known_facts: snapshot?.known_facts || [],
      missing_facts: snapshot?.missing_facts || [],
      conflict_facts: snapshot?.conflict_facts || [],
      follow_up_questions: snapshot?.follow_up_questions || [],
      risk_assessment: snapshot?.risk_assessment || {},
      warnings: snapshot?.warnings || [],
    },
    state: { turn_count: snapshot?.turn_count || 1 },
    processingStatus: snapshot?.processing_status,
    answerReady: snapshot?.answer_ready,
    resultWarnings: snapshot?.warnings || [],
    consultationProgress: snapshot?.consultation_progress || null,
    nextQuestion: snapshot?.next_question || null,
    isComplete: snapshot?.is_complete,
  });
}

export function mapAConversationStateToMessages(state) {
  const history = state?.turn_history || [];
  const storedMessages = state?.messages || [];
  const historyMessageCount = history.length * 2;
  const legacyPrefixCount = Math.max(0, storedMessages.length - historyMessageCount);
  const legacyMessages = storedMessages.slice(0, legacyPrefixCount).map((message, index) => ({
    id: `legacy-${state.conversation_id}-${index}`,
    role: message.role,
    content: message.content,
  }));

  if (history.length) {
    const restoredHistory = history.flatMap((snapshot, index) => [
      {
        id: `saved-${state.conversation_id}-${index}-user`,
        role: 'user',
        content: (snapshot.attached_documents || []).length
          ? {
              text: snapshot.user_message,
              attachments: normalizeADocumentList(snapshot.attached_documents),
            }
          : snapshot.user_message,
      },
      {
        id: `saved-${state.conversation_id}-${index}-assistant`,
        role: 'assistant',
        content: mapAHistorySnapshotToAnswer(snapshot),
      },
    ]);
    return [...legacyMessages, ...restoredHistory];
  }

  return storedMessages.map((message, index) => ({
    id: `legacy-${state.conversation_id}-${index}`,
    role: message.role,
    content: message.content,
  }));
}
