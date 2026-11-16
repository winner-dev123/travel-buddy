import type { Inquiry, Offering } from './api';

/** "R$ 150" / "€25": an indicative price in the reader's language. */
export function formatPrice(price: NonNullable<Offering['price_from']>, locale: string): string {
  const digits = ['JPY', 'KRW', 'CLP', 'VND', 'ISK'].includes(price.currency) ? 0 : 2;
  try {
    return new Intl.NumberFormat(locale, {
      style: 'currency',
      currency: price.currency,
      minimumFractionDigits: price.amount_minor % 10 ** digits === 0 ? 0 : digits,
      maximumFractionDigits: digits,
    }).format(price.amount_minor / 10 ** digits);
  } catch {
    return `${price.currency} ${(price.amount_minor / 10 ** digits).toFixed(digits)}`;
  }
}

/** Minor units from what someone typed ("150", "150,50", "1.234,5"). */
export function parseAmount(input: string): number | null {
  const cleaned = input.replace(/\s/g, '');
  if (!cleaned) return null;
  const match = cleaned.match(/^(\d{1,3}(?:[.,]\d{3})*|\d+)(?:[.,](\d{1,2}))?$/);
  if (!match) return null;
  const whole = Number((match[1] ?? '').replace(/[.,]/g, ''));
  const cents = match[2] ? Number(match[2].padEnd(2, '0')) : 0;
  return whole * 100 + cents;
}

/** "3 h", "1 h 30 min", "2 days" (rounded) for an offering. */
export function durationParts(minutes: number): { days: number; hours: number; mins: number } {
  if (minutes >= 24 * 60) return { days: Math.round(minutes / (24 * 60)), hours: 0, mins: 0 };
  return { days: 0, hours: Math.floor(minutes / 60), mins: minutes % 60 };
}

/** The request's dates in the reader's language, or null when flexible without a date. */
export function requestDates(inquiry: Pick<Inquiry, 'start_date' | 'end_date'>, locale: string) {
  const fmt = (iso: string) =>
    new Date(`${iso}T12:00:00Z`).toLocaleDateString(locale, {
      day: 'numeric',
      month: 'short',
      year: 'numeric',
      timeZone: 'UTC',
    });
  if (!inquiry.start_date) return null;
  if (!inquiry.end_date || inquiry.end_date === inquiry.start_date) return fmt(inquiry.start_date);
  return `${fmt(inquiry.start_date)} – ${fmt(inquiry.end_date)}`;
}

/** Hours (rounded up, at least 1) for "usually replies within N hours". */
export function responseHours(seconds: number): number {
  return Math.max(1, Math.ceil(seconds / 3600));
}

/** ISO date (YYYY-MM-DD) `days` after today in local time. */
export function isoDaysFromToday(days: number, today = new Date()): string {
  const date = new Date(today.getFullYear(), today.getMonth(), today.getDate() + days);
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  return `${date.getFullYear()}-${month}-${day}`;
}

export function isIsoDate(value: string): boolean {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const date = new Date(`${value}T00:00:00Z`);
  return !Number.isNaN(date.getTime()) && date.toISOString().startsWith(value);
}
