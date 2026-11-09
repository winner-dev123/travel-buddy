/**
 * MOCK FIXTURE DATA — development only. Fictional personas and posts.
 */
import type {
  PostKind,
  TravelStyle,
  LocaleCode,
  PlatformRole,
  PostVisibility,
  ReactionType,

} from '@travelbuddy/domain-types';

export interface PersonaFixture {
  handle: string;
  display_name: string;
  email: string;
  bio: string;
  home_country_code: string;
  languages: string[];
  travel_styles: TravelStyle[];
  preferred_language: LocaleCode;
  browse?: string;
  premium?: boolean;
  roles?: PlatformRole[];
  /** Opted into search-engine indexing of public stories (PROF-008). */
  indexing?: boolean;
  /** Short description shown on the development persona picker. */
  persona_note: string;
}

export const PERSONAS: PersonaFixture[] = [
  {
    handle: 'amelia', indexing: true, display_name: 'Amelia Clarke', email: 'amelia@example.com',
    bio: 'London-based photographer chasing golden hour on every continent.',
    home_country_code: 'GB', languages: ['en', 'fr'], travel_styles: ['photography', 'food', 'nature'],
    preferred_language: 'en', browse: 'brazil/rio-de-janeiro',
    persona_note: 'UK traveller in Rio · free plan',
  },
  {
    handle: 'lucas', indexing: true, display_name: 'Lucas Almeida', email: 'lucas@example.com',
    bio: 'Carioca trail runner. Ask me about waterfalls.',
    home_country_code: 'BR', languages: ['pt', 'en', 'es'], travel_styles: ['adventure', 'nature'],
    preferred_language: 'pt-BR', browse: 'brazil/rio-de-janeiro', premium: true,
    persona_note: 'Rio local · premium plan',
  },
  {
    handle: 'yuki', indexing: true, display_name: 'Yuki Tanaka', email: 'yuki@example.com',
    bio: 'Temples, ramen and quiet mornings.',
    home_country_code: 'JP', languages: ['ja', 'en'], travel_styles: ['culture', 'food'],
    preferred_language: 'en', browse: 'japan/tokyo',
    persona_note: 'Tokyo local · free plan',
  },
  {
    handle: 'sofia', indexing: true, display_name: 'Sofia Rossi', email: 'sofia@example.com',
    bio: 'Historian on sabbatical, one old town at a time.',
    home_country_code: 'IT', languages: ['it', 'en', 'es'], travel_styles: ['culture', 'food', 'photography'],
    preferred_language: 'en', browse: 'portugal/lisbon',
    persona_note: 'Italian traveller in Lisbon · free plan',
  },
  {
    handle: 'noah', display_name: 'Noah Fischer', email: 'noah@example.com',
    bio: 'Mountains first, cities second.',
    home_country_code: 'DE', languages: ['de', 'en'], travel_styles: ['adventure', 'nature', 'photography'],
    preferred_language: 'de',
    persona_note: 'German hiker · no browse destination',
  },
  {
    handle: 'mia', indexing: true, display_name: 'Mia Laurent', email: 'mia@example.com',
    bio: 'Food writer. Will travel for pastry.',
    home_country_code: 'FR', languages: ['fr', 'en'], travel_styles: ['food', 'culture'],
    preferred_language: 'fr', browse: 'france/paris',
    persona_note: 'French food writer · free plan',
  },
  {
    handle: 'priya.mod', display_name: 'Priya Shah', email: 'priya@example.com',
    bio: 'Trust & safety team.',
    home_country_code: 'GB', languages: ['en'], travel_styles: ['culture'],
    preferred_language: 'en', roles: ['moderator'],
    persona_note: 'Platform moderator · admin area access',
  },
];

export const FOLLOWS: [follower: string, followee: string][] = [
  ['amelia', 'lucas'],
  ['amelia', 'yuki'],
  ['lucas', 'amelia'],
  ['sofia', 'mia'],
  ['mia', 'sofia'],
  ['noah', 'mia'],
  ['yuki', 'noah'],
];

