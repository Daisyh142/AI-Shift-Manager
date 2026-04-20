import type { Employee } from '@/lib/api'
import { ChevronRight } from 'lucide-react'
import { FairnessScore as FairnessRing } from '@/components/FairnessScore'
import { cn } from '@/lib/utils'

interface EmployeeCardProps {
  employee: Employee
  fairnessPercent: number | null
  onClick?: () => void
}

export function EmployeeCard({ employee, fairnessPercent, onClick }: EmployeeCardProps) {
  const initials = employee.name
    .split(' ')
    .map((namePart) => namePart[0])
    .join('')
    .slice(0, 2)

  const roleLabel = formatRoleLabel(employee.role)

  return (
    <article
      className={cn(
        'rounded-xl border border-border/65 bg-card p-4 transition-all',
        onClick ? 'cursor-pointer hover:border-primary/35 hover:shadow-card-hover' : 'hover:shadow-card',
      )}
      onClick={onClick}
    >
      <div className="flex items-center gap-4">
        <div className="relative">
          <div className="flex h-12 w-12 items-center justify-center rounded-full gradient-primary text-sm font-semibold text-primary-foreground">
            {initials}
          </div>
          <div className="absolute -bottom-1 -right-1 h-4 w-4 rounded-full border-2 border-card bg-[color:var(--success)]" />
        </div>

        <div className="min-w-0 flex-1">
          <h4 className="truncate font-semibold text-foreground">{employee.name}</h4>
          <p className="text-sm text-muted-foreground">{roleLabel}</p>
          <p className="mt-1 text-xs text-muted-foreground">
            {employee.required_weekly_hours.toFixed(0)}h target | {employee.max_weekly_hours.toFixed(0)}h max
          </p>
        </div>

        <EmployeeFairness fairnessPercent={fairnessPercent} />

        {onClick ? <ChevronRight className="h-5 w-5 text-muted-foreground" /> : null}
      </div>
    </article>
  )
}

function formatRoleLabel(raw: string) {
  const normalized = raw.toLowerCase().replace(/[-_]/g, ' ')
  if (normalized === 'shift lead' || normalized === 'shiftlead') return 'Shift Lead'
  if (normalized === 'manager') return 'Manager'
  if (normalized.includes('cook')) return 'Cook'
  if (normalized === 'regular') return 'Team Member'
  return normalized.replace(/\b\w/g, (letter) => letter.toUpperCase())
}

function EmployeeFairness({ fairnessPercent }: { fairnessPercent: number | null }) {
  if (fairnessPercent === null) {
    return <span className="rounded-lg bg-muted px-3 py-2 text-xs font-semibold text-muted-foreground">N/A</span>
  }
  return <FairnessRing score={fairnessPercent} showLabel={false} size="sm" />
}
