import type { Assignment, Employee, Shift } from '@/lib/api'
import { cn } from '@/lib/utils'
import { formatEtTime } from '@/lib/time'

interface TeamScheduleViewProps {
  shifts: Shift[]
  assignments: Assignment[]
  employees: Employee[]
  currentEmployeeId?: string | null
  weekStartDate?: string
}

interface TeamShiftCard {
  id: string
  startTime: string
  endTime: string
  employeeLabel: string
  tag: string
  isCurrentEmployee: boolean
}

function buildTwoWeekDays(startIso: string) {
  const startDate = new Date(`${startIso}T00:00:00`)
  return Array.from({ length: 14 }, (_, index) => {
    const date = new Date(startDate)
    date.setDate(startDate.getDate() + index)
    const iso = date.toISOString().slice(0, 10)
    const dayLabel = date.toLocaleDateString('en-US', { weekday: 'short' })
    return { dayLabel, iso, key: `${iso}-${index}` }
  })
}

function shiftTag(shift: Shift) {
  if (shift.required_category) return formatRoleLabel(shift.required_category)
  if (shift.required_role) return formatRoleLabel(shift.required_role)
  const startHour = Number(shift.start_time.slice(0, 2))
  if (startHour < 12) return 'Morning'
  if (startHour < 17) return 'Afternoon'
  if (startHour < 22) return 'Evening'
  return 'Night'
}

function roleClass(tag: string) {
  const value = tag.toLowerCase()
  if (value.includes('morning')) return 'bg-primary/15 text-primary'
  if (value.includes('afternoon')) return 'bg-accent/40 text-accent-foreground'
  if (value.includes('evening')) return 'bg-[color:var(--warning)]/15 text-[color:var(--warning)]'
  return 'bg-muted text-muted-foreground'
}

function formatRoleLabel(raw: string) {
  const normalized = raw.toLowerCase().replace(/[-_]/g, ' ')
  if (normalized.includes('cook')) return 'Cook'
  if (normalized === 'shift lead') return 'Shift Lead'
  if (normalized === 'manager') return 'Manager'
  return normalized.replace(/\b\w/g, (letter) => letter.toUpperCase())
}

function displayEmployeeName(employeeId: string, employeeNameById: Record<string, string>) {
  if (employeeId.toLowerCase() === 'owner_id') return 'Owner'
  return employeeNameById[employeeId] ?? employeeId
}

function localIsoDate(date: Date) {
  const year = date.getFullYear()
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const dayOfMonth = String(date.getDate()).padStart(2, '0')
  return `${year}-${month}-${dayOfMonth}`
}

function parseTimeToMinutes(raw: string) {
  const [hoursPart = '0', minutesPart = '0'] = raw.split(':')
  const hours = Number(hoursPart)
  const minutes = Number(minutesPart)
  if (!Number.isFinite(hours) || !Number.isFinite(minutes)) return 0
  return hours * 60 + minutes
}

function buildTeamDayCards(
  dayShifts: Shift[],
  assignmentsByShiftId: Map<string, string[]>,
  employeeNameById: Record<string, string>,
  currentEmployeeId?: string | null,
) {
  const cards: TeamShiftCard[] = []

  for (const shift of dayShifts) {
    const employeeIds = assignmentsByShiftId.get(shift.id) ?? []
    const tag = shiftTag(shift)

    employeeIds.forEach((employeeId, index) => {
      cards.push({
        id: `${shift.id}-assigned-${employeeId}-${index}`,
        startTime: shift.start_time,
        endTime: shift.end_time,
        employeeLabel: displayEmployeeName(employeeId, employeeNameById),
        tag,
        isCurrentEmployee: Boolean(currentEmployeeId && employeeId === currentEmployeeId),
      })
    })

    const openSlots = Math.max(shift.required_staff - employeeIds.length, 0)
    for (let slotIndex = 0; slotIndex < openSlots; slotIndex += 1) {
      cards.push({
        id: `${shift.id}-open-${slotIndex}`,
        startTime: shift.start_time,
        endTime: shift.end_time,
        employeeLabel: 'Open shift',
        tag,
        isCurrentEmployee: false,
      })
    }
  }

  return cards.sort((a, b) => parseTimeToMinutes(a.startTime) - parseTimeToMinutes(b.startTime))
}

