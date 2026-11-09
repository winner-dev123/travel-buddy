import { z } from 'zod';
import {
  FEED_TABS,
  POST_KINDS,
  POST_VISIBILITIES,
  REPORT_REASONS,
  SUPPORTED_LOCALES,
  TRAVEL_STYLES,
  type FeedTab,
} from '@travelbuddy/domain-types';
import { parseNearParam } from './location';

/**
 * Client-side mirrors of contract constraints (contracts/openapi/openapi.yaml). The backend
 * re-validates everything; these exist for immediate, translated form feedback.
 * Messages are i18n keys (namespace `validation`), not English text.
 */
export const V = {
  required: 'validation.required',
  tooShort: 'validation.tooShort',
  tooLong: 'validation.tooLong',
  invalid: 'validation.invalid',
  mustAccept: 'validation.mustAccept',
  tooMany: 'validation.tooMany',
  underage: 'validation.underage',
  passwordMismatch: 'validation.passwordMismatch',
} as const;

/** Limits copied from the contract schemas (UpdateMyProfileRequest, CreatePostRequest, …). */
export const LIMITS = {
  displayName: { min: 1, max: 50 },
  handle: { min: 3, max: 30 },
  bio: { max: 300 },
  postBody: { max: 5000 },
  tags: { max: 10, itemMax: 40 },
  comment: { max: 2000 },
  reportDetails: { max: 1000 },
  travelStyles: { max: 9 },
  mediaPerPost: { max: 10 },
  searchQuery: { min: 2, max: 80 },
} as const;

export const localeSchema = z.enum(SUPPORTED_LOCALES);
export const travelStyleSchema = z.enum(TRAVEL_STYLES);
export const uuidSchema = z.string().uuid({ message: V.invalid });

export const displayNameSchema = z
  .string()
  .trim()
  .min(LIMITS.displayName.min, { message: V.required })
  .max(LIMITS.displayName.max, { message: V.tooLong });

export const handleSchema = z.string().trim().toLowerCase().regex(/^[a-z0-9_.]{3,30}$/, { message: V.invalid });
export const emailSchema = z.string().trim().toLowerCase().email({ message: V.invalid });
export const countryCodeSchema = z.string().regex(/^[A-Z]{2}$/, { message: V.invalid });
export const bioSchema = z.string().trim().max(LIMITS.bio.max, { message: V.tooLong });
export const travelStylesSchema = z.array(travelStyleSchema).max(LIMITS.travelStyles.max, { message: V.tooMany });

/** Minimum age at launch (PRD AUTH-008). The backend is authoritative and answers `age_restricted`. */
export const MINIMUM_AGE = 18;

/** Whole years between an ISO birth date and `today` (both interpreted as calendar dates). */
export function ageOn(birthDate: string, today: Date = new Date()): number | null {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(birthDate);
  if (!match) return null;
  const [y, m, d] = [Number(match[1]), Number(match[2]), Number(match[3])];
  const probe = new Date(Date.UTC(y, m - 1, d));
  if (probe.getUTCFullYear() !== y || probe.getUTCMonth() !== m - 1 || probe.getUTCDate() !== d) return null;
  let age = today.getUTCFullYear() - y;
  const beforeBirthday = today.getUTCMonth() + 1 < m || (today.getUTCMonth() + 1 === m && today.getUTCDate() < d);
  if (beforeBirthday) age -= 1;
  return age;
}

export const birthDateSchema = z
  .string()
  .min(1, { message: V.required })
  .refine((v) => {
    const age = ageOn(v);
    return age !== null && age >= 0 && age < 130;
  }, { message: V.invalid })
  .refine((v) => (ageOn(v) ?? 0) >= MINIMUM_AGE, { message: V.underage });

/**
 * Registration details collected by the web before `POST /v1/auth/register`. The birth date is
 * sent once for the age gate; the platform stores only the birth year.
 */
export const registerSchema = z.object({
  display_name: displayNameSchema,
  email: emailSchema,
  birth_date: birthDateSchema,
  terms_accepted: z.literal(true, { message: V.mustAccept }),
});
export type RegisterInput = z.infer<typeof registerSchema>;

