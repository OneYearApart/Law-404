import { motion } from 'framer-motion';
import {
  FiAlertTriangle,
  FiArrowRight,
  FiBookOpen,
  FiCalendar,
  FiCheck,
  FiCheckCircle,
  FiClipboard,
  FiClock,
  FiCreditCard,
  FiEdit3,
  FiFileText,
  FiHelpCircle,
  FiHome,
  FiSearch,
  FiShield,
  FiUploadCloud,
  FiUserCheck,
} from 'react-icons/fi';
import { Link, Navigate } from 'react-router';

import { CHAT_ROUTES, ROUTES } from '../../constants/routes.js';
import { useAuth } from '../../contexts/AuthContext.jsx';
import styles from './LandingPage.module.css';

const categoryContent = {
  'before-contract': {
    eyebrow: '계약 상대방과 권리관계 확인',
    description: '임대인, 대리 권한, 등기부와 계약금 계좌를 계약 전에 확인합니다.',
    features: ['실제 소유자 확인', '대리 권한·위임장 확인', '등기부·송금 계좌 점검'],
    icon: FiClipboard,
  },
  'during-contract': {
    eyebrow: '계약서 문구와 지급 조건 점검',
    description: '계약 금액, 지급일, 특약과 책임 범위를 서명 전에 점검합니다.',
    features: ['계약 금액·지급 일정', '특약과 수리 책임', '서명·해지 조건 확인'],
    icon: FiEdit3,
  },
  'after-contract': {
    eyebrow: '잔금·입주·퇴거 절차 정리',
    description: '잔금일부터 입주, 신고와 보증금 반환까지 필요한 절차를 정리합니다.',
    features: ['잔금 전 등기부 재확인', '전입신고·확정일자', '퇴거·보증금 반환 준비'],
    icon: FiCheckCircle,
  },
  'jeonse-fraud': {
    eyebrow: '위험 신호 우선 대응',
    description: '권리관계 변동과 계좌·신원 불일치 위험을 일반 절차보다 먼저 확인합니다.',
    features: ['근저당·압류 변동', '임대인·계좌 불일치', '송금·서명 보류 판단'],
    icon: FiAlertTriangle,
  },
};

