const ET_TIME_ZONE = 'America/New_York'

const isoFormatter = new Intl.DateTimeFormat('en-US', {
  hour: 'numeric',
  minute: '2-digit',
  hour12: true,
  timeZone: ET_TIME_ZONE,
})

function parseTimeOnly(raw: string): { hours: number; minutes: number } | null {
  const match = /^(\d{1,2}):(\d{2})(?::\d{2})?$/.exec(raw.trim())
  if (!match) return null
  const hours = Number(match[1])
  const minutes = Number(match[2])
  if (!Number.isInteger(hours) || !Number.isInteger(minutes)) return null
  if (hours < 0 || hours > 23 || minutes < 0 || minutes > 59) return null
  return { hours, minutes }
}

export function formatEtTime(value: string): string {
  const parsedTimeOnly = parseTimeOnly(value)
  if (parsedTimeOnly) {
    const { hours, minutes } = parsedTimeOnly
    const period = hours >= 12 ? 'PM' : 'AM'
    const hour12 = hours % 12 || 12
    return `${hour12}:${String(minutes).padStart(2, '0')} ${period}`
  }

  const parsedDate = new Date(value)
  if (Number.isNaN(parsedDate.getTime())) {
    return value
  }
  return isoFormatter.format(parsedDate)
}
