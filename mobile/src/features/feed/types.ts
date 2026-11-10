/** Subset of the contract's feed, post and comment schemas used by the app. */

export interface MediaRef {
  id: string;
  kind: 'image' | 'video' | 'audio';
  status: 'ready' | 'processing' | 'unavailable';
  url: string | null;
  width?: number | null;
  height?: number | null;
  alt_text?: string | null;
}

export interface UserSummary {
  id: string;
  handle: string;
  display_name: string;
  avatar: MediaRef | null;
}

export interface DestinationSummary {
  id: string;
  kind: string;
  slug: string;
  path: string;
  name: string;
  country_code: string;
  country_name?: string | null;
}

export type ReactionType = 'like' | 'love' | 'helpful' | 'wow';

export type PostKind =
  | 'text'
  | 'photo'
  | 'video'
  | 'story'
  | 'attraction_recommendation'
  | 'restaurant_recommendation'
  | 'review'
  | 'tip'
  | 'itinerary_summary'
  | 'experience';

export interface Post {
  id: string;
  author: UserSummary;
  kind: PostKind;
  body: string;
  language: string;
  visibility: string;
  primary_destination: DestinationSummary | null;
  tags: string[];
  media: MediaRef[];
  published_at: string;
  edited_at: string | null;
  counts: { reactions: number; comments: number; bookmarks: number; shares: number };
  /** Absent on guest (public) posts. */
  viewer?: {
    reaction: ReactionType | null;
    bookmarked: boolean;
    is_author: boolean;
    can_comment: boolean;
    can_delete: boolean;
  };
}

export type FeedTab = 'for_you' | 'nearby' | 'following' | 'destinations';
export type FeedSource =
  'gps' | 'selected' | 'upcoming_trip' | 'interests' | 'global' | 'following';

export interface FeedPage {
  data: Post[];
  page: { next_cursor: string | null; has_more: boolean; reset?: boolean };
  context?: {
    destination: DestinationSummary | null;
    source: FeedSource;
    radius_km: number | null;
  };
}

export interface Comment {
  id: string;
  post_id: string;
  author: UserSummary | null;
  body: string | null;
  deleted: boolean;
  created_at: string;
  viewer?: { can_edit: boolean; can_delete: boolean };
  parent_comment_id?: string | null;
  reply_count?: number;
}

export interface Page<T> {
  data: T[];
  page: { next_cursor: string | null; has_more: boolean };
}