const featureSections = [
  {
    key: 'before-contract',
    label: '계약 전',
    title: '계약 전에 꼭 확인해야 할 내용을\n먼저 봅니다',
    description:
      '계약 상대방과 실제 소유자가 같은지, 대리 계약에 필요한 서류가 있는지, 최신 등기부와 송금 계좌가 안전한지 순서대로 확인합니다.',
    mascot: '/images/review.png',
    icon: FiClipboard,
    highlights: [
      {
        title: '실제 소유자 확인',
        text: '등기부의 소유자와 계약 상대방 정보를 비교합니다.',
        icon: FiUserCheck,
      },
      {
        title: '등기부·문서 위험 확인',
        text: '업로드한 계약서와 등기부에서 확인할 항목을 정리합니다.',
        icon: FiFileText,
      },
      {
        title: '계약금·예금주 점검',
        text: '송금 계좌의 예금주와 계약 관계를 다시 확인합니다.',
        icon: FiCreditCard,
      },
    ],
  },
  {
    key: 'during-contract',
    label: '계약 중',
    title: '계약서 문장과 조건 변경을\n한눈에 정리합니다',
    description:
      '계약 금액과 지급 일정, 특약 문구, 수리 책임과 중도 해지 조건처럼 나중에 분쟁이 생기기 쉬운 내용을 빠짐없이 비교합니다.',
    mascot: '/images/balance.png',
    icon: FiEdit3,
    highlights: [
      {
        title: '수리 책임과 하자 특약',
        text: '누가 언제까지 처리하는지 문장으로 남겼는지 확인합니다.',
        icon: FiHome,
      },
      {
        title: '관리비·세금 부담 범위',
        text: '금액과 포함 항목이 모호하지 않은지 점검합니다.',
        icon: FiBookOpen,
      },
      {
        title: '중도금·잔금 조건 대응',
        text: '지급일 변경이나 선지급 요청이 생겼을 때 확인할 순서를 안내합니다.',
        icon: FiCreditCard,
      },
    ],
  },
  {
    key: 'after-contract',
    label: '계약 후',
    title: '입주부터 보증금 반환까지\n절차를 순서대로 안내합니다',
    description:
      '잔금일과 입주일을 기준으로 전입신고, 확정일자, 임대차 신고를 정리하고 퇴거 통보와 보증금 반환 준비까지 이어서 확인합니다.',
    mascot: '/images/guide.png',
    icon: FiCalendar,
    highlights: [
      {
        title: '잔금 전 권리관계 재확인',
        text: '계약 뒤 새로 생긴 권리 변동이 없는지 최신 등기부를 다시 확인합니다.',
        icon: FiSearch,
      },
      {
        title: '전입신고·확정일자 정리',
        text: '입주일에 놓치지 않도록 필요한 순서와 준비물을 정리합니다.',
        icon: FiCalendar,
      },
      {
        title: '퇴거 통보·보증금 반환',
        text: '통보 시점과 반환 요청 기록을 남길 수 있도록 행동 순서를 안내합니다.',
        icon: FiClock,
      },
    ],
  },
  {
    key: 'jeonse-fraud',
    label: '전세사기',
    title: '위험 상황은 일반 흐름보다\n먼저 대응합니다',
    description:
      '추가 송금이나 서명을 바로 진행하지 않고, 위험 신호를 먼저 분류한 뒤 확인해야 할 자료와 공식 기관 재확인 순서를 안내합니다.',
    mascot: '/images/verdict.png',
    icon: FiAlertTriangle,
    highlights: [
      {
        title: '근저당·압류 변동',
        text: '계약 이후 권리관계가 달라졌다면 잔금 진행 전 다시 확인합니다.',
        icon: FiAlertTriangle,
      },
      {
        title: '임대인·계좌 정보 불일치',
        text: '신원이나 계좌가 바뀌었다면 송금을 보류하고 관계를 확인합니다.',
        icon: FiUserCheck,
      },
      {
        title: '긴급 대응 행동 정리',
        text: '계약 단계와 위험 수준에 따라 기록, 보류, 상담 순서를 안내합니다.',
        icon: FiShield,
      },
    ],
  },
];

const questionRows = [
  {
    stage: '계약 전',
    question: '집주인 아들이 대신 계약하러 왔는데 위임장 없이 계약해도 되나요?',
    route: ROUTES.CHAT_BEFORE_CONTRACT,
  },
  {
    stage: '계약 중',
    question: '특약에 수리 책임이 모호하게 적혀 있는데 그대로 서명해도 되나요?',
    route: ROUTES.CHAT_DURING_CONTRACT,
  },
  {
    stage: '계약 후',
    question: '잔금일과 입주일이 다른데 전입신고와 확정일자는 언제 해야 하나요?',
    route: ROUTES.CHAT_AFTER_CONTRACT,
  },
  {
    stage: '전세사기',
    question: '계약 뒤 집주인이 다른 계좌로 잔금을 보내 달라고 합니다.',
    route: ROUTES.CHAT_JEONSE_FRAUD,
  },
];

const answerSteps = [
  {
    number: '01',
    title: '상황 판단',
    description: '사용자가 말한 계약 단계와 현재까지 확인된 사실을 먼저 정리합니다.',
    icon: FiUserCheck,
  },
  {
    number: '02',
    title: '문서·근거 확인',
    description: '계약서와 등기부 등 관련 문서와 법률·안전 근거에서 필요한 내용을 확인합니다.',
    icon: FiFileText,
  },
  {
    number: '03',
    title: '다음 행동 안내',
    description: '지금 확인할 자료와 진행하거나 보류해야 할 행동을 우선순위대로 안내합니다.',
    icon: FiShield,
  },
];

