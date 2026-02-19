import { cn } from '@/lib/utils'

interface FairnessScoreProps {
  score: number
  size?: 'sm' | 'md' | 'lg'
  showLabel?: boolean
  label?: string
}

const sizeConfig = {
  sm: { dimension: 58, stroke: 4, scoreSize: 'text-sm', labelSize: 'text-xs' },
  md: { dimension: 96, stroke: 6, scoreSize: 'text-xl', labelSize: 'text-sm' },
  lg: { dimension: 130, stroke: 8, scoreSize: 'text-3xl', labelSize: 'text-base' },
}

function getScoreClass(score: number) {
  if (score >= 80) return 'text-[color:var(--success)] stroke-[color:var(--success)]'
  if (score >= 60) return 'text-primary stroke-primary'
  if (score >= 40) return 'text-[color:var(--warning)] stroke-[color:var(--warning)]'
  return 'text-destructive stroke-destructive'
}

export function FairnessScore({ score, size = 'md', showLabel = true, label }: FairnessScoreProps) {
  const clamped = Math.max(0, Math.min(100, score))
  const config = sizeConfig[size]
  const radius = (config.dimension - config.stroke) / 2
  const circumference = 2 * Math.PI * radius
  const dashOffset = circumference * (1 - clamped / 100)
  const scoreClass = getScoreClass(clamped)

  return (
    <div className="flex flex-col items-center gap-2">
      <div className="relative" style={{ height: config.dimension, width: config.dimension }}>
        <svg className="-rotate-90" height={config.dimension} width={config.dimension}>
          <circle
            className="fill-none stroke-border/75"
            cx={config.dimension / 2}
            cy={config.dimension / 2}
            r={radius}
            strokeWidth={config.stroke}
          />
          <circle
            className={cn('fill-none transition-all duration-700 ease-out', scoreClass.split(' ')[1])}
            cx={config.dimension / 2}
            cy={config.dimension / 2}
            r={radius}
            strokeDasharray={circumference}
            strokeDashoffset={dashOffset}
            strokeLinecap="round"
            strokeWidth={config.stroke}
          />
        </svg>
        <div className="absolute inset-0 grid place-items-center">
          <span className={cn('font-bold', config.scoreSize, scoreClass.split(' ')[0])}>{Math.round(clamped)}%</span>
        </div>
      </div>
      {showLabel ? <span className={cn('font-medium text-muted-foreground', config.labelSize)}>{label ?? 'Fairness'}</span> : null}
    </div>
  )
}
