import { useRef } from 'react';
import { motion } from 'framer-motion';
import {
  FiFileText,
  FiImage,
  FiCheckCircle,
  FiHelpCircle,
  FiDownload,
  FiCopy,
} from 'react-icons/fi';

import styles from './DocumentAnswer.module.css';

/**
 * C파트 내용증명(문서 생성) 답변.
 *
 * content 구조 (부모가 /document, /document/ocr 응답으로 채움):
 * {
 *   kind: 'document',
 *   status: 'need_more_info' | 'complete',
 *   progress: 0.0 ~ 1.0,
 *   missingLabels: string[],
 *   nextQuestion: string | null,
 *   document: string | null,        // status='complete'일 때 내용증명 본문
 *   extractedFromImage: string[],   // OCR로 방금 찾은 항목 (있을 때만)
 *   isStreaming: boolean,
 *   error: string | null,
 * }
 *
 * 문자열이면(과거 저장 대화 복원) 단순 텍스트로 표시.
 */

function ProgressBar({ progress }) {
  const pct = Math.round(Math.max(0, Math.min(1, progress || 0)) * 100);
  return (
    <div className={styles.progressWrap} aria-label={`정보 수집 ${pct}% 완료`}>
      <div className={styles.progressTrack}>
        <motion.div
          className={styles.progressFill}
          initial={{ width: 0 }}
          animate={{ width: `${pct}%` }}
          transition={{ duration: 0.4, ease: 'easeOut' }}
        />
      </div>
      <span className={styles.progressLabel}>{pct}%</span>
    </div>
  );
}

function CompletedDocument({ document }) {
  const textRef = useRef(null);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(document || '');
    } catch {
      // 클립보드 권한이 없으면 조용히 무시 (사용자가 직접 선택 복사 가능)
    }
  };

  const handleDownload = () => {
    const blob = new Blob([document || ''], { type: 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = window.document.createElement('a');
    a.href = url;
    a.download = '내용증명.txt';
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <motion.article
      className={styles.docCard}
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
    >
      <div className={styles.docHead}>
        <span className={styles.docIcon} aria-hidden="true">
          <FiFileText />
        </span>
        <div className={styles.docHeadText}>
          <span className={styles.docEyebrow}>내용증명 초안 완성</span>
          <span className={styles.docHint}>
            내용을 검토하고, 실제 발송 전 사실관계를 다시 확인하세요.
          </span>
        </div>
      </div>

      <pre className={styles.docBody} ref={textRef}>
        {document}
      </pre>

      <div className={styles.docActions}>
        <button type="button" className={styles.docActionButton} onClick={handleCopy}>
          <FiCopy aria-hidden="true" />
          <span>복사</span>
        </button>
        <button type="button" className={styles.docActionButton} onClick={handleDownload}>
          <FiDownload aria-hidden="true" />
          <span>텍스트로 저장</span>
        </button>
      </div>

      <p className={styles.docDisclaimer}>
        이 문서는 참고용 초안입니다. 법적 효력과 발송(내용증명 우편) 절차는 우체국·전문가를 통해 확인하세요.
      </p>
    </motion.article>
  );
}

function DocumentAnswer({ content }) {
  // 문자열이면 단순 표시 (히스토리 복원 등)
  if (typeof content === 'string') {
    return (
      <motion.article className={styles.simpleCard} initial={{ opacity: 0 }} animate={{ opacity: 1 }}>
        <span className={styles.simpleEyebrow}>내용증명</span>
        <p className={styles.simpleBody}>{content}</p>
      </motion.article>
    );
  }

  const {
    status = null,
    progress = 0,
    missingLabels = [],
    nextQuestion = null,
    document = null,
    extractedFromImage = [],
    isStreaming = false,
    error = null,
  } = content || {};

  if (error) {
    return (
      <div className={`${styles.simpleCard} ${styles.errorCard}`}>
        <span className={styles.simpleEyebrow}>오류</span>
        <p className={styles.simpleBody}>{error}</p>
      </div>
    );
  }

  // 처리 중
  if (isStreaming && !status) {
    return (
      <div className={styles.working}>
        <span className={styles.workingDot} />
        <span className={styles.workingDot} />
        <span className={styles.workingDot} />
        <span className={styles.workingText}>내용증명 정보를 정리하고 있어요</span>
      </div>
    );
  }

  return (
    <div className={styles.wrap}>
      {/* OCR로 방금 찾은 항목 안내 */}
      {extractedFromImage.length > 0 && (
        <motion.div
          className={styles.ocrNotice}
          initial={{ opacity: 0, y: 6 }}
          animate={{ opacity: 1, y: 0 }}
        >
          <span className={styles.ocrIcon} aria-hidden="true">
            <FiImage />
          </span>
          <span>
            계약서 이미지에서 <strong>{extractedFromImage.length}개 항목</strong>을 자동으로 채웠어요
            {extractedFromImage.length > 0 && (
              <span className={styles.ocrItems}> ({extractedFromImage.join(', ')})</span>
            )}
          </span>
        </motion.div>
      )}

      {/* 진행바 (완성 전까지) */}
      {status === 'need_more_info' && (
        <div className={styles.collectCard}>
          <div className={styles.collectHead}>
            <span className={styles.collectIcon} aria-hidden="true">
              <FiHelpCircle />
            </span>
            <span className={styles.collectEyebrow}>내용증명 작성 중</span>
          </div>

          <ProgressBar progress={progress} />

          {nextQuestion && <p className={styles.question}>{nextQuestion}</p>}

          {missingLabels.length > 0 && (
            <div className={styles.missingChips}>
              <span className={styles.missingLabel}>남은 정보</span>
              {missingLabels.map((label) => (
                <span className={styles.missingChip} key={label}>
                  {label}
                </span>
              ))}
            </div>
          )}
        </div>
      )}

      {/* 완성된 문서 */}
      {status === 'complete' && (
        <>
          <div className={styles.completeBadge}>
            <FiCheckCircle aria-hidden="true" />
            <span>필요한 정보를 모두 모았어요</span>
          </div>
          {document && <CompletedDocument document={document} />}
        </>
      )}
    </div>
  );
}

export default DocumentAnswer;