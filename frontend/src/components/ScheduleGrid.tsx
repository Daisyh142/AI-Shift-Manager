import type { ScheduleRunResponse, Shift } from '@/lib/api'
import { cn } from '@/lib/utils'
import { formatEtTime } from '@/lib/time'

interface ScheduleGridProps {
  scheduleRun: ScheduleRunResponse
  shifts: Shift[]
  employeeNameById: Record<string, string>
  title?: string
  onlyAssignedShifts?: boolean
  emptyMessage?: string
}

interface ShiftCard {
  id: string
  startTime: string
  endTime: string
  employeeLabel: string
  roleLabel: string
}

function buildTwoWeekDays(weekStartDate: Date) {
  return Array.from({ length: 14 }, (_, index) => {
    const date = new Date(weekStartDate)
    date.setDate(weekStartDate.getDate() + index)
    const iso = date.toISOString().slice(0, 10)
    const dayLabel = date.toLocaleDateString('en-US', { weekday: 'short' })
    return { dayLabel, iso, key: `${iso}-${index}` }
  })
}

function shiftRoleLabel(shift: Shift) {
  if (shift.required_role) return formatRoleLabel(shift.required_role)
  if (shift.required_category) return formatRoleLabel(shift.required_category)
  const startHour = Number(shift.start_time.slice(0, 2))
  if (startHour < 12) return 'Morning'
  if (startHour < 17) return 'Afternoon'
  if (startHour < 22) return 'Evening'
  return 'Night'
}

function formatRoleLabel(raw: string) {
  const normalized = raw.toLowerCase().replace(/[-_]/g, ' ')
  if (normalized.includes('cook')) return 'Cook'
  if (normalized === 'shift lead') return 'Shift Lead'
  if (normalized === 'manager') return 'Manager'
  return normalized.replace(/\b\w/g, (letter) => letter.toUpperCase())
}

