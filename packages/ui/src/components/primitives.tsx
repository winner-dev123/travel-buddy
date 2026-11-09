import * as React from 'react';
import { Avatar as AvatarPrimitive, Label as LabelPrimitive, VisuallyHidden as VH } from 'radix-ui';
import { cva, type VariantProps } from 'class-variance-authority';
import { cn } from '../lib/cn';

// ---- Layout ----------------------------------------------------------------------------------

export function Container({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn('mx-auto w-full max-w-7xl px-4 sm:px-6 lg:px-8', className)} {...props} />;
}

export const VisuallyHidden = VH.Root;

// ---- Card ------------------------------------------------------------------------------------

export const Card = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(
  ({ className, ...props }, ref) => (
    <div
      ref={ref}
      className={cn('rounded-card border border-border bg-surface text-foreground shadow-card', className)}
      {...props}
    />
  ),
);
Card.displayName = 'Card';

// ---- Badge -----------------------------------------------------------------------------------

export const badgeVariants = cva(
  'inline-flex items-center gap-1 rounded-pill px-2.5 py-0.5 text-xs font-semibold [&_svg]:size-3.5',
  {
    variants: {
      tone: {
        neutral: 'bg-surface-muted text-foreground',
        primary: 'bg-primary-soft text-primary-strong',
        secondary: 'bg-secondary-soft text-foreground',
        accent: 'bg-accent-soft text-foreground',
        outline: 'border border-border text-muted-foreground',
        warning: 'bg-warning/15 text-warning',
        inverse: 'bg-black/45 text-white backdrop-blur-sm',
      },
    },
    defaultVariants: { tone: 'neutral' },
  },
);

export function Badge({
  className,
  tone,
  ...props
}: React.HTMLAttributes<HTMLSpanElement> & VariantProps<typeof badgeVariants>) {
  return <span className={cn(badgeVariants({ tone }), className)} {...props} />;
}

// ---- Form controls ---------------------------------------------------------------------------

const fieldBase =
  'w-full rounded-xl border border-input bg-surface px-3.5 text-sm text-foreground placeholder:text-muted-foreground ' +
  'transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:border-transparent ' +
  'disabled:cursor-not-allowed disabled:opacity-60 aria-invalid:border-danger aria-invalid:ring-danger/30';

export const Input = React.forwardRef<HTMLInputElement, React.InputHTMLAttributes<HTMLInputElement>>(
  ({ className, type = 'text', ...props }, ref) => (
    <input ref={ref} type={type} className={cn(fieldBase, 'h-11', className)} {...props} />
  ),
);
Input.displayName = 'Input';

export const Textarea = React.forwardRef<HTMLTextAreaElement, React.TextareaHTMLAttributes<HTMLTextAreaElement>>(
  ({ className, ...props }, ref) => (
    <textarea ref={ref} className={cn(fieldBase, 'min-h-24 py-3 leading-relaxed', className)} {...props} />
  ),
);
Textarea.displayName = 'Textarea';

export const NativeSelect = React.forwardRef<HTMLSelectElement, React.SelectHTMLAttributes<HTMLSelectElement>>(
  ({ className, ...props }, ref) => (
    <select ref={ref} className={cn(fieldBase, 'h-11 appearance-auto pe-8', className)} {...props} />
  ),
);
NativeSelect.displayName = 'NativeSelect';

export const Label = React.forwardRef<
  React.ComponentRef<typeof LabelPrimitive.Root>,
  React.ComponentPropsWithoutRef<typeof LabelPrimitive.Root>
>(({ className, ...props }, ref) => (
  <LabelPrimitive.Root ref={ref} className={cn('text-sm font-semibold text-foreground', className)} {...props} />
));
Label.displayName = 'Label';

/**
 * Label + control + hint + error with correct ARIA wiring. The child control receives `id`,
 * `aria-describedby` and `aria-invalid`.
 */
