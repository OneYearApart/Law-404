import { AnimatePresence, motion } from 'framer-motion';
import { useEffect, useRef, useState } from 'react';
import { FiAlertCircle, FiCheckCircle, FiPaperclip } from 'react-icons/fi';
import { RiShieldCheckLine } from 'react-icons/ri';

import {
  analyzeADocuments,
  createAConversation,
  deleteADocument,
  getAConversation,
  getUploadedADocument,
  listADocuments,
  mapAConversationStateToMessages,
  mapATurnToAnswer,
  normalizeADocumentList,
  sendATurn,
  uploadADocument,
} from '../../api/chat/A/aApi.js';
import {
  createDConversation,
  createEmptyDAnswer,
  reduceDAnswer,
  streamDChat,
} from '../../api/chat/D/dApi.js';
import { ApiError } from '../../api/common/apiClient.js';
import ChatComposer from '../../components/chat/ChatComposer/ChatComposer.jsx';
import AssistantThinking from '../../components/chat/AssistantThinking/AssistantThinking.jsx';
import DocumentAttachmentList from '../../components/chat/DocumentAttachmentList/DocumentAttachmentList.jsx';
import DocumentUploadDialog from '../../components/chat/DocumentUploadDialog/DocumentUploadDialog.jsx';
import MessageBubble from '../../components/chat/MessageBubble/MessageBubble.jsx';
import { CHATBOT_CATEGORIES, createEmptyConversations } from '../../constants/chatbot.js';
import { useChatConversation } from '../../contexts/chatConversationContext.js';
import { CHATBOT_ANSWER_COMPONENTS } from './answerVariants.js';
import styles from './ChatbotPage.module.css';

const MAX_FILE_SIZE = 20 * 1024 * 1024;

const STARTER_GUIDES = Object.freeze({
  'before-contract': {
    eyebrow: '계약 전 상담',
    title: '계약 전, 무엇이 걱정되시나요?',
    description:
      '현재 상황을 한 문장으로 알려 주세요. 필요한 확인 항목을 하나씩 묻고, 마지막에 확인 결과와 다음 행동을 정리해 드립니다.',
    examples: [
      '집주인 가족이 대신 계약하러 왔어요.',
      '공동명의인데 소유자 한 명만 계약하러 왔어요.',
      '계약금을 다른 사람 계좌로 보내라고 해요.',
    ],
  },
  'during-contract': {
    eyebrow: '계약 중 상담',
    title: '계약서에서 무엇을 확인할까요?',
    description:
      '작성 중인 계약 내용이나 걱정되는 조항을 알려 주세요. 확인할 부분과 수정이 필요한 행동을 정리해 드립니다.',
    examples: [
      '계약서 금액과 설명받은 금액이 달라요.',
      '특약에 불리한 내용이 있는지 확인하고 싶어요.',
      '계약금을 지금 바로 보내도 되는지 궁금해요.',
    ],
  },
  'after-contract': {
    eyebrow: '계약 후 상담',
    title: '계약 후, 무엇부터 해야 할까요?',
    description:
      '계약 직후부터 입주 전까지 필요한 절차를 알려 주세요. 놓치기 쉬운 일정과 다음 행동을 정리해 드립니다.',
    examples: [
      '계약 후 가장 먼저 해야 할 일이 무엇인가요?',
      '전입신고와 확정일자는 언제 해야 하나요?',
      '계약 후 집주인이 바뀌었다고 연락이 왔어요.',
    ],
  },
  'jeonse-fraud': {
    eyebrow: '전세사기 상담',
    title: '어떤 상황이 의심되시나요?',
    description:
      '의심되는 요청이나 위험 신호를 알려 주세요. 우선 멈춰야 할 행동과 공식 확인 경로를 정리해 드립니다.',
    examples: [
      '계약 직전에 계좌를 바꿔 달라고 해요.',
      '등기부에 근저당이 많은데 계약해도 되나요?',
      '보증보험 가입이 어렵다고 들었어요.',
    ],
  },
});

function createPendingFile(file) {
  const loweredName = file.name.toLowerCase();
  const guessedType =
    loweredName.includes('등기') || loweredName.includes('registry')
      ? 'registry'
      : 'lease_contract';

  return {
    id: `${Date.now()}-${Math.random().toString(36).slice(2)}`,
    file,
    documentType: guessedType,
  };
}

