import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import type { Assignment, Employee, Shift } from '@/lib/api'
import { cn } from '@/lib/utils'

interface TeamScheduleViewProps {
  shifts: Shift[]
  assignments: Assignment[]
  employees: Employee[]
  currentEmployeeId?: string | null
  weekStartDate?: string
}

// Generates 14 consecutive day entries starting from startIso (YYYY-MM-DD).
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

// Returns a short category/time-of-day tag for a shift cell.
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

  const shiftsByDayIso = new Map(days.map((day) => [day.iso, [] as Shift[]]))
  for (const shift of shiftsInWindow) {
    shiftsByDayIso.get(shift.date)?.push(shift)
  }
  const weeks = [days.slice(0, 7), days.slice(7, 14)]

  return (
    <Card className="border-primary/15">
      <CardHeader className="border-b border-border/60 bg-gradient-hero">
        <CardTitle className="text-lg">Team Schedule</CardTitle>
      </CardHeader>
      <CardContent className="p-0">
        <div className="space-y-6 p-4">
          {weeks.map((weekDays, weekIndex) => (
            <section className="space-y-0 rounded-xl border border-border/60" key={`team-week-${weekIndex}`}>
              <div className="border-b border-border/60 bg-muted/30 px-4 py-2 text-sm font-semibold text-foreground">
                Week {weekIndex + 1}
              </div>
              <div className="grid grid-cols-7 border-b border-border/60">
                {weekDays.map((day) => (
                  <div className="border-r border-border/60 p-3 text-center last:border-r-0" key={`team-hdr-${day.key}`}>
                    <p className="text-xs font-semibold text-muted-foreground">{day.dayLabel}</p>
                    <p className="mt-1 text-base font-bold text-foreground">{new Date(`${day.iso}T00:00:00`).getDate()}</p>
                  </div>
                ))}
              </div>
              <div className="grid grid-cols-7">
                {weekDays.map((day) => {
                  const dayShifts = shiftsByDayIso.get(day.iso) ?? []
                  return (
                    <div className="min-h-[260px] space-y-2 border-r border-border/60 p-2 last:border-r-0" key={`team-body-${day.key}`}>
                      {dayShifts.length === 0 ? (
                        <div className="grid h-full place-items-center rounded-lg border border-dashed border-border/80 text-xs text-muted-foreground/60">
                          Off
                        </div>
                      ) : (
                        dayShifts.map((shift) => {
                          const employeeIds = assignmentsByShiftId.get(shift.id) ?? []
                          const tag = shiftTag(shift)
                          const hasCurrentEmployee = currentEmployeeId ? employeeIds.includes(currentEmployeeId) : false
                          return (
                            <div
                              className={cn(
                                'rounded-lg border p-2 text-xs',
                                hasCurrentEmployee
                                  ? 'border-blue-500/60 bg-blue-500/15 shadow-[0_0_0_1px_rgba(59,130,246,0.25)]'
                                  : 'border-border/75 bg-card',
                              )}
                              key={shift.id}
                            >
                              <div className="flex items-center justify-between gap-2">
                                <p className="font-semibold text-foreground">
                                  {shift.start_time} - {shift.end_time}
                                </p>
                                <span className={cn('rounded-md px-2 py-0.5 text-[10px] font-semibold', roleClass(tag))}>{tag}</span>
                              </div>
                              <p className={cn('mt-1', hasCurrentEmployee ? 'text-blue-700 font-medium' : 'text-muted-foreground')}>
                                {employeeIds.length === 0
                                  ? 'No team member assigned'
                                  : employeeIds.map((employeeId) => displayEmployeeName(employeeId, employeeNameById)).join(', ')}
                              </p>
                              {hasCurrentEmployee ? <p className="mt-1 text-[11px] font-semibold text-blue-700">Your shift</p> : null}
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
      </CardContent>
    </Card>
  )
}
