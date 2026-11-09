/** Horizontal "or" separator between social buttons and the email form. */
export function OrDivider({ label }: { label: string }) {
  return (
    <div className="flex items-center gap-3 text-xs font-semibold tracking-wide text-muted-foreground uppercase" role="separator" aria-label={label}>
      <span className="h-px flex-1 bg-border" aria-hidden="true" />
      <span aria-hidden="true">{label}</span>
      <span className="h-px flex-1 bg-border" aria-hidden="true" />
    </div>
  );
}
