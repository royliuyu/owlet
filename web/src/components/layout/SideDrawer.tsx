import type { ReactNode } from 'react'

export function SideDrawer({
  open,
  onClose,
  children,
}: {
  open: boolean
  onClose: () => void
  children: ReactNode
}) {
  if (!open) return null
  return (
    <div className="fixed inset-0 z-40 flex">
      <div className="flex h-full w-[min(20rem,88vw)] flex-col bg-paper-raised shadow-xl">
        {children}
      </div>
      <button type="button" className="flex-1 bg-ink/30" aria-label="Close menu" onClick={onClose} />
    </div>
  )
}
