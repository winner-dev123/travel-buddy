'use client';

import * as React from 'react';
import { Dialog as DialogPrimitive, Switch as SwitchPrimitive, Tabs as TabsPrimitive } from 'radix-ui';
import { X } from 'lucide-react';
import { cn } from '../lib/cn';

// ---- Dialog ----------------------------------------------------------------------------------

export const Dialog = DialogPrimitive.Root;
export const DialogTrigger = DialogPrimitive.Trigger;
export const DialogClose = DialogPrimitive.Close;

export function DialogContent({
  className,
  children,
  title,
  description,
  closeLabel,
  ...props
}: React.ComponentPropsWithoutRef<typeof DialogPrimitive.Content> & {
  title: React.ReactNode;
  description?: React.ReactNode;
  /** Accessible label of the close button (translated by the caller). */
  closeLabel: string;
}) {
  return (
    <DialogPrimitive.Portal>
      <DialogPrimitive.Overlay className="fixed inset-0 z-50 bg-overlay data-[state=open]:animate-in data-[state=open]:fade-in-0" />
      <DialogPrimitive.Content
        className={cn(
          'fixed z-50 flex max-h-[92dvh] w-full flex-col gap-4 overflow-y-auto bg-surface p-6 shadow-lift',
          'inset-x-0 bottom-0 rounded-t-card sm:inset-auto sm:start-1/2 sm:top-1/2 sm:max-w-lg sm:-translate-y-1/2 sm:rounded-card sm:ltr:-translate-x-1/2 sm:rtl:translate-x-1/2',
          'focus-visible:outline-none',
          className,
        )}
        {...props}
      >
        <div className="flex items-start justify-between gap-4">
          <div className="flex flex-col gap-1">
            <DialogPrimitive.Title className="font-display text-xl font-semibold">{title}</DialogPrimitive.Title>
            {description ? (
              <DialogPrimitive.Description className="text-sm text-muted-foreground">{description}</DialogPrimitive.Description>
            ) : (
              <DialogPrimitive.Description className="sr-only">{title}</DialogPrimitive.Description>
            )}
          </div>
          <DialogPrimitive.Close
            className="rounded-full p-1.5 text-muted-foreground hover:bg-surface-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            aria-label={closeLabel}
          >
            <X className="size-5" aria-hidden="true" />
          </DialogPrimitive.Close>
        </div>
        {children}
      </DialogPrimitive.Content>
    </DialogPrimitive.Portal>
  );
}

// ---- Tabs ------------------------------------------------------------------------------------

export const Tabs = TabsPrimitive.Root;
export const TabsContent = TabsPrimitive.Content;

export function TabsList({ className, ...props }: React.ComponentPropsWithoutRef<typeof TabsPrimitive.List>) {
  return (
    <TabsPrimitive.List
      className={cn('inline-flex items-center gap-1 rounded-pill bg-surface-muted p-1', className)}
      {...props}
    />
  );
}

export function TabsTrigger({ className, ...props }: React.ComponentPropsWithoutRef<typeof TabsPrimitive.Trigger>) {
  return (
    <TabsPrimitive.Trigger
      className={cn(
        'inline-flex h-9 items-center gap-1.5 rounded-pill px-4 text-sm font-semibold text-muted-foreground transition-colors',
        'hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
        'data-[state=active]:bg-surface data-[state=active]:text-foreground data-[state=active]:shadow-sm',
        '[&_svg]:size-4',
        className,
      )}
      {...props}
    />
  );
}

// ---- Switch ----------------------------------------------------------------------------------

export function Switch({ className, ...props }: React.ComponentPropsWithoutRef<typeof SwitchPrimitive.Root>) {
  return (
    <SwitchPrimitive.Root
      className={cn(
        'peer inline-flex h-6 w-11 shrink-0 cursor-pointer items-center rounded-full border-2 border-transparent transition-colors',
        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background',
        'disabled:cursor-not-allowed disabled:opacity-50 data-[state=checked]:bg-primary data-[state=unchecked]:bg-input',
        className,
      )}
      {...props}
    >
      <SwitchPrimitive.Thumb className="pointer-events-none block size-5 rounded-full bg-white shadow-sm transition-transform data-[state=checked]:translate-x-5 data-[state=unchecked]:translate-x-0 rtl:data-[state=checked]:-translate-x-5" />
    </SwitchPrimitive.Root>
  );
}