/** Password rules for identity-provider accounts (Supabase Auth, ADR-0020). 72 is the bcrypt limit. */
export const PASSWORD_LIMITS = { min: 8, max: 72 } as const;
export const passwordSchema = z
  .string()
  .min(PASSWORD_LIMITS.min, { message: V.tooShort })
  .max(PASSWORD_LIMITS.max, { message: V.tooLong });

/** Email + password registration: the platform fields plus the IdP password. */
export const passwordRegisterSchema = registerSchema.extend({ password: passwordSchema });
export type PasswordRegisterInput = z.infer<typeof passwordRegisterSchema>;

export const emailSignInSchema = z.object({
  email: emailSchema,
  password: z.string().min(1, { message: V.required }).max(PASSWORD_LIMITS.max, { message: V.tooLong }),
});
export type EmailSignInInput = z.infer<typeof emailSignInSchema>;

/** Finishing registration after the IdP step (social sign-in or an expired signup flow). */
export const completeRegistrationSchema = registerSchema.pick({ birth_date: true, terms_accepted: true });
export type CompleteRegistrationInput = z.infer<typeof completeRegistrationSchema>;

export const resetPasswordSchema = z
  .object({ password: passwordSchema, confirm: z.string() })
  .refine((v) => v.password === v.confirm, { message: V.passwordMismatch, path: ['confirm'] });
export type ResetPasswordInput = z.infer<typeof resetPasswordSchema>;

export const tagSchema = z.string().trim().min(1).max(LIMITS.tags.itemMax, { message: V.tooLong });

/** Mirrors CreatePostRequest. */
export const createPostSchema = z
  .object({
    kind: z.enum(POST_KINDS),
    body: z.string().trim().min(1, { message: V.required }).max(LIMITS.postBody.max, { message: V.tooLong }),
    visibility: z.enum(POST_VISIBILITIES),
    location_precision: z.enum(['none', 'destination', 'place']),
    destination_id: uuidSchema.optional(),
    place_id: uuidSchema.optional(),
    tags: z.array(tagSchema).max(LIMITS.tags.max, { message: V.tooMany }).optional(),
    media_ids: z.array(uuidSchema).max(LIMITS.mediaPerPost.max, { message: V.tooMany }).optional(),
  })
  .refine((p) => p.location_precision === 'none' || Boolean(p.destination_id), {
    message: V.required,
    path: ['destination_id'],
  })
  .refine((p) => p.location_precision !== 'place' || Boolean(p.place_id), { message: V.required, path: ['place_id'] });
export type CreatePostInput = z.infer<typeof createPostSchema>;

export const commentSchema = z.object({
  body: z.string().trim().min(1, { message: V.required }).max(LIMITS.comment.max, { message: V.tooLong }),
});

export const reportSchema = z.object({
  reason: z.enum(REPORT_REASONS),
  details: z.string().trim().max(LIMITS.reportDetails.max, { message: V.tooLong }).optional(),
  also_block: z.boolean().optional(),
});
export type ReportInput = z.infer<typeof reportSchema>;

export const searchQuerySchema = z.string().trim().min(LIMITS.searchQuery.min).max(LIMITS.searchQuery.max);

/** URL feed tab slugs use hyphens (`for-you`); the API uses snake_case (`for_you`). */
export const FEED_TAB_SLUGS: Record<FeedTab, string> = {
  for_you: 'for-you',
  nearby: 'nearby',
  following: 'following',
  destinations: 'destinations',
};

export function feedTabFromSlug(slug: string | null | undefined): FeedTab {
  const entry = Object.entries(FEED_TAB_SLUGS).find(([, s]) => s === slug);
  return (entry?.[0] as FeedTab | undefined) ?? 'for_you';
}

export const feedQuerySchema = z.object({
  tab: z.enum(FEED_TABS),
  destination_id: uuidSchema.nullish(),
  near: z
    .string()
    .nullish()
    .refine((v) => v == null || parseNearParam(v) !== null, { message: V.invalid }),
  radius_km: z.number().int().min(1).max(50).nullish(),
  cursor: z.string().max(512).nullish(),
  limit: z.number().int().min(1).max(100).optional(),
});
