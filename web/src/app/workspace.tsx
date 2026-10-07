import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { openSession, readToken } from '@/lib/api'
import type { OpenDocument, SourceKind } from '@/lib/types'
import { connectedSources } from '@/components/cards/registry'

type WorkspaceValue = {
  sources: SourceKind[]
  toggleSource: (kind: SourceKind) => void
  selection: OpenDocument | null
  openDocument: (document: OpenDocument) => void
  closeDocument: () => void
}

const WorkspaceContext = createContext<WorkspaceValue | null>(null)

export function WorkspaceProvider({ children }: { children: ReactNode }) {
  const [sources, setSources] = useState<SourceKind[]>(connectedSources)
  const [selection, setSelection] = useState<OpenDocument | null>(null)

  useEffect(() => {
    void openSession(readToken()).catch(() => undefined)
  }, [])

  const value = useMemo<WorkspaceValue>(
    () => ({
      sources,
      toggleSource(kind) {
        setSources((current) =>
          current.includes(kind) ? current.filter((item) => item !== kind) : [...current, kind],
        )
      },
      selection,
      openDocument: setSelection,
      closeDocument: () => setSelection(null),
    }),
    [selection, sources],
  )

  return <WorkspaceContext.Provider value={value}>{children}</WorkspaceContext.Provider>
}

export function useWorkspace(): WorkspaceValue {
  const value = useContext(WorkspaceContext)
  if (!value) throw new Error('useWorkspace must be used inside WorkspaceProvider')
  return value
}
