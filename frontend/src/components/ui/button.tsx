import * as React from 'react'
import { cva, type VariantProps } from 'class-variance-authority'
import { cn } from '@/lib/utils'

const buttonVariants = cva(
  'inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-[12px] text-sm font-semibold transition-all duration-200 disabled:pointer-events-none disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2',
  {
    variants: {
      variant: {
        default: 'bg-primary text-primary-foreground shadow-[0_10px_20px_rgba(15,118,110,0.2)] hover:bg-primary/95 hover:shadow-[0_14px_24px_rgba(15,118,110,0.24)]',
        gradient:
          'gradient-primary text-primary-foreground shadow-[0_10px_20px_rgba(15,118,110,0.24)] hover:brightness-105 hover:shadow-[0_16px_28px_rgba(15,118,110,0.28)]',
        success:
          'bg-[color:var(--success)] text-white shadow-[0_8px_18px_rgba(16,185,129,0.25)] hover:brightness-105',
        destructive:
          'bg-destructive text-white shadow-[0_8px_18px_rgba(220,38,38,0.22)] hover:brightness-105',
        outline: 'border border-input bg-background/90 text-foreground hover:border-primary/35 hover:bg-accent/70',
        ghost: 'text-muted-foreground hover:bg-accent/70 hover:text-accent-foreground',
      },
      size: {
        default: 'h-10 px-4 py-2',
        sm: 'h-9 px-3 text-xs',
        lg: 'h-11 px-8 text-base',
      },
    },
    defaultVariants: {
      variant: 'default',
      size: 'default',
    },
  },
)

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {}

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, ...props }, ref) => (
    <button className={cn(buttonVariants({ variant, size, className }))} ref={ref} {...props} />
  ),
)
Button.displayName = 'Button'

export { Button }
