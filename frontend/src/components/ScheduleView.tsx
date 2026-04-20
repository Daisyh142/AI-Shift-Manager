import { cn } from '@/lib/utils';

interface Shift {
  id: string;
  day: string;
  startTime: string;
  endTime: string;
  role: string;
}

interface ScheduleViewProps {
  shifts: Shift[];
  isOwnerView?: boolean;
}

const daysOfWeek = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

const getShiftColor = (role: string) => {
  const colors: Record<string, string> = {
    Morning: 'bg-accent/20 border-accent text-accent',
    Afternoon: 'bg-primary/20 border-primary text-primary',
    Evening: 'bg-warning/20 border-warning text-warning',
    Night: 'bg-muted border-muted-foreground text-muted-foreground',
  };
  return colors[role] || 'bg-secondary border-border text-foreground';
};

export function ScheduleView({ shifts, isOwnerView = false }: ScheduleViewProps) {
  const currentDate = new Date();
  const weekStart = new Date(currentDate);
  weekStart.setDate(currentDate.getDate() - currentDate.getDay() + 1);

  const getShiftsForDay = (day: string) => {
    return shifts.filter((shift) => shift.day === day);
  };

  return (
    <div className="bg-card rounded-2xl border border-border/50 overflow-hidden">
      <div className="p-4 border-b border-border/50 bg-gradient-hero">
        <div className="flex items-center justify-between">
          <h3 className="font-semibold text-foreground">
            {isOwnerView ? 'Schedule Preview' : 'Your Schedule'}
          </h3>
          <span className="text-sm text-muted-foreground">
            Week of {weekStart.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}
          </span>
        </div>
      </div>

      <div className="grid grid-cols-7 border-b border-border/50">
        {daysOfWeek.map((day, index) => {
          const date = new Date(weekStart);
          date.setDate(weekStart.getDate() + index);
          const isToday = date.toDateString() === currentDate.toDateString();

          return (
            <div
              key={day}
              className={cn('p-3 text-center border-r last:border-r-0 border-border/50', isToday && 'bg-primary/5')}
            >
              <div className={cn('text-xs font-medium', isToday ? 'text-primary' : 'text-muted-foreground')}>
                {day}
              </div>
              <div className={cn('text-lg font-bold mt-1', isToday ? 'text-primary' : 'text-foreground')}>
                {date.getDate()}
              </div>
            </div>
          );
        })}
      </div>

      <div className="grid grid-cols-7 min-h-[200px]">
        {daysOfWeek.map((day) => {
          const dayShifts = getShiftsForDay(day);

          return (
            <div key={day} className="p-2 border-r last:border-r-0 border-border/50 space-y-2">
              {dayShifts.length > 0 ? (
                dayShifts.map((shift) => (
                  <div key={shift.id} className={cn('p-2 rounded-lg border text-xs', getShiftColor(shift.role))}>
                    <div className="font-medium">{shift.role}</div>
                    <div className="opacity-80 mt-1">
                      {shift.startTime} - {shift.endTime}
                    </div>
                  </div>
                ))
              ) : (
                <div className="h-full flex items-center justify-center">
                  <span className="text-xs text-muted-foreground/50">Off</span>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