export function FormField({
  id,
  label,
  hint,
  error,
  required,
  className,
  children,
}: {
  id: string;
  label: React.ReactNode;
  hint?: React.ReactNode;
  error?: React.ReactNode;
  required?: boolean;
  className?: string;
  children: React.ReactElement<{ id?: string; 'aria-describedby'?: string; 'aria-invalid'?: boolean; 'aria-required'?: boolean }>;
}) {
  const hintId = hint ? `${id}-hint` : undefined;
  const errorId = error ? `${id}-error` : undefined;
  const describedBy = [hintId, errorId].filter(Boolean).join(' ') || undefined;
  return (
    <div className={cn('flex flex-col gap-1.5', className)}>
      <Label htmlFor={id}>
        {label}
        {required ? <span aria-hidden="true" className="ms-0.5 text-danger">*</span> : null}
      </Label>
      {React.cloneElement(children, {
        id,
        'aria-describedby': describedBy,
        'aria-invalid': error ? true : undefined,
        'aria-required': required || undefined,
      })}
      {hint ? (
        <p id={hintId} className="text-xs text-muted-foreground">
          {hint}
        </p>
      ) : null}
      {error ? (
        <p id={errorId} role="alert" className="text-xs font-medium text-danger">
          {error}
        </p>
      ) : null}
    </div>
  );
}

/** A pill that toggles (interests, categories). Uses `aria-pressed`. */
export function ToggleChip({
  pressed,
  className,
  children,
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement> & { pressed: boolean }) {
  return (
    <button
      type="button"
      aria-pressed={pressed}
      className={cn(
        'inline-flex h-10 items-center gap-2 rounded-pill border px-4 text-sm font-medium transition-colors duration-200',
        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background',
        pressed
          ? 'border-primary bg-primary text-primary-foreground'
          : 'border-border bg-surface text-foreground hover:border-primary/50',
        '[&_svg]:size-4',
        className,
      )}
      {...props}
    >
      {children}
    </button>
  );
}

// ---- Avatar ----------------------------------------------------------------------------------

const AVATAR_TONES = ['bg-primary-soft text-primary-strong', 'bg-secondary-soft text-foreground', 'bg-accent-soft text-foreground'];

function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  return ((parts[0]?.[0] ?? '') + (parts.length > 1 ? (parts[parts.length - 1]?.[0] ?? '') : '')).toUpperCase() || '?';
}

export function Avatar({
  name,
  src,
  size = 40,
  className,
}: {
  name: string;
  src?: string | null;
  size?: number;
  className?: string;
}) {
  const tone = AVATAR_TONES[[...name].reduce((a, c) => a + c.charCodeAt(0), 0) % AVATAR_TONES.length];
  return (
    <AvatarPrimitive.Root
      className={cn('relative inline-flex shrink-0 overflow-hidden rounded-full', className)}
      style={{ width: size, height: size }}
    >
      {src ? <AvatarPrimitive.Image src={src} alt="" className="size-full object-cover" /> : null}
      <AvatarPrimitive.Fallback
        className={cn('flex size-full items-center justify-center font-semibold', tone)}
        style={{ fontSize: Math.max(11, size * 0.38) }}
        aria-hidden="true"
      >
        {initials(name)}
      </AvatarPrimitive.Fallback>
    </AvatarPrimitive.Root>
  );
}

// ---- Feedback --------------------------------------------------------------------------------

export function Skeleton({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      aria-hidden="true"
      className={cn('animate-pulse rounded-lg bg-surface-muted motion-reduce:animate-none', className)}
      {...props}
    />
  );
}

export function EmptyState({
  icon,
  title,
  description,
  action,
  className,
}: {
  icon?: React.ReactNode;
  title: React.ReactNode;
  description?: React.ReactNode;
  action?: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={cn('flex flex-col items-center gap-3 rounded-card border border-dashed border-border px-6 py-12 text-center', className)}>
      {icon ? <div className="flex size-12 items-center justify-center rounded-full bg-primary-soft text-primary [&_svg]:size-6">{icon}</div> : null}
      <h3 className="font-display text-xl font-semibold">{title}</h3>
      {description ? <p className="max-w-md text-sm text-muted-foreground">{description}</p> : null}
      {action ? <div className="mt-2">{action}</div> : null}
    </div>
  );
}

export function Alert({
  tone = 'info',
  title,
  children,
  className,
}: {
  tone?: 'info' | 'warning' | 'danger' | 'success';
  title?: React.ReactNode;
  children?: React.ReactNode;
  className?: string;
}) {
  const tones = {
    info: 'border-info/30 bg-info/8',
    warning: 'border-warning/40 bg-warning/10',
    danger: 'border-danger/40 bg-danger/8',
    success: 'border-success/40 bg-success/8',
  } as const;
  return (
    <div role={tone === 'danger' ? 'alert' : 'status'} className={cn('rounded-xl border px-4 py-3 text-sm', tones[tone], className)}>
      {title ? <p className="font-semibold">{title}</p> : null}
      {children ? <div className="text-muted-foreground [&_a]:text-primary [&_a]:underline">{children}</div> : null}
    </div>
  );
}
