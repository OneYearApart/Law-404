import { AnimatePresence, motion } from "framer-motion";
import { useEffect, useRef, useState } from "react";
import { useLocation } from "react-router";
import { FiAlertCircle, FiCheckCircle, FiPaperclip } from "react-icons/fi";
import { RiShieldCheckLine } from "react-icons/ri";

import {
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
} from "../../api/chat/A/aApi.js";
import { createBConversation, sendBChat } from "../../api/chat/B/bApi.js";
import {
  createConversation as createStoredConversation,
  loadConversation as loadStoredConversation,
  saveConversationMessage,
} from "../../api/chat/conversationsApi.js";
import {
  getCalendarConnectGuide,
  getCalendarConnectionStatus,
} from "../../api/calendar/calendarApi.js";
import { ApiError } from "../../api/common/apiClient.js";
import ChatComposer from "../../components/chat/ChatComposer/ChatComposer.jsx";
import AssistantThinking from "../../components/chat/AssistantThinking/AssistantThinking.jsx";
import DocumentAttachmentList from "../../components/chat/DocumentAttachmentList/DocumentAttachmentList.jsx";
import DocumentUploadDialog from "../../components/chat/DocumentUploadDialog/DocumentUploadDialog.jsx";
import MessageBubble from "../../components/chat/MessageBubble/MessageBubble.jsx";
import {
  CHATBOT_CATEGORIES,
  createEmptyConversations,
} from "../../constants/chatbot.js";
import { useChatConversation } from "../../contexts/chatConversationContext.js";
import { CHATBOT_ANSWER_COMPONENTS } from "./answerVariants.js";
import styles from "./ChatbotPage.module.css";

const MAX_FILE_SIZE = 20 * 1024 * 1024;

const CONSULTATION_PARTS = Object.freeze({
  "before-contract": "a",
  "during-contract": "b",
  "after-contract": "c",
  "jeonse-fraud": "d",
});

const STARTER_GUIDES = Object.freeze({
  "before-contract": {
    eyebrow: "계약 전 상담",
    title: "계약 전, 무엇이 걱정되시나요?",
    description:
      "현재 상황을 한 문장으로 알려 주세요. 필요한 확인 항목을 하나씩 묻고, 마지막에 확인 결과와 다음 행동을 정리해 드립니다.",
    examples: [
      "집주인 가족이 대신 계약하러 왔어요.",
      "임대차계약서 이상 없는지 확인해줘",
    ],
  },
  "during-contract": {
    eyebrow: "계약 중 상담",
    title: "계약서에서 무엇을 확인할까요?",
    description:
      "작성 중인 계약 내용이나 걱정되는 조항을 알려 주세요. 확인할 부분과 수정이 필요한 행동을 정리해 드립니다.",
    examples: [
      "계약서 금액과 설명받은 금액이 달라요.",
      "특약에 불리한 내용이 있는지 확인하고 싶어요.",
    ],
  },
  "after-contract": {
    eyebrow: "계약 후 상담",
    title: "계약 후, 무엇부터 해야 할까요?",
    description:
      "계약 직후부터 입주 전까지 필요한 절차를 알려 주세요. 놓치기 쉬운 일정과 다음 행동을 정리해 드립니다.",
    examples: [
      "계약 후 가장 먼저 해야 할 일이 무엇인가요?",
      "전입신고와 확정일자는 언제 해야 하나요?",
    ],
  },
  "jeonse-fraud": {
    eyebrow: "전세사기 상담",
    title: "어떤 상황이 의심되시나요?",
    description:
      "의심되는 요청이나 위험 신호를 알려 주세요. 우선 멈춰야 할 행동과 공식 확인 경로를 정리해 드립니다.",
    examples: [
      "계약 직전에 계좌를 바꿔 달라고 해요.",
      "등기부에 근저당이 많은데 계약해도 되나요?",
    ],
  },
});

function getUserMessageText(content) {
  if (content && typeof content === "object") {
    return String(content.text || "").trim();
  }
  return String(content || "").trim();
}

function createPendingFile(file) {
  const loweredName = file.name.toLowerCase();
  const guessedType =
    loweredName.includes("등기") || loweredName.includes("registry")
      ? "registry"
      : "lease_contract";

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
  return String(item || "")
    .replace(/^\[[^\]]+\]\s*/, "")
    .replace(/\s+/g, " ")
    .trim();
}

