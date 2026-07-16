import { AnimatePresence, motion } from 'framer-motion';
import { useEffect, useRef, useState } from 'react';
import { FiAlertCircle, FiCheckCircle, FiPaperclip } from 'react-icons/fi';

import {
  analyzeADocuments,
  createAConversation,
  deleteADocument,
  getUploadedADocument,
  listADocuments,
  mapATurnToAnswer,
  normalizeADocumentList,
  sendATurn,
  uploadADocument,
} from '../../api/chat/A/aApi.js';
import { ApiError } from '../../api/common/apiClient.js';
import ChatComposer from '../../components/chat/ChatComposer/ChatComposer.jsx';
import AssistantThinking from '../../components/chat/AssistantThinking/AssistantThinking.jsx';
import DocumentAttachmentList from '../../components/chat/DocumentAttachmentList/DocumentAttachmentList.jsx';
import DocumentUploadDialog from '../../components/chat/DocumentUploadDialog/DocumentUploadDialog.jsx';
import MessageBubble from '../../components/chat/MessageBubble/MessageBubble.jsx';
import { CHATBOT_CATEGORIES, createEmptyConversations } from '../../constants/chatbot.js';
import { CHATBOT_ANSWER_COMPONENTS } from './answerVariants.js';
import styles from './ChatbotPage.module.css';

const MAX_FILE_SIZE = 20 * 1024 * 1024;

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

function ChatbotPage({ consultationType }) {
  const messagesEndRef = useRef(null);
  const config = CHATBOT_CATEGORIES[consultationType];
  const AssistantAnswer = CHATBOT_ANSWER_COMPONENTS[consultationType];
  const isAPart = consultationType === 'before-contract';
  const [input, setInput] = useState('');
  const [messagesByType, setMessagesByType] = useState(createEmptyConversations);
  const [conversationIds, setConversationIds] = useState({});
  const [documents, setDocuments] = useState([]);
  const [pendingFiles, setPendingFiles] = useState([]);
  const [isUploadDialogOpen, setIsUploadDialogOpen] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const messages = messagesByType[consultationType] ?? [];
  const isBusy = isLoading || isUploading || isAnalyzing;
  const currentConversationId = conversationIds[consultationType] || null;

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
  }, [messages.length, isLoading]);

  const appendMessages = (...nextMessages) => {
    setMessagesByType((current) => ({
      ...current,
      [consultationType]: [
        ...(current[consultationType] ?? []),
        ...nextMessages,
      ],
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
    return created.conversation_id;
  };

  const refreshDocuments = async (conversationId) => {
    const response = await listADocuments(conversationId);
    const nextDocuments = normalizeADocumentList(response);
    setDocuments(nextDocuments);
    return nextDocuments;
  };

  const handleSubmit = async (event) => {
    event.preventDefault();
    const question = input.trim();

    if (!question || isBusy) {
      return;
    }

    const timestamp = Date.now();
    appendMessages({ id: `${timestamp}-user`, role: 'user', content: question });
    setInput('');
    setError('');
    setNotice('');
    setIsLoading(true);

    try {
      if (isAPart) {
        const result = await sendATurn({
          question,
          conversationId: currentConversationId,
          documentIds: documents.map((document) => document.document_id),
          analyzeDocuments: documents.length > 0,
          forceDocumentAnalysis: false,
        });

        saveConversationId(result.conversation_id);

        if (result.consultation?.state?.documents) {
          setDocuments(normalizeADocumentList(result.consultation.state.documents));
        }

        appendMessages({
          id: `${timestamp}-assistant`,
          role: 'assistant',
          content: mapATurnToAnswer(result),
        });
      } else {
        appendMessages({
          id: `${timestamp}-assistant`,
          role: 'assistant',
          content: config.reply,
        });
      }
    } catch (requestError) {
      setError(getErrorMessage(requestError, '상담 답변을 불러오지 못했습니다.'));

    } finally {
      setIsLoading(false);
    }
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
      setNotice('첨부 문서를 다시 분석했습니다. 같은 상담에서 질문을 이어갈 수 있습니다.');
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
        <AnimatePresence initial={false}>
          {messages.map((message) => (
            <MessageBubble
              key={message.id}
              role={message.role}
              content={message.content}
              AssistantAnswer={AssistantAnswer}
            />
          ))}
          {isLoading && (
            <AssistantThinking key={`assistant-thinking-${consultationType}`} />
          )}
        </AnimatePresence>
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
