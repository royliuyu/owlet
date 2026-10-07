import { Navigate, createBrowserRouter } from 'react-router-dom'
import { AppShell } from '@/app/AppShell'
import { WorkspaceProvider } from '@/app/workspace'
import { ChatView } from '@/components/chat/ChatView'
import { LibraryView } from '@/components/library/LibraryView'
import { ActionsView } from '@/components/pages/ActionsView'
import { SettingsView } from '@/components/pages/SettingsView'
import { TodayView } from '@/components/pages/TodayView'

export const router = createBrowserRouter([
  {
    path: '/',
    element: (
      <WorkspaceProvider>
        <AppShell />
      </WorkspaceProvider>
    ),
    children: [
      { index: true, element: <Navigate to="/chat" replace /> },
      { path: 'chat/:id?', element: <ChatView /> },
      { path: 'today', element: <TodayView /> },
      { path: 'library', element: <LibraryView /> },
      { path: 'library/:collectionId', element: <LibraryView /> },
      { path: 'actions', element: <ActionsView /> },
      { path: 'settings', element: <SettingsView /> },
    ],
  },
])
