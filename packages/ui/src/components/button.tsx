import * as React from 'react';
import { Slot } from 'radix-ui';
import { cva, type VariantProps } from 'class-variance-authority';
import { cn } from '../lib/cn';

export const buttonVariants = cva(
  [
    'inline-flex items-center justify-center gap-2 rounded-pill font-semibold whitespace-nowrap select-none',
    'transition-[background-color,color,box-shadow,transform] duration-200 ease-travel',
    'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background',
    'disabled:pointer-events-none disabled:opacity-50 aria-disabled:pointer-events-none aria-disabled:opacity-50',
    'active:scale-[0.98] motion-reduce:transition-none motion-reduce:active:scale-100',
    '[&_svg]:size-[1.1em] [&_svg]:shrink-0',
  ],
  {
    variants: {
      variant: {
        primary: 'bg-primary text-primary-foreground hover:bg-primary-hover shadow-sm',
        accent: 'bg-accent text-accent-foreground hover:bg-accent-hover shadow-sm',
        secondary: 'bg-surface text-foreground border border-border hover:bg-surface-muted',
        ghost: 'text-foreground hover:bg-surface-muted',
        soft: 'bg-primary-soft text-primary-strong hover:brightness-95',
        danger: 'bg-danger text-white hover:brightness-110',
        link: 'text-primary underline-offset-4 hover:underline rounded-sm px-0 h-auto',
        inverse: 'bg-white/95 text-[#17252a] hover:bg-white shadow-sm',
      },
      size: {
        sm: 'h-9 px-4 text-sm',
        md: 'h-11 px-5 text-sm',
        lg: 'h-13 px-7 text-base',
        icon: 'size-10 p-0',
        'icon-sm': 'size-8 p-0',
      },
    },
    defaultVariants: { variant: 'primary', size: 'md' },
  },
);

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  /** Render the child element (e.g. a Next.js `Link`) with button styles. */
  asChild?: boolean;
  loading?: boolean;
}

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, asChild = false, loading = false, disabled, children, ...props }, ref) => {
    const Comp = asChild ? Slot.Root : 'button';
    return (
      <Comp
        ref={ref}
        className={cn(buttonVariants({ variant, size }), className)}
        disabled={asChild ? undefined : disabled || loading}
        aria-busy={loading || undefined}
        {...props}
      >
        {asChild ? (
          children
        ) : (
          <>
            {loading ? <Spinner className="size-4" /> : null}
            {children}
          </>
        )}
      </Comp>
    );
  },
);
Button.displayName = 'Button';

export function Spinner({ className, label }: { className?: string; label?: string }) {
  return (
    <svg
      className={cn('size-5 animate-spin motion-reduce:animate-none', className)}
      viewBox="0 0 24 24"
      fill="none"
      role={label ? 'img' : undefined}
      aria-label={label}
      aria-hidden={label ? undefined : true}
    >
      <circle cx="12" cy="12" r="10" stroke="currentColor" strokeOpacity="0.25" strokeWidth="3" />
      <path d="M22 12a10 10 0 0 0-10-10" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
    </svg>
  );
}
