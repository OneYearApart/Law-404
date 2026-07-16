export const CHATBOT_CATEGORIES = Object.freeze({
  'before-contract': {
    title: '계약 전 상담',
    prompt: '계약 전에 확인할 내용을 질문해 주세요.',
    reply:
      '계약 전 상담 기준으로 확인하겠습니다. 임대인과 등기부 소유자가 같은지, 대리 계약이라면 위임장과 인감증명서가 있는지부터 확인해 주세요.',
  },
  'during-contract': {
    title: '계약 중 상담',
    prompt: '계약 중 확인할 조항이나 상황을 입력해 주세요.',
    reply:
      '계약 중 상담 기준으로 살펴보겠습니다. 금액과 지급일, 임대인 정보, 특약의 책임 범위가 서로 충돌하지 않는지 확인해 주세요.',
  },
  'after-contract': {
    title: '계약 후 상담',
    prompt: '계약 후 해야 할 절차를 질문해 주세요.',
    reply:
      '계약 후 상담 기준으로 안내하겠습니다. 입주일과 잔금일을 기준으로 전입신고, 확정일자, 임대차 신고 일정을 먼저 정리해 주세요.',
  },
  // 전세사기(D)는 실제 백엔드에 연결돼 있어 고정 reply를 쓰지 않는다.
  'jeonse-fraud': {
    title: '전세사기 상담',
    prompt: '의심되는 상황이나 위험 신호를 입력해 주세요.',
  },
});

export const createEmptyConversations = () =>
  Object.fromEntries(Object.keys(CHATBOT_CATEGORIES).map((key) => [key, []]));
