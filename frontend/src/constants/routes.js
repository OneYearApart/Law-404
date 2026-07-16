export const ROUTES = Object.freeze({
  LANDING: '/',
  LOGIN: '/login',
  SIGNUP: '/signup',
  CHAT_BEFORE_CONTRACT: '/chat/before-contract',
  CHAT_DURING_CONTRACT: '/chat/during-contract',
  CHAT_AFTER_CONTRACT: '/chat/after-contract',
  CHAT_JEONSE_FRAUD: '/chat/jeonse-fraud',
});

export const CHAT_ROUTES = Object.freeze([
  {
    key: 'before-contract',
    label: '계약 전',
    path: ROUTES.CHAT_BEFORE_CONTRACT,
  },
  {
    key: 'during-contract',
    label: '계약 중',
    path: ROUTES.CHAT_DURING_CONTRACT,
  },
  {
    key: 'after-contract',
    label: '계약 후',
    path: ROUTES.CHAT_AFTER_CONTRACT,
  },
  {
    key: 'jeonse-fraud',
    label: '전세사기',
    path: ROUTES.CHAT_JEONSE_FRAUD,
  },
]);
