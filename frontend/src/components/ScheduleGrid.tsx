import type { ScheduleRunResponse, Shift } from '@/lib/api'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { cn } from '@/lib/utils'

interface ScheduleGridProps {
  scheduleRun: ScheduleRunResponse
  shifts: Shift[]
  employeeNameById: Record<string, string>
  title?: string
  onlyAssignedShifts?: boolean
  emptyMessage?: string
}

// Generates an array of 14 consecutive day entries starting from weekStartDate.
function buildTwoWeekDays(weekStartDate: Date) {
  return Array.from({ length: 14 }, (_, index) => {
    const date = new Date(weekStartDate)
    date.setDate(weekStartDate.getDate() + index)
    const iso = date.toISOString().slice(0, 10)
    const dayLabel = date.toLocaleDateString('en-US', { weekday: 'short' })
    return { dayLabel, iso, key: `${iso}-${index}` }
  })
}

// Returns a display label for a shift based on its required role or time of day.
function shiftRoleLabel(shift: Shift) {
  if (shift.required_role) return formatRoleLabel(shift.required_role)
  if (shift.required_category) return formatRoleLabel(shift.required_category)
  const startHour = Number(shift.start_time.slice(0, 2))
  if (startHour < 12) return 'Morning'
  if (startHour < 17) return 'Afternoon'
  if (startHour < 22) return 'Evening'
  return 'Night'
}

// Normalizes a raw role string to a title-cased display label.
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

  const shiftsByDayIso = new Map(days.map((day) => [day.iso, [] as Shift[]]))
  for (const shift of displayedShifts) {
    shiftsByDayIso.get(shift.date)?.push(shift)
  }
  const weeks = [days.slice(0, 7), days.slice(7, 14)]

  return (
    <Card className="border-primary/15">
      <CardHeader className="border-b border-border/60 bg-gradient-hero">
        <CardTitle className="text-lg">{title}</CardTitle>
      </CardHeader>
      <CardContent className="p-0">
        {displayedShifts.length === 0 ? (
          <p className="px-6 py-8 text-sm text-muted-foreground">{emptyMessage}</p>
        ) : (
          <div className="space-y-6 p-4">
            {weeks.map((weekDays, weekIndex) => (
              <section className="space-y-0 rounded-xl border border-border/60" key={`week-${weekIndex}`}>
                <div className="border-b border-border/60 bg-muted/30 px-4 py-2 text-sm font-semibold text-foreground">
                  Week {weekIndex + 1}
                </div>
                <div className="grid grid-cols-7 border-b border-border/60">
                  {weekDays.map((day) => (
                    <div className="border-r border-border/60 p-3 text-center last:border-r-0" key={`hdr-${day.key}`}>
                      <p className="text-xs font-semibold text-muted-foreground">{day.dayLabel}</p>
                      <p className="mt-1 text-base font-bold text-foreground">{new Date(`${day.iso}T00:00:00`).getDate()}</p>
                    </div>
                  ))}
                </div>
                <div className="grid grid-cols-7">
                  {weekDays.map((day) => {
                    const dayShifts = shiftsByDayIso.get(day.iso) ?? []
                    return (
                      <div className="min-h-[260px] space-y-2 border-r border-border/60 p-2 last:border-r-0" key={`body-${day.key}`}>
                        {dayShifts.length === 0 ? (
                          <div className="grid h-full place-items-center rounded-lg border border-dashed border-border/80 text-xs text-muted-foreground/60">
                            Off
                          </div>
                        ) : (
                          dayShifts.map((shift) => {
                            const assignedEmployeeIds = assignmentsByShiftId.get(shift.id) ?? []
                            const roleLabel = shiftRoleLabel(shift)
                            return (
                              <div className={cn('rounded-lg border p-2 text-xs', shiftRoleColorClass(roleLabel))} key={shift.id}>
                                <p className="font-semibold">{roleLabel}</p>
                                <p className="mt-0.5 opacity-85">
                                  {shift.start_time} - {shift.end_time}
                                </p>
                                <p className="mt-1 opacity-85">
                                  {assignedEmployeeIds.length === 0
                                    ? `Unassigned (${shift.required_staff} needed)`
                                    : assignedEmployeeIds.map((employeeId) => displayEmployeeName(employeeId, employeeNameById)).join(', ')}
                                </p>
                              </div>
                            )
                          })
                        )}
                      </div>
                    )
                  })}
                </div>
              </section>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  )
}