function uniqueReviewItems(items, maxItems = 4) {
  return [...new Set(items.map(normalizeReviewItem).filter(Boolean))].slice(
    0,
    maxItems,
  );
}

function findCompletedResult(progress, question) {
  if (!progress || !question) {
    return null;
  }

  const slotKey = question.slot_key || question.slotKey;
  const questionKey = question.question_key || question.questionKey;
  const groups = [
    ["확인된 정보", progress.confirmed_items || []],
    ["확인하지 못한 정보", progress.unresolved_items || []],
    ["추가 확인 필요", progress.conflict_items || []],
  ];

  for (const [groupLabel, items] of groups) {
    const matched = items.find(
      (item) =>
        (slotKey && item?.slot_key === slotKey) ||
        (questionKey && item?.question_key === questionKey),
    );
    if (matched) {
      return {
        groupLabel,
        label: matched.label || question.label || "확인 항목",
        displayValue: matched.display_value || matched.value || groupLabel,
      };
    }
  }

  return null;
}

function inferInitialAReviewItems(question) {
  const normalized = String(question || "").toLowerCase();

  if (/대리|위임|아들|딸|가족|대신/.test(normalized)) {
    return [
      "등기부등본상 실제 소유자",
      "소유자 본인의 대리 계약 의사",
      "위임 범위와 서명 권한",
      "계약금 계좌 예금주와 대금 수령 권한",
    ];
  }

  if (/계좌|예금주|송금|계약금|잔금/.test(normalized)) {
    return [
      "계약 상대방과 계좌 예금주의 관계",
      "계약금 또는 잔금 수령 권한",
      "계좌 변경 요청의 기록과 확인 경로",
      "송금 전 보류해야 할 위험 신호",
    ];
  }

  if (/등기|근저당|압류|가압류|신탁|권리/.test(normalized)) {
    return [
      "등기부등본상 현재 소유자",
      "현재 유효한 근저당과 권리 제한",
      "신탁등기 및 말소 여부",
      "계약·송금 전 추가 확인 항목",
    ];
  }

  if (/계약서|문서|pdf|특약|보증금/.test(normalized)) {
    return [
      "계약 당사자와 목적물 정보",
      "보증금·계약금·잔금과 주요 일정",
      "특약과 위험 문구",
      "문서 내용과 추가 확인이 필요한 항목",
    ];
  }

  return [
    "현재 계약 단계와 질문의 핵심 사실",
    "관련 법률·판례·공식 절차 근거",
    "계약 진행 또는 송금 보류 필요성",
    "다음으로 확인할 가장 중요한 항목",
  ];
}

function buildAThinkingItems(messages) {
  const lastUserMessage = [...messages]
    .reverse()
    .find((message) => message.role === "user");
  const lastAssistantMessage = [...messages]
    .reverse()
    .find(
      (message) =>
        message.role === "assistant" && typeof message.content === "object",
    );
  const previousAnswer = lastAssistantMessage?.content;

  const unresolved = uniqueReviewItems(previousAnswer?.missingFacts || []);
  if (unresolved.length > 0) {
    return unresolved;
  }

  const required = uniqueReviewItems(previousAnswer?.requiredInformation || []);
  if (required.length > 0) {
    return required;
  }

  return inferInitialAReviewItems(getUserMessageText(lastUserMessage?.content));
}

