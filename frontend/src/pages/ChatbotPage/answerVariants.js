import AAssistantAnswer from './A/AssistantAnswer.jsx';
import BAssistantAnswer from './B/AssistantAnswer.jsx';
import CAssistantAnswer from './C/AssistantAnswer.jsx';
import DAssistantAnswer from './D/AssistantAnswer.jsx';

export const CHATBOT_ANSWER_COMPONENTS = Object.freeze({
  'before-contract': AAssistantAnswer,
  'during-contract': BAssistantAnswer,
  'after-contract': CAssistantAnswer,
  'jeonse-fraud': DAssistantAnswer,
});