function FeatureVisual({ section }) {
  return (
    <div className={`${styles.featureVisual} ${styles[`featureVisual_${section.key}`]}`}>
      <div className={styles.visualGlow} aria-hidden="true" />
      <div className={styles.visualStatus}>
        <span className={styles.statusDot} />
        {section.label} 상담
      </div>

      <div className={styles.featureVisualBody}>
        <img className={styles.featureMascot} src={section.mascot} alt="" aria-hidden="true" />

        <div className={styles.featureMockSlot}>
          {section.key === 'before-contract' && (
            <div className={`${styles.mockCard} ${styles.documentMock}`}>
              <div className={styles.mockHeader}>
                <span>계약 전 확인</span>
                <span className={styles.mockBadge}>3단계</span>
              </div>
              <div className={styles.mockQuestion}>계약 상대방이 등기부 소유자와 같은가요?</div>
              <div className={styles.choiceGrid}>
                <span>예</span>
                <span>아니요</span>
                <span>확인 중</span>
              </div>
              <div className={styles.mockProgress}>
                <span />
              </div>
            </div>
          )}

          {section.key === 'during-contract' && (
            <div className={`${styles.mockCard} ${styles.contractMock}`}>
              <div className={styles.mockHeader}>
                <span>특약 점검</span>
                <span className={styles.mockBadge}>비교</span>
              </div>
              <div className={styles.contractLine}>
                <FiCheck aria-hidden="true" />
                수리 책임 주체
              </div>
              <div className={styles.contractLine}>
                <FiCheck aria-hidden="true" />
                관리비 포함 범위
              </div>
              <div className={`${styles.contractLine} ${styles.contractLineWarning}`}>
                <FiAlertTriangle aria-hidden="true" />
                중도 해지 조건 확인 필요
              </div>
            </div>
          )}

          {section.key === 'after-contract' && (
            <div className={`${styles.mockCard} ${styles.calendarMock}`}>
              <div className={styles.mockHeader}>
                <span>입주일 절차</span>
                <span className={styles.mockBadge}>D-day</span>
              </div>
              <div className={styles.calendarTop}>
                <button type="button" aria-label="이전 달" tabIndex={-1}>
                  ‹
                </button>
                <strong>7월</strong>
                <button type="button" aria-label="다음 달" tabIndex={-1}>
                  ›
                </button>
              </div>
              <div className={styles.calendarGrid} aria-hidden="true">
                {Array.from({ length: 21 }, (_, index) => (
                  <span key={index} className={index === 10 || index === 16 ? styles.activeDate : ''}>
                    {index + 1}
                  </span>
                ))}
              </div>
              <div className={styles.calendarNotice}>잔금 확인 → 전입신고 → 확정일자</div>
            </div>
          )}

          {section.key === 'jeonse-fraud' && (
            <div className={`${styles.mockCard} ${styles.riskMock}`}>
              <div className={styles.riskIcon}>
                <FiShield aria-hidden="true" />
              </div>
              <div>
                <span className={styles.riskLabel}>확인 필요</span>
                <strong>추가 송금을 잠시 보류하세요</strong>
                <p>최신 등기부와 임대인·계좌 관계를 먼저 다시 확인해야 합니다.</p>
              </div>
              <div className={styles.riskAction}>확인할 항목 보기</div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function LandingPage() {
  const { status } = useAuth();

  if (status === 'loading') {
    return <main className={styles.loadingPage} aria-label="페이지를 불러오는 중" />;
  }

  if (status === 'authenticated') {
    return <Navigate to={ROUTES.CHAT_BEFORE_CONTRACT} replace />;
  }

  return (
    <main className={styles.page}>
      <section className={styles.hero} id="service-intro">
        <div className={styles.heroPattern} aria-hidden="true" />
        <motion.div
          className={styles.heroInner}
          initial={{ opacity: 0, y: 24 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.55, ease: 'easeOut' }}
        >
          <div className={styles.heroCopy}>
            <span className={styles.badge}>
              <FiShield aria-hidden="true" />
              주택 임대차 계약 AI 상담
            </span>
            <h1 className={styles.title}>
              <span>주택 임대차,</span>
              <span>
                계약 전부터 <em>보증금 반환까지</em>
              </span>
            </h1>
            <p className={styles.description}>
              계약 단계와 현재 상황을 확인하고, 놓치기 쉬운 위험 신호와 다음 행동을 이해하기
              쉽게 정리합니다.
            </p>
            <div className={styles.actions}>
              <motion.div whileHover={{ y: -3 }} whileTap={{ scale: 0.98 }}>
                <Link className={styles.primaryButton} to={ROUTES.LOGIN}>
                  로그인
                  <FiArrowRight aria-hidden="true" />
                </Link>
              </motion.div>
            </div>
          </div>

          <div className={styles.heroVisual} aria-hidden="true">
            <div className={styles.heroHalo} />
            <div className={styles.heroPanel}>
              <div className={styles.heroPanelTop}>
                <span className={styles.heroPanelLogo}>Law404</span>
                <span className={styles.onlineChip}>
                  <span /> 상담 준비
                </span>
              </div>
              <div className={styles.heroChatBubble}>
                오늘 계약서를 쓰러 가는데 무엇부터 확인해야 하나요?
              </div>
              <div className={styles.heroAnswerBubble}>
                <span>확인 순서</span>
                <strong>소유자 → 대리 권한 → 등기부 → 송금 계좌</strong>
              </div>
              <div className={styles.heroUploadChip}>
                <FiUploadCloud /> 계약서·등기부 PDF 확인
              </div>
            </div>
            <img className={styles.heroMascot} src="/images/consult.png" alt="" />
            <div className={`${styles.floatingCard} ${styles.floatingCardTop}`}>
              <FiFileText />
              <span>
                <strong>문서 확인</strong>
                계약서·등기부
              </span>
            </div>
            <div className={`${styles.floatingCard} ${styles.floatingCardBottom}`}>
              <FiShield />
              <span>
                <strong>위험 신호</strong>
                먼저 확인
              </span>
            </div>
          </div>
        </motion.div>
      </section>

      <section className={styles.categorySection} id="consultation-fields">
        <div className={styles.sectionInner}>
          <motion.div
            className={styles.sectionHeading}
            initial={{ opacity: 0, y: 18 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true, amount: 0.35 }}
          >
            <span>4가지 상담 카테고리</span>
            <h2>계약 단계에 따라 제공하는 기능을 확인하세요</h2>
            <p>계약 전, 계약 중, 계약 후, 전세사기 상황에서 확인할 핵심 기능을 나누어 안내합니다.</p>
          </motion.div>

          <div className={styles.categoryGrid}>
            {CHAT_ROUTES.map((route, index) => {
              const category = categoryContent[route.key];
              const Icon = category.icon;

              return (
                <motion.div
                  key={route.key}
                  initial={{ opacity: 0, y: 22 }}
                  whileInView={{ opacity: 1, y: 0 }}
                  viewport={{ once: true, amount: 0.25 }}
                  transition={{ delay: index * 0.07 }}
                  whileHover={{ y: -7 }}
                >
                  <article className={styles.categoryCard}>
                    <div className={styles.cardTop}>
                      <span className={styles.cardIcon}>
                        <Icon aria-hidden="true" />
                      </span>
                      <span className={styles.cardNumber}>{String(index + 1).padStart(2, '0')}</span>
                    </div>
                    <span className={styles.cardEyebrow}>{category.eyebrow}</span>
                    <h3>{route.label}</h3>
                    <p>{category.description}</p>
                    <ul className={styles.categoryFeatureList}>
                      {category.features.map((feature) => (
                        <li key={feature}>
                          <FiCheck aria-hidden="true" />
                          <span>{feature}</span>
                        </li>
                      ))}
                    </ul>
                  </article>
                </motion.div>
              );
            })}
          </div>
        </div>
      </section>

      <div className={styles.featureList}>
        {featureSections.map((section, index) => {
          const Icon = section.icon;

          return (
            <section
              className={`${styles.featureSection} ${index % 2 === 1 ? styles.featureSectionAlt : ''}`}
              key={section.key}
            >
              <div className={styles.sectionInner}>
                <motion.div
                  className={`${styles.featureGrid} ${index % 2 === 1 ? styles.featureGridReverse : ''}`}
                  initial={{ opacity: 0, y: 24 }}
                  whileInView={{ opacity: 1, y: 0 }}
                  viewport={{ once: true, amount: 0.18 }}
                  transition={{ duration: 0.45 }}
                >
                  <FeatureVisual section={section} />

                  <div className={styles.featureCopy}>
                    <span className={styles.featureBadge}>
                      <Icon aria-hidden="true" />
                      {section.label} 상담
                    </span>
                    <h2>
                      {section.title.split('\n').map((line) => (
                        <span key={line}>{line}</span>
                      ))}
                    </h2>
                    <p className={styles.featureDescription}>{section.description}</p>

                    <div className={styles.highlightList}>
                      {section.highlights.map((highlight) => {
                        const HighlightIcon = highlight.icon;

                        return (
                          <div className={styles.highlightCard} key={highlight.title}>
                            <span className={styles.highlightIcon}>
                              <HighlightIcon aria-hidden="true" />
                            </span>
                            <div>
                              <h3>{highlight.title}</h3>
                              <p>{highlight.text}</p>
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                </motion.div>
              </div>
            </section>
          );
        })}
      </div>

      <section className={styles.questionSection} id="questions">
        <div className={styles.sectionInner}>
          <motion.div
            className={styles.questionIntro}
            initial={{ opacity: 0, y: 18 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true, amount: 0.3 }}
          >
            <div className={styles.questionIntroCopy}>
              <span className={styles.simpleSectionLabel}>
                <FiHelpCircle aria-hidden="true" /> 대표 질문
              </span>
              <h2>계약 단계가 달라도 궁금한 상황을 그대로 물어보세요</h2>
              <p>어려운 법률 용어 대신 지금 겪고 있는 상황을 평소 말하듯 입력하면 됩니다.</p>
            </div>
            <img className={styles.questionMascot} src="/images/thinking.png" alt="" aria-hidden="true" />
          </motion.div>

          <motion.div
            className={styles.questionTable}
            initial={{ opacity: 0, y: 20 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true, amount: 0.2 }}
          >
            <div className={styles.questionHeader}>
              <span>단계</span>
              <span>질문 예시</span>
            </div>
            {questionRows.map((row) => (
              <div className={styles.questionRow} key={row.question}>
                <span className={styles.stageBadge}>{row.stage}</span>
                <strong>{row.question}</strong>
              </div>
            ))}
          </motion.div>
        </div>
      </section>

      <section className={styles.answerSection} id="answer-method">
        <div className={styles.sectionInner}>
          <motion.div
            className={styles.answerIntro}
            initial={{ opacity: 0, y: 18 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true, amount: 0.3 }}
          >
            <div>
              <span className={styles.answerEyebrow}>답변 방식</span>
              <h2>답변은 판단에서 끝나지 않고 다음 행동까지 이어집니다.</h2>
              <p>
                현재 상황을 정리하고 문서와 근거를 확인한 뒤, 사용자가 바로 실행할 수 있는
                행동까지 답변합니다.
              </p>
            </div>
            <img src="/images/explain.png" alt="" aria-hidden="true" />
          </motion.div>

          <div className={styles.answerGrid}>
            {answerSteps.map((step, index) => {
              const Icon = step.icon;

              return (
                <motion.div
                  className={styles.answerCard}
                  key={step.number}
                  initial={{ opacity: 0, y: 20 }}
                  whileInView={{ opacity: 1, y: 0 }}
                  viewport={{ once: true, amount: 0.25 }}
                  transition={{ delay: index * 0.08 }}
                >
                  <span className={styles.answerNumber}>{step.number}</span>
                  <span className={styles.answerIcon}>
                    <Icon aria-hidden="true" />
                  </span>
                  <h3>{step.title}</h3>
                  <p>{step.description}</p>
                </motion.div>
              );
            })}
          </div>

          <motion.div
            className={styles.answerCta}
            initial={{ opacity: 0, y: 18 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true, amount: 0.35 }}
          >
            <img className={styles.answerCtaMascot} src="/images/victory.png" alt="" aria-hidden="true" />
            <div className={styles.answerCtaCopy}>
              <h3>
                <span className={styles.ctaBrand}>
                  <span className={styles.ctaBrandLaw}>Law</span>
                  <span className={styles.ctaBrandNumber}>404</span>
                </span>{' '}
                챗봇을 활용해 계약 상황을 차근차근 확인해 보세요.
              </h3>
              <p>현재 단계와 확인한 사실을 구체적으로 입력하면 다음 확인 항목과 행동 순서를 안내합니다.</p>
            </div>
            <Link className={styles.answerCtaButton} to={ROUTES.LOGIN}>
              로그인
              <FiArrowRight aria-hidden="true" />
            </Link>
          </motion.div>
        </div>
      </section>
    </main>
  );
}

export default LandingPage;
