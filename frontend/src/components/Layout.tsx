import { useMemo, useState, type ReactNode } from 'react'
import { Link, useLocation } from 'wouter'
import {
  BarChart3,
  CalendarDays,
  ClipboardList,
  Home,
  LogOut,
  Menu,
  Sparkles,
  type LucideIcon,
} from 'lucide-react'
import type { AuthUser, UserRole } from '@/lib/api'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

interface LayoutProps {
  user: AuthUser
  onLogout: () => void
  children: ReactNode
}

interface NavItem {
  href: string
  label: string
  icon: LucideIcon
}

const ownerNav: NavItem[] = [
  { href: '/dashboard', label: 'Dashboard', icon: Home },
  { href: '/requests', label: 'Requests', icon: ClipboardList },
  { href: '/analytics', label: 'Analytics', icon: BarChart3 },
]

const employeeNav: NavItem[] = [
  { href: '/dashboard', label: 'Dashboard', icon: Home },
  { href: '/team-schedule', label: 'Team Schedule', icon: CalendarDays },
  { href: '/my-requests', label: 'My Requests', icon: ClipboardList },
]

function roleLabel(role: UserRole) {
  return role === 'owner' ? 'Owner' : 'Employee'
}

export function Layout({ user, onLogout, children }: LayoutProps) {
  const [location] = useLocation()
  const [isMobileMenuOpen, setIsMobileMenuOpen] = useState(false)

  const navItems = useMemo(() => (user.role === 'owner' ? ownerNav : employeeNav), [user.role])

  return (
    <div className="min-h-screen bg-background">
      <header className="sticky top-0 z-40 border-b border-border/70 bg-background/85 backdrop-blur-lg">
        <div className="mx-auto flex h-16 w-full max-w-[1240px] items-center justify-between px-4 md:px-6">
          <div className="flex items-center gap-3">
            <div className="shadow-glow flex h-10 w-10 items-center justify-center rounded-xl gradient-primary">
              <Sparkles className="h-5 w-5 text-primary-foreground" />
            </div>
            <div>
              <p className="text-sm font-semibold tracking-wide text-foreground">ShiftManagerAI</p>
              <p className="text-xs text-muted-foreground">{roleLabel(user.role)} workspace</p>
            </div>
          </div>

          <nav className="hidden items-center gap-2 md:flex">
            {navItems.map((item) => {
              const Icon = item.icon
              const isActive = location === item.href || location.startsWith(`${item.href}/`)
              return (
                <Link
                  className={cn(
                    'inline-flex items-center gap-2 rounded-xl px-3 py-2 text-sm font-medium transition-all',
                    isActive
                      ? 'gradient-primary text-primary-foreground shadow-glow'
                      : 'text-muted-foreground hover:bg-accent/70 hover:text-accent-foreground',
                  )}
                  href={item.href}
                  key={item.href}
                >
                  <Icon className="h-4 w-4" />
                  <span>{item.label}</span>
                </Link>
              )
            })}
          </nav>

          <div className="hidden items-center gap-3 md:flex">
            <div className="rounded-xl border border-border/70 bg-card px-3 py-1.5 text-right">
              <p className="max-w-[180px] truncate text-xs font-medium text-foreground">{user.email}</p>
              <p className="text-[11px] text-muted-foreground">{roleLabel(user.role)}</p>
            </div>
            <Button onClick={onLogout} size="sm" variant="outline">
              <LogOut className="h-4 w-4" />
              Log out
            </Button>
          </div>

          <Button className="md:hidden" onClick={() => setIsMobileMenuOpen(true)} size="sm" variant="outline">
            <Menu className="h-4 w-4" />
            Menu
          </Button>
        </div>
      </header>

      {isMobileMenuOpen ? (
        <div className="fixed inset-0 z-50 md:hidden">
          <button
            aria-label="Close navigation"
            className="absolute inset-0 bg-black/50"
            onClick={() => setIsMobileMenuOpen(false)}
            type="button"
          />
          <aside className="relative h-full w-72 max-w-[85vw] border-r border-border/70 bg-card p-4">
            <nav className="space-y-2">
              {navItems.map((item) => {
                const Icon = item.icon
                const isActive = location === item.href || location.startsWith(`${item.href}/`)
                return (
                  <Link
                    className={cn(
                      'flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium transition-all',
                      isActive
                        ? 'gradient-primary text-primary-foreground shadow-glow'
                        : 'text-muted-foreground hover:bg-accent/70 hover:text-accent-foreground',
                    )}
                    href={item.href}
                    key={item.href}
                    onClick={() => setIsMobileMenuOpen(false)}
                  >
                    <Icon className="h-4 w-4" />
                    <span>{item.label}</span>
                  </Link>
                )
              })}
            </nav>
            <div className="mt-4 rounded-xl border border-border/70 bg-muted/50 p-3">
              <p className="truncate text-sm font-medium text-foreground">{user.email}</p>
              <p className="text-xs text-muted-foreground">{roleLabel(user.role)}</p>
            </div>
            <Button className="mt-3 w-full" onClick={onLogout} variant="outline">
              <LogOut className="h-4 w-4" />
              Log out
            </Button>
          </aside>
        </div>
      ) : null}

      <main className="px-4 py-6 md:px-8 md:py-8">
        <div className="mx-auto w-full max-w-[1220px] animate-in fade-in duration-300">{children}</div>
      </main>
    </div>
  )
}
