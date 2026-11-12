import type { ImageSourcePropType } from 'react-native';

/**
 * The gift catalog (DM-016). Free illustrated presents with no money value, sent in direct
 * chats. The codes are the API's `GiftCode` (contracts/openapi/openapi.yaml); the pictures ship
 * with the app (assets/gifts), so a gift shows without a network.
 */
export const GIFT_CODES = [
  'coffee',
  'postcard',
  'flowers',
  'ice_cream',
  'cake',
  'boarding_pass',
  'snow_globe',
  'coconut',
] as const;

export type GiftCode = (typeof GIFT_CODES)[number];

const IMAGES: Record<GiftCode, ImageSourcePropType> = {
  coffee: require('../../../assets/gifts/coffee.png') as number,
  postcard: require('../../../assets/gifts/postcard.png') as number,
  flowers: require('../../../assets/gifts/flowers.png') as number,
  ice_cream: require('../../../assets/gifts/ice_cream.png') as number,
  cake: require('../../../assets/gifts/cake.png') as number,
  boarding_pass: require('../../../assets/gifts/boarding_pass.png') as number,
  snow_globe: require('../../../assets/gifts/snow_globe.png') as number,
  coconut: require('../../../assets/gifts/coconut.png') as number,
};

/** The box a gift arrives in, until the recipient opens it. */
export const WRAPPED_GIFT: ImageSourcePropType =
  require('../../../assets/gifts/wrapped.png') as number;

export function isGiftCode(value: unknown): value is GiftCode {
  return typeof value === 'string' && (GIFT_CODES as readonly string[]).includes(value);
}

/** A gift's picture; an unknown code (a gift added in a newer app) shows the wrapped box. */
export function giftImage(code: string): ImageSourcePropType {
  return isGiftCode(code) ? IMAGES[code] : WRAPPED_GIFT;
}

export type GiftNameKey = `gifts.${GiftCode | 'unknown'}`;

/** The translation key of a gift's name ("Coffee"); unknown codes read as "Gift". */
export function giftNameKey(code: string): GiftNameKey {
  return isGiftCode(code) ? `gifts.${code}` : 'gifts.unknown';
}

/**
 * Emoji offered in the panel beside the message field: faces and gestures first, then travel.
 * Any emoji can still be typed from the keyboard.
 */
export const PANEL_EMOJI = [
  '😀',
  '😂',
  '🥹',
  '😊',
  '😍',
  '🥰',
  '😘',
  '😎',
  '🤩',
  '🥳',
  '😮',
  '🤔',
  '😴',
  '😢',
  '😅',
  '🙃',
  '👍',
  '👏',
  '🙌',
  '🙏',
  '👋',
  '🤝',
  '💪',
  '✌️',
  '❤️',
  '🧡',
  '💛',
  '💚',
  '💙',
  '💜',
  '✨',
  '🔥',
  '🎉',
  '💯',
  '✈️',
  '🧳',
  '🗺️',
  '📍',
  '🏖️',
  '⛰️',
  '🏕️',
  '🌍',
  '🌅',
  '🌴',
  '📸',
  '🚆',
  '🚗',
  '⛵',
  '☕',
  '🍕',
  '🍜',
  '🍦',
  '🍹',
  '🥐',
  '🌮',
  '🍷',
] as const;
