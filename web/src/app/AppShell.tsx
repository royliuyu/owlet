import { Menu, PanelRightOpen } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Outlet, useLocation } from 'react-router-dom'
import { useWorkspace } from '@/app/workspace'
import { ContextPanel } from '@/components/layout/ContextPanel'
import { MobileTabs } from '@/components/layout/MobileTabs'
import { NavRail } from '@/components/layout/NavRail'
import { ResizeHandle } from '@/components/layout/ResizeHandle'
import { Sidebar } from '@/components/layout/Sidebar'
import { SideDrawer } from '@/components/layout/SideDrawer'
import { cn } from '@/lib/cn'
import { useConversations } from '@/lib/conversations'
import { useBreakpoint, useStoredNumber, useStoredString, type ReaderSpan } from '@/lib/layout'

const TITLES: Record<string, string> = {
  today: 'Today',
  chat: 'Chat',
  library: 'Library',
  actions: 'Actions',
  settings: 'Settings',
}

/** Three shells: phone drawer + sheet, tablet overlay, wide three-column reader. */
export function AppShell() {
  const { pathname } = useLocation()
  const breakpoint = useBreakpoint()
  const [sideWidth, setSideWidth] = useStoredNumber('owlet.side', 280)
  const [contextWidth, setContextWidth] = useStoredNumber('owlet.context', 460)
  const [readerSpan, setReaderSpan] = useStoredString<ReaderSpan>('owlet.reader', 'split', [
    'split',
    'max',
    'min',
  ])
  const [drawerOpen, setDrawerOpen] = useState(false)
  const { selection, closeDocument } = useWorkspace()
  const residentNav = breakpoint === 'desktop' || breakpoint === 'wide'
  const onSettings = pathname.startsWith('/settings')
  const showConversations = residentNav && !onSettings
  const readerColumn = breakpoint === 'wide'
  const showReaderColumn = readerColumn && readerSpan !== 'min' && (!onSettings || Boolean(selection))
  const readerCovers = showReaderColumn && readerSpan === 'max'

  useEffect(() => {
    setDrawerOpen(false)
  }, [breakpoint])

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return
      setDrawerOpen(false)
      if (readerColumn && readerSpan === 'max') {
        setReaderSpan('split')
        return
      }
      if (!readerColumn) closeDocument()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [closeDocument, readerColumn, readerSpan, setReaderSpan])

  return (
    <div className="flex h-dvh flex-col bg-paper text-ink">
      <div className="flex min-h-0 flex-1">
        {residentNav ? <NavRail /> : null}
        {showConversations ? (
          <>
            <div className="min-h-0 shrink-0 border-r border-line" style={{ width: sideWidth }}>
              <Sidebar />
            </div>
            <ResizeHandle
              label="Resize conversations"
              onDelta={(dx) => setSideWidth(clamp(sideWidth + dx, 220, 420))}
            />
          </>
        ) : null}
        <div className="relative flex min-w-0 flex-1">
          <div
            className={cn('flex min-w-0 flex-1 flex-col', readerCovers && 'pointer-events-none')}
            inert={readerCovers ? true : undefined}
          >
            <TopBar
              showMenu={!residentNav}
              onMenu={() => setDrawerOpen(true)}
              onShowReader={
                readerColumn && readerSpan === 'min' && (!onSettings || selection)
                  ? () => setReaderSpan('split')
                  : undefined
              }
            />
            <div className="flex min-h-0 flex-1 flex-col">
              <Outlet />
            </div>
          </div>
          {showReaderColumn ? (
            <>
              {readerSpan === 'split' ? (
                <ResizeHandle
                  label="Resize reader"
                  onDelta={(dx) => setContextWidth(clamp(contextWidth - dx, 320, 760))}
                />
              ) : null}
              <div
                className={cn(
                  'min-h-0 border-l border-line bg-paper',
                  readerSpan === 'max' ? 'absolute inset-0 z-10 flex' : 'shrink-0',
                )}
                style={readerSpan === 'split' ? { width: contextWidth } : undefined}
              >
                <ContextPanel
                  mode="column"
                  span={readerSpan === 'max' ? 'max' : 'split'}
                  onSpan={setReaderSpan}
                />
              </div>
            </>
          ) : null}
        </div>
      </div>
      {breakpoint === 'mobile' ? <MobileTabs /> : null}
      {residentNav ? null : (
        <SideDrawer open={drawerOpen} onClose={() => setDrawerOpen(false)}>
          <Sidebar onNavigate={() => setDrawerOpen(false)} />
        </SideDrawer>
      )}
      {breakpoint === 'tablet' || breakpoint === 'desktop' ? (
        selection ? (
          <ContextPanel mode="overlay" width={Math.min(contextWidth, window.innerWidth - 48)} onClose={closeDocument} />
        ) : null
      ) : null}
      {breakpoint === 'mobile' && selection ? (
        <ContextPanel mode="sheet" onClose={closeDocument} />
      ) : null}
    </div>
  )
}

function TopBar({
  showMenu,
  onMenu,
  onShowReader,
}: {
  showMenu: boolean
  onMenu: () => void
  onShowReader?: () => void
}) {
  const title = useTitle()
  return (
    <header className="flex h-14 shrink-0 items-center gap-2 border-b border-line px-3">
      {showMenu ? (
        <button type="button" aria-label="Open menu" className="rounded-lg p-2 hover:bg-paper-raised" onClick={onMenu}>
          <Menu size={18} />
        </button>
      ) : null}
      <h1 className="truncate font-serif text-lg">{title}</h1>
      {onShowReader ? (
        <button
          type="button"
          onClick={onShowReader}
          className="ml-auto inline-flex items-center gap-1.5 rounded-full border border-line px-3 py-1 text-sm text-muted hover:bg-paper-raised hover:text-ink"
        >
          <PanelRightOpen size={16} />
          Reader
        </button>
      ) : null}
    </header>
  )
}

function useTitle(): string {
  const { pathname } = useLocation()
  const conversations = useConversations()
  const section = pathname.split('/').filter(Boolean)[0] ?? 'chat'
  if (section === 'chat') {
    const id = decodeURIComponent(pathname.slice('/chat/'.length))
    const conversation = conversations.find((item) => item.id === id)
    if (conversation) return conversation.title
  }
  return TITLES[section] ?? 'owlet'
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value))
}
