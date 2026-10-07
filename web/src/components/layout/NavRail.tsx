import { NavLink } from 'react-router-dom'
import { NAV } from '@/components/cards/registry'
import { cn } from '@/lib/cn'

export function Mark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" className={className} aria-hidden>
      <circle cx="12" cy="14" r="3" fill="#f3efe6" />
      <circle cx="20" cy="14" r="3" fill="#f3efe6" />
      <circle cx="12" cy="14" r="1.4" fill="#0e6b66" />
      <circle cx="20" cy="14" r="1.4" fill="#0e6b66" />
      <path d="M16 18 13.4 22.2h5.2Z" fill="#f3efe6" />
    </svg>
  )
}

export function NavRail() {
  return (
    <nav aria-label="Primary" className="flex w-16 shrink-0 flex-col items-center gap-1 bg-rail py-3">
      <Mark className="mb-3 h-8 w-8" />
      {NAV.map((item) => (
        <NavLink
          key={item.to}
          to={item.to}
          title={item.label}
          className={({ isActive }) =>
            cn(
              'flex h-11 w-11 items-center justify-center rounded-xl',
              isActive ? 'bg-rail-soft text-paper' : 'text-paper/55 hover:text-paper',
            )
          }
        >
          <item.icon size={18} aria-hidden />
          <span className="sr-only">{item.label}</span>
        </NavLink>
      ))}
    </nav>
  )
}