function getErrorMessage(error, fallback) {
  return error instanceof ApiError ? error.message : error?.message || fallback;
}

function normalizeReviewItem(item) {
  return String(item || '')
    .replace(/^\[[^\]]+\]\s*/, '')
    .replace(/\s+/g, ' ')
    .trim();
}

function uniqueReviewItems(items, maxItems = 4) {
  return [...new Set(items.map(normalizeReviewItem).filter(Boolean))].slice(0, maxItems);
}

function findCompletedResult(progress, question) {
  if (!progress || !question) {
    return null;
  }

  const slotKey = question.slot_key || question.slotKey;
  const questionKey = question.question_key || question.questionKey;
  const groups = [
    ['확인된 정보', progress.confirmed_items || []],
    ['확인하지 못한 정보', progress.unresolved_items || []],
    ['추가 확인 필요', progress.conflict_items || []],
  ];

  for (const [groupLabel, items] of groups) {
    const matched = items.find((item) =>
      (slotKey && item?.slot_key === slotKey)
      || (questionKey && item?.question_key === questionKey),
    );
    if (matched) {
      return {
        groupLabel,
        label: matched.label || question.label || '확인 항목',
        displayValue: matched.display_value || matched.value || groupLabel,
      };
    }
  }

  return null;
}

function inferInitialAReviewItems(question) {
  const normalized = String(question || '').toLowerCase();

  if (/대리|위임|아들|딸|가족|대신/.test(normalized)) {
    return [
      '등기부등본상 실제 소유자',
      '소유자 본인의 대리 계약 의사',
      '위임 범위와 서명 권한',
      '계약금 계좌 예금주와 대금 수령 권한',
    ];
  }

  if (/계좌|예금주|송금|계약금|잔금/.test(normalized)) {
    return [
      '계약 상대방과 계좌 예금주의 관계',
      '계약금 또는 잔금 수령 권한',
      '계좌 변경 요청의 기록과 확인 경로',
      '송금 전 보류해야 할 위험 신호',
    ];
  }

  if (/등기|근저당|압류|가압류|신탁|권리/.test(normalized)) {
    return [
      '등기부등본상 현재 소유자',
      '현재 유효한 근저당과 권리 제한',
      '신탁등기 및 말소 여부',
      '계약·송금 전 추가 확인 항목',
    ];
  }

  if (/계약서|문서|pdf|특약|보증금/.test(normalized)) {
    return [
      '계약 당사자와 목적물 정보',
      '보증금·계약금·잔금과 주요 일정',
      '특약과 위험 문구',
      '문서 내용과 추가 확인이 필요한 항목',
    ];
  }

  return [
    '현재 계약 단계와 질문의 핵심 사실',
    '관련 법률·판례·공식 절차 근거',
    '계약 진행 또는 송금 보류 필요성',
    '다음으로 확인할 가장 중요한 항목',
  ];
}

function buildAThinkingItems(messages) {
  const lastUserMessage = [...messages].reverse().find((message) => message.role === 'user');
  const lastAssistantMessage = [...messages]
    .reverse()
    .find((message) => message.role === 'assistant' && typeof message.content === 'object');
  const previousAnswer = lastAssistantMessage?.content;

  const unresolved = uniqueReviewItems(previousAnswer?.missingFacts || []);
  if (unresolved.length > 0) {
    return unresolved;
  }

  const required = uniqueReviewItems(previousAnswer?.requiredInformation || []);
  if (required.length > 0) {
    return required;
  }

  return inferInitialAReviewItems(lastUserMessage?.content);
}

