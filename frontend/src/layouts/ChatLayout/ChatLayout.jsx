import { Outlet } from 'react-router';

import AppHeader from '../../components/common/AppHeader/AppHeader.jsx';
import ChatSidebar from '../../components/chat/ChatSidebar/ChatSidebar.jsx';
import { ChatConversationProvider } from '../../contexts/ChatConversationContext.jsx';
import styles from './ChatLayout.module.css';

function ChatLayout() {
  return (
    <ChatConversationProvider>
      <div className={styles.layout}>
        <AppHeader variant="chat" />
        <div className={styles.workspace}>
          <ChatSidebar />
          <div className={styles.content}>
            <Outlet />
          </div>
        </div>
      </div>
    </ChatConversationProvider>
  );
}

export default ChatLayout;