export function TeamScheduleView({ shifts, assignments, employees, currentEmployeeId, weekStartDate }: TeamScheduleViewProps) {
  const employeeNameById = Object.fromEntries(employees.map((employee) => [employee.id, employee.name]))
  const assignmentsByShiftId = new Map<string, string[]>()

  for (const assignment of assignments) {
    const existing = assignmentsByShiftId.get(assignment.shift_id) ?? []
    existing.push(assignment.employee_id)
    assignmentsByShiftId.set(assignment.shift_id, existing)
  }

  const fallbackWeekStart = shifts.map((shift) => shift.date).sort()[0]
  const startIso = weekStartDate ?? fallbackWeekStart ?? new Date().toISOString().slice(0, 10)
  const days = buildTwoWeekDays(startIso)
  const endIso = days[days.length - 1]?.iso ?? startIso

  const shiftsInWindow = [...shifts]
    .filter((shift) => shift.date >= startIso && shift.date <= endIso)
    .sort((a, b) => a.date.localeCompare(b.date) || a.start_time.localeCompare(b.start_time))
  const distinctShiftDates = new Set(shiftsInWindow.map((shift) => shift.date))
  const hasIncompleteTwoWeekData = distinctShiftDates.size > 0 && distinctShiftDates.size < 14

  const shiftsByDayIso = new Map(days.map((day) => [day.iso, [] as Shift[]]))
  for (const shift of shiftsInWindow) {
    shiftsByDayIso.get(shift.date)?.push(shift)
  }
  const weeks = [days.slice(0, 7), days.slice(7, 14)]
  const todayIso = localIsoDate(new Date())

  return (
    <div className="space-y-4">
      {hasIncompleteTwoWeekData ? (
        <p className="rounded-xl border border-warning/30 bg-warning/10 px-4 py-3 text-sm text-warning-foreground">
          Warning: this view has shifts on {distinctShiftDates.size} of 14 days. Missing days show as Off.
        </p>
      ) : null}
      {weeks.map((weekDays, weekIndex) => {
        const weekDate = new Date(`${weekDays[0]?.iso ?? startIso}T00:00:00`)
        return (
          <section className="overflow-hidden rounded-2xl border border-border/50 bg-card" key={`team-week-${weekIndex}`}>
            <div className="border-b border-border/50 bg-gradient-hero p-4">
              <div className="flex items-center justify-between">
                <h3 className="font-semibold text-foreground">Team Schedule {weeks.length > 1 ? `- Week ${weekIndex + 1}` : null}</h3>
                <span className="text-sm text-muted-foreground">
                  Week of {weekDate.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}
                </span>
              </div>
            </div>
            <div className="grid grid-cols-7 border-b border-border/50">
              {weekDays.map((day) => {
                const isToday = day.iso === todayIso
                return (
                  <div
                    className={cn('border-r border-border/50 p-3 text-center last:border-r-0', isToday && 'bg-primary/5')}
                    key={`team-hdr-${day.key}`}
                  >
                    <p className={cn('text-xs font-medium', isToday ? 'text-primary' : 'text-muted-foreground')}>{day.dayLabel}</p>
                    <p className={cn('mt-1 text-lg font-bold', isToday ? 'text-primary' : 'text-foreground')}>
                      {new Date(`${day.iso}T00:00:00`).getDate()}
                    </p>
                  </div>
                )
              })}
            </div>
            <div className="grid min-h-[220px] grid-cols-7">
              {weekDays.map((day) => {
                const dayShifts = shiftsByDayIso.get(day.iso) ?? []
                const dayCards = buildTeamDayCards(dayShifts, assignmentsByShiftId, employeeNameById, currentEmployeeId)
                return (
                  <div className="space-y-2 border-r border-border/50 p-2 last:border-r-0" key={`team-body-${day.key}`}>
                    {dayShifts.length === 0 ? (
                      <div className="flex h-full min-h-[140px] items-center justify-center">
                        <span className="text-xs text-muted-foreground/50">Off</span>
                      </div>
                    ) : (
                      dayCards.map((card) => (
                        <div
                          className={cn(
                            'rounded-lg border p-2 text-xs',
                            card.isCurrentEmployee
                              ? 'border-blue-500/60 bg-blue-500/15 shadow-[0_0_0_1px_rgba(59,130,246,0.2)]'
                              : 'border-border/60 bg-card',
                          )}
                          key={card.id}
                        >
                          <p className={cn('font-medium', card.isCurrentEmployee ? 'text-blue-700' : 'text-foreground')}>{card.employeeLabel}</p>
                          <p className={cn('mt-1 opacity-80', card.isCurrentEmployee ? 'text-blue-700' : 'text-muted-foreground')}>
                            {formatEtTime(card.startTime)} - {formatEtTime(card.endTime)}
                          </p>
                          <div className="mt-1 flex items-center justify-between gap-2">
                            <span className={cn('rounded px-1.5 py-0.5 text-[10px] font-semibold', roleClass(card.tag))}>{card.tag}</span>
                            {card.isCurrentEmployee ? <span className="text-[10px] font-semibold text-blue-700">Your shift</span> : null}
                          </div>
                        </div>
                      ))
                    )}
                  </div>
                )
              })}
            </div>
          </section>
        )
      })}
    </div>
  )
}