export interface PostFixture {
  key: string;
  author: string;
  destination: string;
  place?: string;
  caption: string;
  language: string;
  tags: string[];
  visibility: PostVisibility;
  hours_ago: number;
  reactions: Partial<Record<ReactionType, number>>;
  kind?: PostKind;
  comments?: { author: string; body: string; hours_ago: number }[];
}

export const POSTS: PostFixture[] = [
  { key: 'sugarloaf-golden-hour', author: 'lucas', destination: 'brazil/rio-de-janeiro', place: 'sugarloaf-mountain',
    caption: 'Caught the last light over Guanabara Bay from the top of Sugarloaf. Go up before sunset and stay for the city lights coming on — it feels like two different cities in one evening.',
    language: 'en', tags: ['photography', 'nature'], visibility: 'public', hours_ago: 3, reactions: { like: 124, love: 41, wow: 9 },
    comments: [
      { author: 'amelia', body: 'This is exactly the shot I’m hoping for this week!', hours_ago: 2 },
      { author: 'noah', body: 'Did you take the cable car both ways?', hours_ago: 1 },
    ] },
  { key: 'selaron-tiles', author: 'amelia', destination: 'brazil/rio-de-janeiro/santa-teresa', place: 'selaron-steps',
    caption: 'Every tile on the Selarón Steps seems to come from a different country. After twenty minutes of searching I found one from London. Go early if you want photos without crowds.',
    language: 'en', tags: ['culture', 'photography'], visibility: 'public', hours_ago: 6, reactions: { like: 88, love: 30 },
    comments: [{ author: 'lucas', body: 'Welcome to Santa Teresa! Try the bonde (tram) too.', hours_ago: 5 }] },
  { key: 'tijuca-trail-run', author: 'lucas', destination: 'brazil/rio-de-janeiro', place: 'tijuca-national-park',
    caption: 'Trail run through Tijuca Forest this morning: waterfalls, capuchin monkeys and almost nobody else on the path. Hard to believe this is inside the city.',
    language: 'en', tags: ['adventure', 'nature'], visibility: 'public', hours_ago: 20, reactions: { like: 64, wow: 12 } },
  { key: 'arpoador-applause', author: 'amelia', destination: 'brazil/rio-de-janeiro/ipanema', place: 'ipanema-beach',
    caption: 'Applauding the sunset from Arpoador rock is a real thing and I am completely here for it.',
    language: 'en', tags: ['beaches', 'photography'], visibility: 'public', hours_ago: 28, reactions: { like: 201, love: 77 } },
  { key: 'santa-teresa-feira', author: 'lucas', destination: 'brazil/rio-de-janeiro/santa-teresa',
    caption: 'Feira de domingo em Santa Teresa: música ao vivo, artesanato e o melhor pastel da semana.',
    language: 'pt', tags: ['food', 'culture'], visibility: 'public', hours_ago: 48, reactions: { like: 45, love: 18 } },
  { key: 'museum-of-tomorrow', author: 'sofia', destination: 'brazil/rio-de-janeiro', place: 'museum-of-tomorrow',
    caption: 'The Museum of Tomorrow’s architecture alone is worth the walk along the port waterfront. Pair it with the street art on the Boulevard Olímpico.',
    language: 'en', tags: ['architecture', 'culture'], visibility: 'public', hours_ago: 72, reactions: { like: 37 } },
  { key: 'ilha-grande-plan', author: 'lucas', destination: 'brazil/rio-de-janeiro',
    caption: 'Planning a weekend on Ilha Grande next month with a few friends. Followers: reply if you want to join the planning chat.',
    language: 'en', tags: ['adventure', 'beaches'], visibility: 'followers', hours_ago: 26, reactions: { like: 12 } },
  { key: 'amelia-private-note', author: 'amelia', destination: 'brazil/rio-de-janeiro',
    caption: 'Note to self: pack reef-safe sunscreen and a waterproof phone pouch for the boat day.',
    language: 'en', tags: ['beaches'], visibility: 'private', hours_ago: 30, reactions: {} },
  { key: 'redeemer-clouds', author: 'mia', destination: 'brazil/rio-de-janeiro', place: 'christ-the-redeemer',
    caption: 'Clouds rolled in at Christ the Redeemer and then parted for exactly two minutes. Patience pays.',
    language: 'en', tags: ['photography'], visibility: 'public', hours_ago: 120, reactions: { like: 150, wow: 22 } },

  { key: 'sensoji-morning', author: 'yuki', destination: 'japan/tokyo/asakusa', place: 'senso-ji',
    caption: '朝の浅草寺は静かで、とても美しいです。人が少ない時間に行くのがおすすめです。',
    language: 'ja', tags: ['culture', 'photography'], visibility: 'public', hours_ago: 5, reactions: { like: 96, love: 33 },
    comments: [{ author: 'amelia', body: 'Adding this to my Tokyo list!', hours_ago: 4 }] },
  { key: 'tsukiji-breakfast', author: 'yuki', destination: 'japan/tokyo', place: 'tsukiji-outer-market',
    caption: 'Tamagoyaki on a stick at the Tsukiji outer market. Breakfast of champions.',
    language: 'en', tags: ['food'], visibility: 'public', hours_ago: 24, reactions: { like: 71, love: 15 } },
  { key: 'shibuya-from-above', author: 'noah', destination: 'japan/tokyo/shibuya', place: 'shibuya-crossing',
    caption: 'Watched the Shibuya scramble from above for twenty minutes. Strangely hypnotic.',
    language: 'en', tags: ['photography', 'nightlife'], visibility: 'public', hours_ago: 50, reactions: { like: 58, wow: 20 } },
  { key: 'meiji-forest', author: 'mia', destination: 'japan/tokyo', place: 'meiji-jingu',
    caption: 'Meiji Jingu feels like a forest that forgot it is in the middle of a megacity.',
    language: 'en', tags: ['culture', 'nature'], visibility: 'public', hours_ago: 96, reactions: { like: 44 } },
  { key: 'fushimi-gates', author: 'yuki', destination: 'japan/kyoto', place: 'fushimi-inari-taisha',
    caption: 'Climb past the first crowd of gates at Fushimi Inari and the mountain gets quiet fast. The upper shrines are worth the stairs.',
    language: 'en', tags: ['culture', 'adventure'], visibility: 'public', hours_ago: 70, reactions: { like: 112, love: 40 } },

  { key: 'alfama-fado', author: 'sofia', destination: 'portugal/lisbon/alfama',
    caption: 'Got lost in Alfama on purpose. Followed the sound of fado down three staircases and found a tiny courtyard where the whole street seemed to be listening.',
    language: 'en', tags: ['culture'], visibility: 'public', hours_ago: 8, reactions: { like: 83, love: 29 } },
  { key: 'belem-pasteis', author: 'mia', destination: 'portugal/lisbon', place: 'belem-tower',
    caption: 'Pastéis de nata still warm, eaten on a bench by the river near Belém Tower. No notes.',
    language: 'en', tags: ['food'], visibility: 'public', hours_ago: 22, reactions: { like: 140, love: 52 } },
  { key: 'lisbon-walk-28', author: 'amelia', destination: 'portugal/lisbon', place: 'miradouro-de-santa-luzia',
    caption: 'Tram 28 is charming, but walking the same route uphill rewards you with far more viewpoints. Santa Luzia was my favourite.',
    language: 'en', tags: ['photography', 'culture'], visibility: 'public', hours_ago: 144, reactions: { like: 61 } },

  { key: 'sagrada-light', author: 'noah', destination: 'spain/barcelona', place: 'sagrada-familia',
    caption: 'Inside the Sagrada Família the light through the stained glass shifts from blue to orange as the day goes on. Go in the late afternoon.',
    language: 'en', tags: ['architecture'], visibility: 'public', hours_ago: 46, reactions: { like: 99, wow: 31 } },
  { key: 'louvre-mercredi', author: 'mia', destination: 'france/paris', place: 'louvre',
    caption: 'Le Louvre en soirée : moins de monde, plus de magie.',
    language: 'fr', tags: ['culture'], visibility: 'public', hours_ago: 12, reactions: { like: 77, love: 19 } },
  { key: 'colosseo-alba', author: 'sofia', destination: 'italy/rome', place: 'colosseum',
    caption: 'Colosseo all’alba, prima della folla. Vale la sveglia presto.',
    language: 'it', tags: ['history', 'photography'], visibility: 'public', hours_ago: 30, reactions: { like: 90, love: 25 } },
  { key: 'cdmx-tacos', author: 'lucas', destination: 'mexico/mexico-city',
    caption: 'Tacos al pastor y murales en el centro histórico. La Ciudad de México nunca decepciona.',
    language: 'es', tags: ['food', 'culture'], visibility: 'public', hours_ago: 98, reactions: { like: 66, love: 21 } },
  { key: 'cusco-acclimatize', author: 'noah', destination: 'peru/cusco', place: 'sacsayhuaman',
    caption: 'Two slow days in Cusco before the trek. Short walks up to Sacsayhuamán, lots of water and early nights.',
    language: 'en', tags: ['adventure', 'history'], visibility: 'public', hours_ago: 118, reactions: { like: 48 } },
  { key: 'jemaa-dusk', author: 'mia', destination: 'morocco/marrakesh', place: 'jemaa-el-fnaa',
    caption: 'Jemaa el-Fnaa at dusk: smoke from the grills, drums, storytellers and orange-juice stalls in every direction.',
    language: 'en', tags: ['food', 'culture'], visibility: 'public', hours_ago: 75, reactions: { like: 81, wow: 14 } },
  { key: 'table-mountain-hike', author: 'noah', destination: 'south-africa/cape-town', place: 'table-mountain',
    caption: 'Hiked up Platteklip Gorge. Steep and relentless, but the view over the city and the Atlantic is unreal.',
    language: 'en', tags: ['adventure', 'nature'], visibility: 'public', hours_ago: 170, reactions: { like: 104, wow: 26 } },
  { key: 'wat-arun-night', author: 'yuki', destination: 'thailand/bangkok', place: 'wat-arun',
    caption: 'Wat Arun glowing from across the Chao Phraya after dark.',
    language: 'en', tags: ['culture', 'photography'], visibility: 'public', hours_ago: 52, reactions: { like: 73, love: 20 } },
  { key: 'bondi-coogee', author: 'amelia', destination: 'australia/sydney', place: 'sydney-opera-house',
    caption: 'Bondi to Coogee coastal walk in the morning, ferry past the Opera House in the evening. A perfect Sydney day.',
    language: 'en', tags: ['beaches', 'nature'], visibility: 'public', hours_ago: 216, reactions: { like: 57 } },
  { key: 'central-park-autumn', author: 'sofia', destination: 'united-states/new-york-city', place: 'central-park',
    caption: 'Autumn in Central Park is everything the films promised.',
    language: 'en', tags: ['nature', 'photography'], visibility: 'public', hours_ago: 26, reactions: { like: 132, love: 47 } },
  { key: 'reykjavik-aurora', author: 'noah', destination: 'iceland/reykjavik', place: 'hallgrimskirkja',
    caption: 'The aurora forecast looked weak, but we drove out of the city anyway and got a faint green arc over the lava fields. Worth the cold.',
    language: 'en', tags: ['nature', 'photography'], visibility: 'public', hours_ago: 6, reactions: { like: 118, wow: 44 } },
];