function ChatbotPage({ consultationType }) {
  const messagesEndRef = useRef(null);
  const localMessageSequenceRef = useRef(0);
  const config = CHATBOT_CATEGORIES[consultationType];
  const starterGuide = STARTER_GUIDES[consultationType] || STARTER_GUIDES['before-contract'];
  const AssistantAnswer = CHATBOT_ANSWER_COMPONENTS[consultationType];
  const isAPart = consultationType === 'before-contract';
  const isDPart = consultationType === 'jeonse-fraud';
  const {
    activeAConversationId,
    newConversationVersion,
    activateAConversation,
    notifyAConversationSaved,
  } = useChatConversation();
  const [input, setInput] = useState('');
  const [messagesByType, setMessagesByType] = useState(createEmptyConversations);
  const [conversationIds, setConversationIds] = useState({});
  const [documents, setDocuments] = useState([]);
  const [pendingFiles, setPendingFiles] = useState([]);
  const [isUploadDialogOpen, setIsUploadDialogOpen] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [attachDocumentAnalysisNextTurn, setAttachDocumentAnalysisNextTurn] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const messages = messagesByType[consultationType] ?? [];
  const isBusy = isLoading || isUploading || isAnalyzing;
  const currentConversationId = conversationIds[consultationType] || null;
  const aThinkingItems = isAPart ? buildAThinkingItems(messages) : [];
  const latestAssistantIndex = messages.reduce(
    (latest, message, index) => (message.role === 'assistant' ? index : latest),
    -1,
  );
  const latestAssistantAnswer = latestAssistantIndex >= 0
    ? messages[latestAssistantIndex]?.content
    : null;
  const aThinkingProgress = isAPart && typeof latestAssistantAnswer === 'object'
    ? latestAssistantAnswer?.consultationProgress || null
    : null;

  // '새 상담'은 사이드바 컨텍스트(A 전용)를 거치는데 아래 복원 effect가 A에서만 동작해,
  // B·C·D는 버튼이 무반응이었다. 대화이력 연동이 없어도 "새로 시작"은 되어야 하므로
  // 파트 중립 신호인 newConversationVersion만 보고 현재 파트를 직접 초기화한다.
  // (A는 아래 effect가 activeAConversationId=null 경로로 처리하므로 건너뛴다 — 중복 초기화 방지)
  // effect가 아니라 렌더 중 조정인 이유: 초기화를 effect로 미루면 이전 대화가 한 프레임
  // 그려졌다 사라진다. 이 시점에 바로 리셋하면 React가 커밋 전에 다시 렌더한다.
  const [lastNewConversationVersion, setLastNewConversationVersion] = useState(newConversationVersion);
  if (!isAPart && lastNewConversationVersion !== newConversationVersion) {
    setLastNewConversationVersion(newConversationVersion);
    setMessagesByType((current) => ({ ...current, [consultationType]: [] }));
    setConversationIds((current) => ({ ...current, [consultationType]: null }));
    setError('');
    setNotice('');
  }

  useEffect(() => {
    if (!isAPart) {
      return undefined;
    }

    let cancelled = false;

    const restoreConversation = async () => {
      if (!activeAConversationId) {
        setMessagesByType((current) => ({ ...current, [consultationType]: [] }));
        setConversationIds((current) => ({ ...current, [consultationType]: null }));
        setDocuments([]);
        setAttachDocumentAnalysisNextTurn(false);
        setError('');
        setNotice('');
        return;
      }

      if (String(activeAConversationId) === String(currentConversationId || '')) {
        return;
      }

      try {
        const state = await getAConversation(activeAConversationId);
        if (cancelled) {
          return;
        }
        setMessagesByType((current) => ({
          ...current,
          [consultationType]: mapAConversationStateToMessages(state),
        }));
        setConversationIds((current) => ({
          ...current,
          [consultationType]: String(state.conversation_id),
        }));
        setDocuments(normalizeADocumentList(state.documents || []));
        setAttachDocumentAnalysisNextTurn(false);
        setError('');
      } catch (requestError) {
        if (!cancelled) {
          setError(getErrorMessage(requestError, '저장된 상담을 불러오지 못했습니다.'));
        }
      }
    };

    restoreConversation();
    return () => {
      cancelled = true;
    };
  }, [
    activeAConversationId,
    consultationType,
    currentConversationId,
    isAPart,
    newConversationVersion,
  ]);

  // D파트 스트리밍은 메시지 개수가 아니라 마지막 답변의 길이가 늘어나므로 그것도 같이 따라간다.
  const streamedLength = messages[messages.length - 1]?.content?.text?.length ?? 0;

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
  }, [messages.length, isLoading, streamedLength]);

  const appendMessages = (...nextMessages) => {
    setMessagesByType((current) => ({
      ...current,
      [consultationType]: [
        ...(current[consultationType] ?? []),
        ...nextMessages,
      ],
    }));
  };

  // D파트는 SSE라 답변이 토큰 단위로 들어온다. 이미 붙여둔 말풍선을 제자리에서 갱신한다.
  const updateMessage = (id, updater) => {
    setMessagesByType((current) => ({
      ...current,
      [consultationType]: (current[consultationType] ?? []).map((message) =>
        message.id === id ? { ...message, content: updater(message.content) } : message,
      ),
    }));
  };

  const saveConversationId = (conversationId) => {
    setConversationIds((current) => ({
      ...current,
      [consultationType]: conversationId,
    }));
  };

  const ensureAConversation = async () => {
    if (currentConversationId) {
      return currentConversationId;
    }

    const created = await createAConversation();
    saveConversationId(created.conversation_id);
    activateAConversation(created.conversation_id);
    await notifyAConversationSaved(created.conversation_id);
    return created.conversation_id;
  };

  // D파트 엔드포인트는 대화방을 만들어주지 않으므로 첫 질문 전에 발급받아 둔다.
  // 사이드바 대화이력(ChatConversationContext)은 A파트 전용이라 여기서는 건드리지 않는다.
  const ensureDConversation = async () => {
    if (currentConversationId) {
      return currentConversationId;
    }

    const conversationId = await createDConversation();
    saveConversationId(conversationId);
    return conversationId;
  };

  const refreshDocuments = async (conversationId) => {
    const response = await listADocuments(conversationId);
    const nextDocuments = normalizeADocumentList(response);
    setDocuments(nextDocuments);
    return nextDocuments;
  };

  const submitQuestion = async (rawQuestion) => {
    const question = String(rawQuestion || '').trim();

    if (!question || isBusy) {
      return;
    }

    localMessageSequenceRef.current += 1;
    const messageKey = `local-${localMessageSequenceRef.current}`;
    const assistantId = `${messageKey}-assistant`;
    appendMessages({ id: `${messageKey}-user`, role: 'user', content: question });
    setInput('');
    setError('');
    setNotice('');
    setIsLoading(true);

    try {
      if (isDPart) {
        // 빈 답변 카드를 먼저 띄우고 스트림이 도착하는 대로 채운다.
        appendMessages({ id: assistantId, role: 'assistant', content: createEmptyDAnswer() });

        const conversationId = await ensureDConversation();

        await streamDChat({
          conversationId,
          userInput: question,
          onEvent: (streamEvent) =>
            updateMessage(assistantId, (answer) => reduceDAnswer(answer, streamEvent)),
        });
      } else if (isAPart) {
        const result = await sendATurn({
          question,
          conversationId: currentConversationId,
          documentIds: documents.map((document) => document.document_id),
          analyzeDocuments: documents.length > 0 && attachDocumentAnalysisNextTurn,
          forceDocumentAnalysis: false,
        });

        saveConversationId(result.conversation_id);
        notifyAConversationSaved(result.conversation_id);
        if (attachDocumentAnalysisNextTurn) {
          setAttachDocumentAnalysisNextTurn(false);
        }

        if (result.consultation?.state?.documents) {
          setDocuments(normalizeADocumentList(result.consultation.state.documents));
        }

        appendMessages({
          id: `${messageKey}-assistant`,
          role: 'assistant',
          content: mapATurnToAnswer(result),
        });
      } else {
        appendMessages({
          id: `${messageKey}-assistant`,
          role: 'assistant',
          content: config.reply,
        });
      }
    } catch (requestError) {
      const message = getErrorMessage(requestError, '상담 답변을 불러오지 못했습니다.');
      setError(message);

      // D파트는 카드를 이미 띄워둔 상태라 그대로 두면 빈 카드가 남는다.
      if (isDPart) {
        updateMessage(assistantId, (answer) => ({
          ...answer,
          status: 'error',
          errorMessage: message,
        }));
      }
    } finally {
      setIsLoading(false);
    }
  };

  const handleSubmit = async (event) => {
    event.preventDefault();
    await submitQuestion(input);
  };

  const handleQuickAnswer = async (answerText) => {
    await submitQuestion(answerText);
  };

  const handleFilesSelected = (files) => {
    setError('');
    setNotice('');

    if (!isAPart) {
      setNotice('문서 업로드는 현재 계약 전 A 상담에서만 사용할 수 있습니다.');
      return;
    }

    const invalidFile = files.find((file) => {
      const isPdf = file.type === 'application/pdf' || file.name.toLowerCase().endsWith('.pdf');
      return !isPdf || file.size <= 0 || file.size > MAX_FILE_SIZE;
    });

    if (invalidFile) {
      setError('PDF 파일만 업로드할 수 있으며 파일 하나당 최대 20MB까지 가능합니다.');
      return;
    }

    setPendingFiles(files.map(createPendingFile));
    setIsUploadDialogOpen(true);
  };

  const handlePendingTypeChange = (id, documentType) => {
    setPendingFiles((current) =>
      current.map((item) => (item.id === id ? { ...item, documentType } : item)),
    );
  };

  const handlePendingRemove = (id) => {
    setPendingFiles((current) => {
      const next = current.filter((item) => item.id !== id);
      if (next.length === 0) {
        setIsUploadDialogOpen(false);
      }
      return next;
    });
  };

  const handleUploadConfirm = async () => {
    if (!pendingFiles.length || isUploading) {
      return;
    }

    setIsUploading(true);
    setError('');
    setNotice('');

    let conversationId = currentConversationId;
    const uploadedDocuments = [];

    try {
      conversationId = await ensureAConversation();

      for (const item of pendingFiles) {
        const uploadResult = await uploadADocument({
          conversationId,
          file: item.file,
          documentType: item.documentType,
          extractText: true,
          forceExtraction: false,
        });
        const uploaded = getUploadedADocument(uploadResult);
        if (uploaded) {
          uploadedDocuments.push(uploaded);
          setDocuments((current) => [
            ...current.filter((document) => document.document_id !== uploaded.document_id),
            uploaded,
          ]);
        }
      }

      setIsUploadDialogOpen(false);
      setPendingFiles([]);
      setIsAnalyzing(true);

      await analyzeADocuments({
        conversationId,
        documentIds: [],
        force: false,
      });

      const refreshed = await refreshDocuments(conversationId);
      setAttachDocumentAnalysisNextTurn(true);
      setNotice(
        `${refreshed.length || uploadedDocuments.length}개 문서의 업로드와 분석이 완료됐습니다. 이제 문서에 대해 질문해 주세요.`,
      );
    } catch (requestError) {
      setError(getErrorMessage(requestError, '문서를 업로드하거나 분석하지 못했습니다.'));

      if (conversationId) {
        try {
          await refreshDocuments(conversationId);
        } catch {
          // 원래 업로드 오류를 유지한다.
        }
      }

    } finally {
      setIsUploading(false);
      setIsAnalyzing(false);
    }
  };

  const handleAnalyzeDocuments = async () => {
    if (!currentConversationId || !documents.length || isBusy) {
      return;
    }

    setIsAnalyzing(true);
    setError('');
    setNotice('');

    try {
      await analyzeADocuments({
        conversationId: currentConversationId,
        documentIds: documents.map((document) => document.document_id),
        force: true,
      });
      await refreshDocuments(currentConversationId);
      setAttachDocumentAnalysisNextTurn(true);
      setNotice('첨부 문서를 다시 분석했습니다. 다음 질문 한 번에 최신 분석 결과를 연결합니다.');
    } catch (requestError) {
      setError(getErrorMessage(requestError, '문서를 다시 분석하지 못했습니다.'));
    } finally {
      setIsAnalyzing(false);
    }
  };

  const handleDeleteDocument = async (documentId) => {
    if (!currentConversationId || isBusy) {
      return;
    }

    setIsUploading(true);
    setError('');
    setNotice('');

    try {
      await deleteADocument({
        conversationId: currentConversationId,
        documentId,
      });
      const refreshed = await refreshDocuments(currentConversationId);
      if (!refreshed.length) {
        setAttachDocumentAnalysisNextTurn(false);
      }
      setNotice(
        refreshed.length
          ? '문서를 삭제했습니다. 남은 문서로 상담을 계속할 수 있습니다.'
          : '첨부 문서를 모두 삭제했습니다.',
      );
    } catch (requestError) {
      setError(getErrorMessage(requestError, '문서를 삭제하지 못했습니다.'));
    } finally {
      setIsUploading(false);
    }
  };

  return (
    <main className={styles.page} aria-label={config.title}>
      <section className={styles.messages} aria-live="polite">
        {messages.length === 0 && !isLoading && (
          <section className={styles.emptyState}>
            <span className={styles.emptyStateIcon} aria-hidden="true">
              <RiShieldCheckLine />
            </span>
            <p className={styles.emptyStateEyebrow}>{starterGuide.eyebrow}</p>
            <h1>{starterGuide.title}</h1>
            <p className={styles.emptyStateDescription}>{starterGuide.description}</p>
            <div className={styles.exampleQuestions} aria-label="예시 질문">
              {starterGuide.examples.map((example) => (
                <button
                  type="button"
                  key={example}
                  onClick={() => submitQuestion(example)}
                  disabled={isBusy}
                >
                  {example}
                </button>
              ))}
            </div>
            <p className={styles.emptyStateHint}>예시를 선택하거나 아래 입력창에 직접 질문해 주세요.</p>
          </section>
        )}

        {messages.map((message, index) => {
          const isCompletedCollectingQuestion = isAPart
            && message.role === 'assistant'
            && message.content?.answerPhase === 'collecting'
            && messages[index + 1]?.role === 'user';
          const completedAnswerMessage = isCompletedCollectingQuestion
            && messages[index + 1]?.role === 'user'
            ? messages[index + 1]
            : null;
          const nextAssistantMessage = isCompletedCollectingQuestion
            && messages[index + 2]?.role === 'assistant'
            && typeof messages[index + 2]?.content === 'object'
            ? messages[index + 2]
            : null;
          const completedResult = isCompletedCollectingQuestion
            ? findCompletedResult(
                nextAssistantMessage?.content?.consultationProgress,
                message.content?.nextQuestion,
              )
            : null;
          const displayContent = isCompletedCollectingQuestion
            ? {
                ...message.content,
                displayMode: 'completed-question',
                completedAnswer: completedAnswerMessage?.content || '',
                completedResult,
              }
            : message.content;
          const shouldAnimate = String(message.id || '').startsWith('local-');

          return (
            <MessageBubble
              key={message.id}
              role={message.role}
              content={displayContent}
              AssistantAnswer={AssistantAnswer}
              onQuickAnswer={isAPart ? handleQuickAnswer : undefined}
              isInteractive={isAPart && index === latestAssistantIndex && !isBusy}
              shouldAnimate={shouldAnimate}
            />
          );
        })}

        {isLoading && !isDPart && (
          <AssistantThinking
            progress={aThinkingProgress}
            fallbackItems={aThinkingItems}
          />
        )}
        <div ref={messagesEndRef} />
      </section>

      <AnimatePresence>
        {(error || notice) && (
          <motion.div
            className={`${styles.feedback} ${error ? styles.error : styles.notice}`}
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 8 }}
          >
            {error ? <FiAlertCircle aria-hidden="true" /> : notice.includes('완료') ? <FiCheckCircle aria-hidden="true" /> : <FiPaperclip aria-hidden="true" />}
            <span>{error || notice}</span>
          </motion.div>
        )}
      </AnimatePresence>

      <section className={styles.composerDock}>
        {isAPart && (
          <DocumentAttachmentList
            documents={documents}
            onDelete={handleDeleteDocument}
            onAnalyze={handleAnalyzeDocuments}
            isBusy={isBusy}
          />
        )}
        <ChatComposer
          value={input}
          onChange={(event) => setInput(event.target.value)}
          onSubmit={handleSubmit}
          onFilesSelected={handleFilesSelected}
          placeholder={
            isAnalyzing
              ? '문서를 분석하고 있습니다.'
              : isUploading
                ? '문서를 업로드하고 있습니다.'
                : config.prompt
          }
          isLoading={isBusy}
          fileButtonDisabled={isBusy}
        />
      </section>

      <DocumentUploadDialog
        isOpen={isUploadDialogOpen}
        files={pendingFiles}
        onTypeChange={handlePendingTypeChange}
        onRemove={handlePendingRemove}
        onCancel={() => {
          if (!isUploading) {
            setIsUploadDialogOpen(false);
            setPendingFiles([]);
          }
        }}
        onConfirm={handleUploadConfirm}
        isUploading={isUploading}
      />
    </main>
  );
}

export default ChatbotPage;
