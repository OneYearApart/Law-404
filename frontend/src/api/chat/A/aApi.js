import { apiRequest } from '../../common/apiClient.js';

const A_BASE_PATH = '/chat/a';

function unwrap(payload) {
  return payload?.data ?? payload;
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

export async function sendATurn({
  question,
  conversationId = null,
  issueId = null,
  relatedIssueIds = [],
  checklistUpdates = [],
  documentIds = [],
  analyzeDocuments = true,
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

export async function deleteAConversation(conversationId) {
  const payload = await apiRequest(`${A_BASE_PATH}/conversations/${conversationId}`, {
    method: 'DELETE',
  });

  return unwrap(payload);
}

export async function uploadADocument({
  conversationId,
  file,
  documentType,
  extractText = true,
  forceExtraction = false,
}) {
  const formData = new FormData();
  formData.append('document_type', documentType);
  formData.append('file', file);

  const query = new URLSearchParams({
    extract_text: String(extractText),
    force_extraction: String(forceExtraction),
  });

  const payload = await apiRequest(
    `${A_BASE_PATH}/conversations/${conversationId}/documents?${query}`,
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

export async function extractADocument({ conversationId, documentId, force = false }) {
  const query = new URLSearchParams({ force: String(force) });
  const payload = await apiRequest(
    `${A_BASE_PATH}/conversations/${conversationId}/documents/${documentId}/extract?${query}`,
    { method: 'POST' },
  );

  return unwrap(payload);
}

export async function analyzeADocuments({
  conversationId,
  documentIds = [],
  force = false,
}) {
  const payload = await apiRequest(
    `${A_BASE_PATH}/conversations/${conversationId}/documents/analyze`,
    {
      method: 'POST',
      body: {
        document_ids: documentIds,
        force,
      },
    },
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
  const answer = ragResponse.answer ?? {};

  return {
    riskLevel: answer.risk_level || consultation.risk_assessment?.risk_level || '확인 필요',
    coreJudgment: answer.core_judgment || '답변을 확인하지 못했습니다.',
    immediateActions: answer.immediate_actions || [],
    holdActions: answer.hold_actions || [],
    reasons: answer.reasons || [],
    requiredInformation: answer.required_information || [],
    followUpQuestions: answer.follow_up_questions || consultation.follow_up_questions || [],
    references: answer.references || [],
    documentSummary: answer.document_summary || null,
    warnings: [
      ...new Set(
        (
          result?.warnings?.length
            ? result.warnings
            : [...(consultation.warnings || []), ...(ragResponse.warnings || [])]
        ).filter(
          (warning) =>
            warning &&
            !String(warning).startsWith(
              '일부 문장을 현재 슬롯에 연결하지 못했습니다:',
            ),
        ),
      ),
    ],
    evidenceStatus: ragResponse.evidence_status,
    generationStatus: ragResponse.generation_status,
    processingStatus: result?.processing_status,
    answerReady: result?.answer_ready,
  };
}