function shiftRoleColorClass(roleLabel: string) {
  const value = roleLabel.toLowerCase()
  if (value.includes('morning')) return 'bg-primary/15 text-primary border-primary/30'
  if (value.includes('afternoon')) return 'bg-accent/50 text-accent-foreground border-accent/80'
  if (value.includes('evening')) return 'bg-[color:var(--warning)]/15 text-[color:var(--warning)] border-[color:var(--warning)]/30'
  if (value.includes('night')) return 'bg-muted text-muted-foreground border-border'
  return 'bg-secondary text-foreground border-border'
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

function buildDayCards(dayShifts: Shift[], assignmentsByShiftId: Map<string, string[]>, employeeNameById: Record<string, string>) {
  const cards: ShiftCard[] = []

  for (const shift of dayShifts) {
    const assignedEmployeeIds = assignmentsByShiftId.get(shift.id) ?? []
    const roleLabel = shiftRoleLabel(shift)

    assignedEmployeeIds.forEach((employeeId, index) => {
      cards.push({
        id: `${shift.id}-assigned-${employeeId}-${index}`,
        startTime: shift.start_time,
        endTime: shift.end_time,
        employeeLabel: displayEmployeeName(employeeId, employeeNameById),
        roleLabel,
      })
    })

    const openSlots = Math.max(shift.required_staff - assignedEmployeeIds.length, 0)
    for (let slotIndex = 0; slotIndex < openSlots; slotIndex += 1) {
      cards.push({
        id: `${shift.id}-open-${slotIndex}`,
        startTime: shift.start_time,
        endTime: shift.end_time,
        employeeLabel: 'Open shift',
        roleLabel,
      })
    }
  }

  return cards.sort((a, b) => parseTimeToMinutes(a.startTime) - parseTimeToMinutes(b.startTime))
}

export function ScheduleGrid({
  scheduleRun,
  shifts,
  employeeNameById,
  title = 'Schedule Preview',
  onlyAssignedShifts = false,
  emptyMessage = 'No assignments available for this run yet.',
}: ScheduleGridProps) {
  const assignmentsByShiftId = new Map<string, string[]>()

  for (const assignment of scheduleRun.schedule.assignments) {
    const existing = assignmentsByShiftId.get(assignment.shift_id) ?? []
    existing.push(assignment.employee_id)
    assignmentsByShiftId.set(assignment.shift_id, existing)
  }

  const weekStart = scheduleRun.schedule.week_start_date
  const weekStartDate = new Date(`${weekStart}T00:00:00`)
  const weekEndDate = new Date(weekStartDate)
  weekEndDate.setDate(weekStartDate.getDate() + 13)
  const days = buildTwoWeekDays(weekStartDate)

  const shiftsForWeek = shifts
    .filter((shift) => {
      const shiftDate = new Date(`${shift.date}T00:00:00`)
      return shiftDate >= weekStartDate && shiftDate <= weekEndDate
    })
    .sort((a, b) => {
      const dateCompare = a.date.localeCompare(b.date)
      if (dateCompare !== 0) return dateCompare
      return a.start_time.localeCompare(b.start_time)
    })
  const displayedShifts = onlyAssignedShifts
    ? shiftsForWeek.filter((shift) => (assignmentsByShiftId.get(shift.id) ?? []).length > 0)
    : shiftsForWeek
  const distinctShiftDates = new Set(displayedShifts.map((shift) => shift.date))
  const hasIncompleteTwoWeekData = distinctShiftDates.size > 0 && distinctShiftDates.size < 14

  const shiftsByDayIso = new Map(days.map((day) => [day.iso, [] as Shift[]]))
  for (const shift of displayedShifts) {
    shiftsByDayIso.get(shift.date)?.push(shift)
  }
  const weeks = [days.slice(0, 7), days.slice(7, 14)]
  const todayIso = localIsoDate(new Date())

  return (
    <div className="space-y-4">
      {hasIncompleteTwoWeekData ? (
        <p className="rounded-xl border border-warning/30 bg-warning/10 px-4 py-3 text-sm text-warning-foreground">
          Warning: this run has shifts on {distinctShiftDates.size} of 14 days. Missing days show as Off.
        </p>
      ) : null}
      {displayedShifts.length === 0 ? (
        <div className="rounded-2xl border border-border/50 bg-card px-6 py-8 text-sm text-muted-foreground">{emptyMessage}</div>
      ) : (
        weeks.map((weekDays, weekIndex) => {
          const weekDate = new Date(`${weekDays[0]?.iso ?? weekStart}T00:00:00`)
          return (
            <section className="overflow-hidden rounded-2xl border border-border/50 bg-card" key={`week-${weekIndex}`}>
              <div className="border-b border-border/50 bg-gradient-hero p-4">
                <div className="flex items-center justify-between">
                  <h3 className="font-semibold text-foreground">
                    {title} {weeks.length > 1 ? `- Week ${weekIndex + 1}` : null}
                  </h3>
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
                      key={`hdr-${day.key}`}
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
                  const dayCards = buildDayCards(dayShifts, assignmentsByShiftId, employeeNameById)
                  return (
                    <div className="space-y-2 border-r border-border/50 p-2 last:border-r-0" key={`body-${day.key}`}>
                      {dayShifts.length === 0 ? (
                        <div className="flex h-full min-h-[140px] items-center justify-center">
                          <span className="text-xs text-muted-foreground/50">Off</span>
                        </div>
                      ) : (
                        dayCards.map((card) => (
                          <div className={cn('rounded-lg border p-2 text-xs', shiftRoleColorClass(card.roleLabel))} key={card.id}>
                            <p className="font-medium">{card.employeeLabel}</p>
                            <p className="mt-1 opacity-80">
                              {formatEtTime(card.startTime)} - {formatEtTime(card.endTime)}
                            </p>
                          </div>
                        ))
                      )}
                    </div>
                  )
                })}
              </div>
            </section>
          )
        })
      )}
    </div>
  )
}
