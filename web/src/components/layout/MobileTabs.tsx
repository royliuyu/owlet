import { NavLink } from 'react-router-dom'
import { NAV } from '@/components/cards/registry'
import { cn } from '@/lib/cn'

export function MobileTabs() {
  return (
    <nav
      aria-label="Primary"
      className="grid grid-cols-5 border-t border-line bg-paper-raised pb-[env(safe-area-inset-bottom)]"
    >
      {NAV.map((item) => (
        <NavLink
          key={item.to}
          to={item.to}
          className={({ isActive }) =>
            cn(
              'flex flex-col items-center gap-1 py-2 text-[11px]',
              isActive ? 'text-accent' : 'text-muted',
            )
          }
        >
          <item.icon size={18} aria-hidden />
          {item.label}
        </NavLink>
      ))}
    </nav>
  )
}