function ChatbotPage({ consultationType }) {
  const messagesEndRef = useRef(null);
  const entryResetKeyRef = useRef("");
  const entryResetPendingRef = useRef(false);
  const localMessageSequenceRef = useRef(0);
  const messageIdRef = useRef(0);
  const calendarConnectionStatusRef = useRef(null);
  const pendingCalendarRegistrationRef = useRef(null);
  const location = useLocation();
  const config = CHATBOT_CATEGORIES[consultationType];
  const starterGuide =
    STARTER_GUIDES[consultationType] || STARTER_GUIDES["before-contract"];
  const AssistantAnswer = CHATBOT_ANSWER_COMPONENTS[consultationType];
  const isAPart = consultationType === "before-contract";
  const isBPart = consultationType === "during-contract";
  const {
    activeAConversationId,
    newConversationVersion,
    activateAConversation,
    startNewAConversation,
    notifyAConversationSaved,
    notifyConversationSaved,
  } = useChatConversation();
  const [input, setInput] = useState("");
  const [messagesByType, setMessagesByType] = useState(
    createEmptyConversations,
  );
  const [conversationIds, setConversationIds] = useState({});
  const [documents, setDocuments] = useState([]);
  const [pendingFiles, setPendingFiles] = useState([]);
  const [pendingDocumentIds, setPendingDocumentIds] = useState([]);
  const [isUploadDialogOpen, setIsUploadDialogOpen] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [calendarConnectionStatus, setCalendarConnectionStatus] =
    useState(null);
  const [calendarConnectGuide, setCalendarConnectGuide] = useState(null);
  const [isCalendarConnectionLoading, setIsCalendarConnectionLoading] =
    useState(false);
  const [isCalendarConnectionPolling, setIsCalendarConnectionPolling] =
    useState(false);
  const [showCalendarConnectionPanel, setShowCalendarConnectionPanel] =
    useState(false);
  const [attachDocumentAnalysisNextTurn, setAttachDocumentAnalysisNextTurn] =
    useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const messages = messagesByType[consultationType] ?? [];
  const isBusy = isLoading || isUploading;
  const currentConversationId = conversationIds[consultationType] || null;
  const aThinkingItems = isAPart ? buildAThinkingItems(messages) : [];
  const latestAssistantIndex = messages.reduce(
    (latest, message, index) => (message.role === "assistant" ? index : latest),
    -1,
  );
  const latestAssistantAnswer =
    latestAssistantIndex >= 0 ? messages[latestAssistantIndex]?.content : null;
  const aThinkingProgress =
    isAPart && typeof latestAssistantAnswer === "object"
      ? latestAssistantAnswer?.consultationProgress || null
      : null;

  useEffect(() => {
    if (!isAPart) {
      return;
    }

    const entryKey = `${consultationType}:${location.key}`;
    if (entryResetKeyRef.current === entryKey) {
      return;
    }

    const requestedConversationId = String(
      location.state?.conversationId || "",
    ).trim();
    const requestedPart = String(location.state?.conversationPart || "").trim();

    entryResetKeyRef.current = entryKey;
    setMessagesByType((current) => ({ ...current, [consultationType]: [] }));
    setConversationIds((current) => ({ ...current, [consultationType]: null }));
    setDocuments([]);
    setPendingDocumentIds([]);
    setAttachDocumentAnalysisNextTurn(false);
    setError("");
    setNotice("");

    if (requestedConversationId && (!requestedPart || requestedPart === "a")) {
      entryResetPendingRef.current = false;
      activateAConversation(requestedConversationId);
      return;
    }

    entryResetPendingRef.current = true;
    startNewAConversation();
  }, [
    activateAConversation,
    consultationType,
    isAPart,
    location.key,
    location.state,
    startNewAConversation,
  ]);

  useEffect(() => {
    if (!isAPart) {
      return undefined;
    }

    if (entryResetPendingRef.current) {
      if (!activeAConversationId) {
        entryResetPendingRef.current = false;
      }
      return undefined;
    }

    let cancelled = false;

    const restoreConversation = async () => {
      if (!activeAConversationId) {
        setMessagesByType((current) => ({
          ...current,
          [consultationType]: [],
        }));
        setConversationIds((current) => ({
          ...current,
          [consultationType]: null,
        }));
        setDocuments([]);
        setPendingDocumentIds([]);
        setAttachDocumentAnalysisNextTurn(false);
        setError("");
        setNotice("");
        return;
      }

      if (
        String(activeAConversationId) === String(currentConversationId || "")
      ) {
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
        setPendingDocumentIds([]);
        setAttachDocumentAnalysisNextTurn(false);
        setError("");
      } catch (requestError) {
        if (!cancelled) {
          setError(
            getErrorMessage(requestError, "저장된 상담을 불러오지 못했습니다."),
          );
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

  useEffect(() => {
    if (isAPart) {
      return undefined;
    }

    let cancelled = false;
    const requestedConversationId = String(
      location.state?.conversationId || "",
    ).trim();

    const restoreStoredConversation = async () => {
      if (!requestedConversationId) {
        setMessagesByType((current) => ({
          ...current,
          [consultationType]: [],
        }));
        setConversationIds((current) => ({
          ...current,
          [consultationType]: null,
        }));
        setError("");
        setNotice("");
        return;
      }

      try {
        const storedMessages = await loadStoredConversation(
          requestedConversationId,
        );
        if (cancelled) {
          return;
        }
        setMessagesByType((current) => ({
          ...current,
          [consultationType]: storedMessages.map((message) => ({
            id: `stored-${message.id}`,
            role: message.role,
            content: message.content,
          })),
        }));
        setConversationIds((current) => ({
          ...current,
          [consultationType]: requestedConversationId,
        }));
        setError("");
        setNotice("");
      } catch (requestError) {
        if (!cancelled) {
          setError(
            getErrorMessage(requestError, "저장된 대화를 불러오지 못했습니다."),
          );
        }
      }
    };

    restoreStoredConversation();
    return () => {
      cancelled = true;
    };
  }, [consultationType, isAPart, location.key, location.state]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({
      behavior: "smooth",
      block: "end",
    });
  }, [messages.length, isLoading]);

  useEffect(() => {
    calendarConnectionStatusRef.current = calendarConnectionStatus;
  }, [calendarConnectionStatus]);

  useEffect(() => {
    if (!isBPart) {
      return undefined;
    }

    let cancelled = false;

    const loadCalendarConnection = async () => {
      setIsCalendarConnectionLoading(true);
      try {
        const status = await getCalendarConnectionStatus();
        if (!cancelled) {
          setCalendarConnectionStatus(status);
        }
      } catch {
        if (!cancelled) {
          setCalendarConnectionStatus(null);
        }
      } finally {
        if (!cancelled) {
          setIsCalendarConnectionLoading(false);
        }
      }
    };

    loadCalendarConnection();
    return () => {
      cancelled = true;
    };
  }, [isBPart]);

  const appendMessages = (...nextMessages) => {
    setMessagesByType((current) => ({
      ...current,
      [consultationType]: [
        ...(current[consultationType] ?? []),
        ...nextMessages,
      ],
    }));
  };

  const createMessageId = (role) => {
    messageIdRef.current += 1;
    return `${consultationType}-${role}-${messageIdRef.current}`;
  };

  const updateMessageContent = (messageId, updater) => {
    setMessagesByType((current) => ({
      ...current,
      [consultationType]: (current[consultationType] ?? []).map((message) => {
        if (message.id !== messageId) {
          return message;
        }

        const nextContent =
          typeof updater === "function" ? updater(message.content) : updater;
        return { ...message, content: nextContent };
      }),
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

  const ensureBConversation = async () => {
    if (currentConversationId) {
      return currentConversationId;
    }

    const conversationId = await createBConversation();
    saveConversationId(conversationId);
    return conversationId;
  };

  const ensureStoredConversation = async (title) => {
    if (currentConversationId) {
      return currentConversationId;
    }

    const part = CONSULTATION_PARTS[consultationType];
    const created = await createStoredConversation({
      part,
      title:
        String(title || "")
          .trim()
          .slice(0, 80) || `새 ${config.title}`,
    });
    saveConversationId(created.conversation_id);
    await notifyConversationSaved();
    return created.conversation_id;
  };

  const getLatestBPendingAction = () => {
    const latestAssistant = [...messages]
      .reverse()
      .find(
        (message) =>
          message.role === "assistant" &&
          message.content &&
          typeof message.content === "object" &&
          message.content.pendingAction,
      );

    return latestAssistant?.content?.pendingAction ?? null;
  };

  const isCalendarApprovalMessage = (question) =>
    /(등록|캘린더|일정).*(해줘|할게|하고 싶|해주세요)|^(응|네|좋아|그래|등록해줘|등록)$/u.test(
      question,
    );

  const submitCalendarRegistration = (action) => {
    if (!action) {
      return;
    }

    const registerQuestion = "캘린더에 등록해줘";
    appendMessages({
      id: createMessageId("user-calendar"),
      role: "user",
      content: registerQuestion,
    });
    setIsLoading(true);
    setError("");
    setNotice("");

    runBChatTurn({
      question: registerQuestion,
      pendingAction: action,
      calendarMode: "live",
    })
      .then(() => setNotice("캘린더 등록 요청을 처리했습니다."))
      .catch((requestError) =>
        setError(
          getErrorMessage(
            requestError,
            "캘린더 등록 요청을 처리하지 못했습니다.",
          ),
        ),
      )
      .finally(() => setIsLoading(false));
  };

  const appendCalendarRegistrationPrompt = (action) => {
    if (!action) {
      return;
    }

    appendMessages({
      id: createMessageId("assistant-calendar-ready"),
      role: "assistant",
      content: {
        text: "Google Calendar 연동이 완료되었습니다. 일정을 등록하시겠습니까?",
        pendingAction: action,
        calendarEvents: action.events || [],
        calendarRegistration: null,
        calendarToolResult: null,
        isStreaming: false,
        onRegisterCalendar: submitCalendarRegistration,
      },
    });
  };

  const runBChatTurn = async ({
    question,
    pendingAction = null,
    calendarMode = "dry_run",
  }) => {
    const conversationId = await ensureBConversation();
    const assistantMessageId = createMessageId("assistant");

    appendMessages({
      id: assistantMessageId,
      role: "assistant",
      content: {
        text: "",
        pendingAction: null,
        calendarEvents: [],
        calendarRegistration: null,
        calendarToolResult: null,
        isStreaming: true,
        onRegisterCalendar: null,
      },
    });

    await sendBChat({
      message: question,
      conversationId,
      pendingAction,
      calendarMode,
      calendarProvider: "smithery_googlecalendar",
      calendarId: "primary",
      topK: 5,
      onMeta: (meta) => {
        updateMessageContent(assistantMessageId, (content) => ({
          ...(content && typeof content === "object"
            ? content
            : { text: String(content ?? "") }),
          pendingAction: meta.pending_action ?? null,
          calendarEvents: meta.calendar_events ?? [],
          calendarRegistration: meta.calendar_registration ?? null,
          calendarToolResult: meta.calendar_tool_result ?? null,
          meta,
          onRegisterCalendar: (action) => {
            if (!action) {
              return;
            }

            if (!calendarConnectionStatusRef.current?.connected) {
              pendingCalendarRegistrationRef.current = action;
              setShowCalendarConnectionPanel(true);
              setNotice(
                "Google Calendar 연결 후 일정 등록 여부를 다시 확인합니다.",
              );
              handleShowCalendarConnectGuide();
              return;
            }

            submitCalendarRegistration(action);
          },
        }));
      },
      onToken: (token) => {
        updateMessageContent(assistantMessageId, (content) => {
          const current =
            content && typeof content === "object"
              ? content
              : { text: String(content ?? "") };
          return { ...current, text: `${current.text ?? ""}${token}` };
        });
      },
      onDone: () => {
        updateMessageContent(assistantMessageId, (content) => {
          const current =
            content && typeof content === "object"
              ? content
              : { text: String(content ?? "") };
          return { ...current, isStreaming: false };
        });
      },
    });
  };

  const handleShowCalendarConnectGuide = async () => {
    if (isCalendarConnectionLoading) {
      return;
    }

    setIsCalendarConnectionLoading(true);
    setError("");
    setNotice("");

    try {
      const guide = await getCalendarConnectGuide();
      setCalendarConnectGuide(guide);

      if (guide?.authorization_url) {
        const popup = window.open(
          guide.authorization_url,
          "law404-google-calendar-oauth",
          "width=520,height=720",
        );

        if (!popup) {
          pendingCalendarRegistrationRef.current = null;
          setShowCalendarConnectionPanel(false);
          return;
        }

        setNotice(
          "Google Calendar 권한 승인 창을 열었습니다. 승인이 끝나면 연결 상태를 자동으로 확인합니다.",
        );
        setIsCalendarConnectionPolling(true);

        let pollAttempts = 0;
        const pollConnection = window.setInterval(async () => {
          pollAttempts += 1;
          try {
            const status = await getCalendarConnectionStatus();
            setCalendarConnectionStatus(status);

            if (status?.connected) {
              window.clearInterval(pollConnection);
              setIsCalendarConnectionPolling(false);
              setShowCalendarConnectionPanel(false);
              popup.close?.();

              const pendingRegistration =
                pendingCalendarRegistrationRef.current;
              pendingCalendarRegistrationRef.current = null;

              if (pendingRegistration) {
                appendCalendarRegistrationPrompt(pendingRegistration);
                setNotice("Google Calendar 연결이 완료되었습니다.");
                return;
              }

              setNotice("Google Calendar 연결이 완료되었습니다.");
            }
          } catch {
            // OAuth 승인 도중에는 연결 상태 조회가 잠시 실패할 수 있습니다.
          }

          if (pollAttempts >= 48) {
            window.clearInterval(pollConnection);
            setIsCalendarConnectionPolling(false);
            setNotice(
              "승인 후에도 연결 상태가 바뀌지 않으면 연결하기를 다시 눌러 주세요.",
            );
          }
        }, 2000);
        return;
      }

      if (guide?.connected) {
        const status = await getCalendarConnectionStatus();
        setCalendarConnectionStatus(status);
        setShowCalendarConnectionPanel(false);

        const pendingRegistration = pendingCalendarRegistrationRef.current;
        pendingCalendarRegistrationRef.current = null;

        if (pendingRegistration) {
          appendCalendarRegistrationPrompt(pendingRegistration);
          setNotice("Google Calendar 연결이 완료되었습니다.");
          return;
        }

        setNotice("Google Calendar가 이미 연결되어 있습니다.");
        return;
      }

      setNotice(
        guide?.note ||
          "Google Calendar 연결을 시작했습니다. 잠시 후 연결 상태를 다시 확인해 주세요.",
      );
    } catch (requestError) {
      setError(
        getErrorMessage(
          requestError,
          "Google Calendar 연결 안내를 불러오지 못했습니다.",
        ),
      );
    } finally {
      setIsCalendarConnectionLoading(false);
    }
  };

  const refreshDocuments = async (conversationId) => {
    const response = await listADocuments(conversationId);
    const nextDocuments = normalizeADocumentList(response);
    setDocuments(nextDocuments);
    return nextDocuments;
  };

  const submitQuestion = async (rawQuestion) => {
    const question = String(rawQuestion || "").trim();

    if (!question || isBusy) {
      return;
    }

    const attachedDocuments = isAPart
      ? documents.filter((document) =>
          pendingDocumentIds.includes(document.document_id),
        )
      : [];

    localMessageSequenceRef.current += 1;
    const messageKey = `local-${localMessageSequenceRef.current}`;
    appendMessages({
      id: `${messageKey}-user`,
      role: "user",
      content: attachedDocuments.length
        ? { text: question, attachments: attachedDocuments }
        : question,
    });
    setInput("");
    setError("");
    setNotice("");
    setIsLoading(true);
    if (attachedDocuments.length > 0) {
      setPendingDocumentIds([]);
      setAttachDocumentAnalysisNextTurn(false);
    }

    try {
      if (isAPart) {
        const result = await sendATurn({
          question,
          conversationId: currentConversationId,
          documentIds: documents.map((document) => document.document_id),
          attachedDocumentIds: attachedDocuments.map(
            (document) => document.document_id,
          ),
          analyzeDocuments:
            attachedDocuments.length > 0 && attachDocumentAnalysisNextTurn,
          forceDocumentAnalysis: false,
        });

        saveConversationId(result.conversation_id);
        await notifyAConversationSaved(result.conversation_id);
        if (result.consultation?.state?.documents) {
          setDocuments(
            normalizeADocumentList(result.consultation.state.documents),
          );
        }

        appendMessages({
          id: `${messageKey}-assistant`,
          role: "assistant",
          content: mapATurnToAnswer(result),
        });
      } else if (isBPart) {
        const pendingAction = isCalendarApprovalMessage(question)
          ? getLatestBPendingAction()
          : null;

        await runBChatTurn({
          question,
          pendingAction,
          calendarMode: pendingAction ? "live" : "dry_run",
        });
      } else {
        const part = CONSULTATION_PARTS[consultationType];
        const storedConversationId = await ensureStoredConversation(question);
        await saveConversationMessage({
          conversationId: storedConversationId,
          part,
          role: "user",
          content: question,
        });

        appendMessages({
          id: `${messageKey}-assistant`,
          role: "assistant",
          content: config.reply,
        });

        await saveConversationMessage({
          conversationId: storedConversationId,
          part,
          role: "assistant",
          content: config.reply,
        });
        await notifyConversationSaved();
      }
    } catch (requestError) {
      setMessagesByType((current) => ({
        ...current,
        [consultationType]: (current[consultationType] ?? []).filter(
          (message) => message.id !== `${messageKey}-user`,
        ),
      }));
      setInput(question);
      if (attachedDocuments.length > 0) {
        setPendingDocumentIds(
          attachedDocuments.map((document) => document.document_id),
        );
        setAttachDocumentAnalysisNextTurn(true);
      }
      setError(
        getErrorMessage(requestError, "상담 답변을 불러오지 못했습니다."),
      );
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
    setError("");
    setNotice("");

    if (!isAPart) {
      setNotice("문서 업로드는 현재 계약 전 A 상담에서만 사용할 수 있습니다.");
      return;
    }

    const invalidFile = files.find((file) => {
      const isPdf =
        file.type === "application/pdf" ||
        file.name.toLowerCase().endsWith(".pdf");
      return !isPdf || file.size <= 0 || file.size > MAX_FILE_SIZE;
    });

    if (invalidFile) {
      setError(
        "PDF 파일만 업로드할 수 있으며 파일 하나당 최대 20MB까지 가능합니다.",
      );
      return;
    }

    setPendingFiles(files.map(createPendingFile));
    setIsUploadDialogOpen(true);
  };

  const handlePendingTypeChange = (id, documentType) => {
    setPendingFiles((current) =>
      current.map((item) =>
        item.id === id ? { ...item, documentType } : item,
      ),
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
    setError("");
    setNotice("");

    let conversationId = currentConversationId;

    try {
      conversationId = await ensureAConversation();
      const uploadedDocumentIds = [];

      for (const item of pendingFiles) {
        const uploadResult = await uploadADocument({
          conversationId,
          file: item.file,
          documentType: item.documentType,
        });
        const uploaded = getUploadedADocument(uploadResult);
        if (uploaded) {
          uploadedDocumentIds.push(uploaded.document_id);
          setDocuments((current) => [
            ...current.filter(
              (document) => document.document_id !== uploaded.document_id,
            ),
            uploaded,
          ]);
        }
      }

      setIsUploadDialogOpen(false);
      setPendingFiles([]);

      await refreshDocuments(conversationId);
      setPendingDocumentIds((current) => [
        ...new Set([...current, ...uploadedDocumentIds]),
      ]);
      setAttachDocumentAnalysisNextTurn(uploadedDocumentIds.length > 0);
    } catch (requestError) {
      setError(getErrorMessage(requestError, "문서를 업로드하지 못했습니다."));

      if (conversationId) {
        try {
          await refreshDocuments(conversationId);
        } catch {
          // 원래 업로드 오류를 유지한다.
        }
      }
    } finally {
      setIsUploading(false);
    }
  };

  const handleDeleteDocument = async (documentId) => {
    if (!currentConversationId || isBusy) {
      return;
    }

    setIsUploading(true);
    setError("");
    setNotice("");

    try {
      await deleteADocument({
        conversationId: currentConversationId,
        documentId,
      });
      const refreshed = await refreshDocuments(currentConversationId);
      setPendingDocumentIds((current) =>
        current.filter((id) => id !== documentId),
      );
      if (!refreshed.length) {
        setAttachDocumentAnalysisNextTurn(false);
      }
      setNotice(
        refreshed.length
          ? "문서를 삭제했습니다. 남은 문서로 상담을 계속할 수 있습니다."
          : "첨부 문서를 모두 삭제했습니다.",
      );
    } catch (requestError) {
      setError(getErrorMessage(requestError, "문서를 삭제하지 못했습니다."));
    } finally {
      setIsUploading(false);
    }
  };

  return (
    <main className={styles.page} aria-label={config.title}>
      <section className={styles.messages} aria-live="polite">
        {messages.length === 0 && !isLoading && (
          <section className={styles.emptyState}>
            <div className={styles.emptyStateIntro}>
              <span className={styles.emptyStateIcon} aria-hidden="true">
                <RiShieldCheckLine />
              </span>
              <div className={styles.emptyStateCopy}>
                <p className={styles.emptyStateEyebrow}>
                  {starterGuide.eyebrow}
                </p>
                <h1>{starterGuide.title}</h1>
                <p className={styles.emptyStateDescription}>
                  {starterGuide.description}
                </p>
              </div>
            </div>
            <div className={styles.exampleQuestions} aria-label="예시 질문">
              {starterGuide.examples.map((example) => (
                <button
                  type="button"
                  key={example}
                  onClick={() => {
                    if (
                      isAPart &&
                      example === "임대차계약서 이상 없는지 확인해줘"
                    ) {
                      setInput(example);
                      setNotice("임대차계약서 PDF를 먼저 첨부해 주세요.");
                      return;
                    }
                    submitQuestion(example);
                  }}
                  disabled={isBusy}
                >
                  {example}
                </button>
              ))}
            </div>
            <p className={styles.emptyStateHint}>
              예시를 선택하거나 아래 입력창에 직접 질문해 주세요.
            </p>
          </section>
        )}

        {messages.map((message, index) => {
          if (
            isBPart &&
            message.role === "assistant" &&
            message.content?.isStreaming &&
            !String(message.content?.text || "").trim()
          ) {
            return null;
          }

          const isCompletedCollectingQuestion =
            isAPart &&
            message.role === "assistant" &&
            message.content?.answerPhase === "collecting" &&
            messages[index + 1]?.role === "user";
          const completedAnswerMessage =
            isCompletedCollectingQuestion &&
            messages[index + 1]?.role === "user"
              ? messages[index + 1]
              : null;
          const nextAssistantMessage =
            isCompletedCollectingQuestion &&
            messages[index + 2]?.role === "assistant" &&
            typeof messages[index + 2]?.content === "object"
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
                displayMode: "completed-question",
                completedAnswer: getUserMessageText(
                  completedAnswerMessage?.content,
                ),
                completedResult,
              }
            : message.content;
          const shouldAnimate = String(message.id || "").startsWith("local-");

          return (
            <MessageBubble
              key={message.id}
              role={message.role}
              content={displayContent}
              AssistantAnswer={AssistantAnswer}
              onQuickAnswer={isAPart ? handleQuickAnswer : undefined}
              isInteractive={
                isAPart && index === latestAssistantIndex && !isBusy
              }
              shouldAnimate={shouldAnimate}
            />
          );
        })}

        {isLoading && (
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
            {error ? (
              <FiAlertCircle aria-hidden="true" />
            ) : notice.includes("완료") ? (
              <FiCheckCircle aria-hidden="true" />
            ) : (
              <FiPaperclip aria-hidden="true" />
            )}
            <span>{error || notice}</span>
          </motion.div>
        )}
      </AnimatePresence>

      <section className={styles.composerDock}>
        {isAPart && (
          <DocumentAttachmentList
            documents={documents.filter((document) =>
              pendingDocumentIds.includes(document.document_id),
            )}
            onDelete={handleDeleteDocument}
            isBusy={isBusy}
          />
        )}
        {isBPart &&
          showCalendarConnectionPanel &&
          !calendarConnectionStatus?.connected && (
            <section className={styles.calendarConnectionPanel}>
              <div className={styles.calendarConnectionHeader}>
                <div>
                  <p className={styles.calendarConnectionEyebrow}>
                    Google Calendar MCP
                  </p>
                  <strong>
                    {isCalendarConnectionPolling
                      ? "캘린더 연결 확인 중"
                      : "캘린더 연결 필요"}
                  </strong>
                </div>
                <button
                  type="button"
                  onClick={handleShowCalendarConnectGuide}
                  disabled={isCalendarConnectionLoading}
                >
                  {isCalendarConnectionPolling
                    ? "연결 확인 중"
                    : "Google Calendar 연결하기"}
                </button>
              </div>
              <p className={styles.calendarConnectionDescription}>
                계약 종료일과 갱신요구 마감일을 내 Google Calendar에
                등록하려면 먼저 Google 계정 연결이 필요합니다.
              </p>
              {calendarConnectGuide?.note ? (
                <p className={styles.calendarConnectionDescription}>
                  {calendarConnectGuide.note}
                </p>
              ) : (
                <p className={styles.calendarConnectionDescription}>
                  연결 버튼을 누르면 Google Calendar 권한 승인 화면이
                  열립니다.
                </p>
              )}
            </section>
          )}
        <ChatComposer
          value={input}
          onChange={(event) => setInput(event.target.value)}
          onSubmit={handleSubmit}
          onFilesSelected={handleFilesSelected}
          placeholder={config.prompt}
          isLoading={isLoading}
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
