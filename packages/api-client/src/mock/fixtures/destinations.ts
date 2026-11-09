/**
 * MOCK FIXTURE DATA — development only.
 *
 * Content rules (web 01 §7.1 rule 6, brief §6): general, long-established descriptions only.
 * No prices, opening hours, entry rules, safety advisories or other live information. Cover
 * photos are openly licensed and credited (see ./media.ts); anything without one renders the
 * branded placeholder.
 */
import type {
  Continent,
  DestinationKind,
  LocaleCode,
  PlaceCategory,


} from '@travelbuddy/domain-types';

export type Loc = { en: string } & Partial<Record<LocaleCode, string>>;

export interface DestinationFixture {
  path: string;
  kind: DestinationKind;
  name: Loc;
  country_code: string;
  continent: Continent;
  tagline?: Loc;
  categories?: string[];
  center?: { lat: number; lng: number };
  time_zone?: string;
  featured?: boolean;
  overview?: string;
  highlights?: string[];
  best_time?: string;
  languages?: string[];
  currency?: string;
  faqs?: { question: string; answer: string }[];
}

export interface PlaceFixture {
  destination: string;
  slug: string;
  name: string;
  category: PlaceCategory;
  summary: string;
  location: { lat: number; lng: number };
}

const country = (
  path: string,
  name: Loc,
  country_code: string,
  continent: Continent,
  overview: string,
  extra: Partial<DestinationFixture> = {},
): DestinationFixture => ({ path, kind: 'country', name, country_code, continent, overview, ...extra });

export const DESTINATIONS: DestinationFixture[] = [
  // ---- Countries --------------------------------------------------------------------------
  country('brazil', { en: 'Brazil', es: 'Brasil', 'pt-BR': 'Brasil', fr: 'Brésil', de: 'Brasilien' }, 'BR', 'south_america',
    'South America’s largest country, stretching from Amazon rainforest to Atlantic beaches, with a culture shaped by Indigenous, African and European roots.',
    { currency: 'BRL', languages: ['pt'] }),
  country('japan', { en: 'Japan', es: 'Japón', 'pt-BR': 'Japão', fr: 'Japon', de: 'Japan' }, 'JP', 'asia',
    'An island nation where neon megacities, ancient temples and mountain hot springs sit within a few hours of each other by rail.',
    { currency: 'JPY', languages: ['ja'] }),
  country('portugal', { en: 'Portugal' }, 'PT', 'europe',
    'A compact Atlantic country of hilltop cities, tiled façades, long surf beaches and a famously relaxed pace.',
    { currency: 'EUR', languages: ['pt'] }),
  country('spain', { en: 'Spain', es: 'España', 'pt-BR': 'Espanha', fr: 'Espagne', de: 'Spanien' }, 'ES', 'europe',
    'Distinct regions, languages and cuisines, from Catalan modernism to Andalusian courtyards.',
    { currency: 'EUR', languages: ['es', 'ca', 'eu', 'gl'] }),
  country('france', { en: 'France', es: 'Francia', 'pt-BR': 'França', fr: 'France', de: 'Frankreich' }, 'FR', 'europe',
    'Art, food and landscapes in equal measure, from Parisian boulevards to Alpine villages and Mediterranean coves.',
    { currency: 'EUR', languages: ['fr'] }),
  country('italy', { en: 'Italy', es: 'Italia', 'pt-BR': 'Itália', fr: 'Italie', de: 'Italien' }, 'IT', 'europe',
    'Layer upon layer of history, regional cooking traditions and some of the world’s most celebrated art.',
    { currency: 'EUR', languages: ['it'] }),
  country('mexico', { en: 'Mexico', es: 'México', 'pt-BR': 'México', fr: 'Mexique', de: 'Mexiko' }, 'MX', 'north_america',
    'Pre-Hispanic cities, colonial towns, Caribbean and Pacific coasts, and one of the world’s great food cultures.',
    { currency: 'MXN', languages: ['es'] }),
  country('peru', { en: 'Peru', es: 'Perú', 'pt-BR': 'Peru', fr: 'Pérou', de: 'Peru' }, 'PE', 'south_america',
    'Andean highlands, Amazon lowlands and a desert coast, home to the heartland of the former Inca Empire.',
    { currency: 'PEN', languages: ['es', 'qu', 'ay'] }),
  country('morocco', { en: 'Morocco', es: 'Marruecos', 'pt-BR': 'Marrocos', fr: 'Maroc', de: 'Marokko' }, 'MA', 'africa',
    'Imperial cities, Atlas mountain villages and Saharan dunes at the crossroads of Africa, Europe and the Arab world.',
    { currency: 'MAD', languages: ['ar', 'zgh', 'fr'] }),
  country('south-africa', { en: 'South Africa', es: 'Sudáfrica', 'pt-BR': 'África do Sul', fr: 'Afrique du Sud', de: 'Südafrika' }, 'ZA', 'africa',
    'Dramatic coastlines, wine valleys and wildlife reserves, with twelve official languages.',
    { currency: 'ZAR', languages: ['en', 'af', 'xh', 'zu'] }),
  country('thailand', { en: 'Thailand', es: 'Tailandia', 'pt-BR': 'Tailândia', fr: 'Thaïlande', de: 'Thailand' }, 'TH', 'asia',
    'Gilded temples, island-dotted seas and street food that rewards every detour.',
    { currency: 'THB', languages: ['th'] }),
  country('australia', { en: 'Australia', es: 'Australia', 'pt-BR': 'Austrália', fr: 'Australie', de: 'Australien' }, 'AU', 'oceania',
    'A continent-sized country of coastal cities, red deserts, reefs and rainforests.',
    { currency: 'AUD', languages: ['en'] }),
  country('united-states', { en: 'United States', es: 'Estados Unidos', 'pt-BR': 'Estados Unidos', fr: 'États-Unis', de: 'Vereinigte Staaten' }, 'US', 'north_america',
    'Big cities, national parks and road-trip landscapes across fifty very different states.',
    { currency: 'USD', languages: ['en'] }),
  country('iceland', { en: 'Iceland', es: 'Islandia', 'pt-BR': 'Islândia', fr: 'Islande', de: 'Island' }, 'IS', 'europe',
    'Volcanoes, glaciers, waterfalls and geothermal pools on a North Atlantic island.',
    { currency: 'ISK', languages: ['is'] }),

  // ---- Cities -----------------------------------------------------------------------------
  {
    path: 'brazil/rio-de-janeiro', kind: 'city', country_code: 'BR', continent: 'south_america', featured: true,
    name: { en: 'Rio de Janeiro' },
    tagline: {
      en: 'Granite peaks, golden beaches and samba in the streets.',
      es: 'Picos de granito, playas doradas y samba en las calles.',
      'pt-BR': 'Picos de granito, praias douradas e samba nas ruas.',
      fr: 'Pics de granit, plages dorées et samba dans les rues.',
      de: 'Granitgipfel, goldene Strände und Samba auf den Straßen.',
    },
    categories: ['beaches', 'nature', 'nightlife', 'adventure', 'photography'],
    center: { lat: -22.9068, lng: -43.1729 }, time_zone: 'America/Sao_Paulo', currency: 'BRL', languages: ['pt'],
    overview:
      'Rio de Janeiro wraps around Guanabara Bay between forested mountains and the Atlantic. Its beaches — Copacabana, Ipanema, Leblon — are social spaces as much as places to swim, while Tijuca, one of the largest urban forests in the world, climbs the hills behind the city. Neighbourhoods like Santa Teresa and Lapa add colonial streets, live music and a strong creative scene.',
    highlights: [
      'The view from Sugarloaf Mountain and Corcovado over the bay',
      'Beach culture along Copacabana, Ipanema and Leblon',
      'Hiking and waterfalls in Tijuca National Park',
      'Live samba and street life in Lapa and Santa Teresa',
    ],
    best_time:
      'The drier, milder months generally run from May to October. December to March is hot and humid, and the city is busiest around Carnival.',
    faqs: [
      { question: 'How many days do I need in Rio de Janeiro?', answer: 'Most travellers find four to five days enough to see the main viewpoints, spend time on the beaches and explore a few neighbourhoods at an unhurried pace.' },
      { question: 'What language is spoken in Rio?', answer: 'Portuguese. Learning a few basic phrases goes a long way, especially outside the main tourist areas.' },
      { question: 'Where can I find current entry and safety information?', answer: 'Check your government’s official travel advice and the Brazilian consulate before you go. Travel Buddy does not publish live entry requirements or advisories.' },
    ],
  },
  {
    path: 'japan/tokyo', kind: 'city', country_code: 'JP', continent: 'asia', featured: true,
    name: { en: 'Tokyo', es: 'Tokio', 'pt-BR': 'Tóquio', fr: 'Tokyo', de: 'Tokio' },
    tagline: {
      en: 'Where centuries-old shrines meet the world’s busiest crossings.',
      es: 'Donde santuarios centenarios se cruzan con las intersecciones más concurridas del mundo.',
      'pt-BR': 'Onde santuários centenários encontram os cruzamentos mais movimentados do mundo.',
      fr: 'Là où des sanctuaires séculaires côtoient les carrefours les plus animés du monde.',
      de: 'Wo jahrhundertealte Schreine auf die belebtesten Kreuzungen der Welt treffen.',
    },
    categories: ['culture', 'food', 'architecture', 'nightlife', 'shopping'],
    center: { lat: 35.6762, lng: 139.6503 }, time_zone: 'Asia/Tokyo', currency: 'JPY', languages: ['ja'],
    overview:
      'Tokyo is less a single city than a constellation of neighbourhoods, each with its own character: traditional Asakusa, youthful Harajuku, electric Shibuya and Shinjuku, and calm residential streets in between. An exceptionally efficient rail network makes it easy to explore, and the food scene ranges from tiny counter bars to celebrated fine dining.',
    highlights: [
      'Sensō-ji temple and the old-town streets of Asakusa',
      'The Shibuya scramble crossing and Harajuku’s fashion streets',
      'Meiji Jingu shrine and its forest',
      'Food markets and neighbourhood izakaya',
    ],
    best_time:
      'Spring (late March to April) and autumn (October to November) are popular for mild weather and seasonal colours. Summers are hot and humid.',
    faqs: [
      { question: 'Is Tokyo easy to get around without speaking Japanese?', answer: 'Generally yes. Major rail and subway signage is bilingual, and many visitors navigate comfortably with a map app and a transit card.' },
      { question: 'Which neighbourhood should I stay in?', answer: 'It depends on your style: Shinjuku and Shibuya for nightlife and transport links, Asakusa for a traditional atmosphere, and Ginza or Tokyo Station for central convenience.' },
    ],
  },
  {
    path: 'japan/kyoto', kind: 'city', country_code: 'JP', continent: 'asia',
    name: { en: 'Kyoto', es: 'Kioto', 'pt-BR': 'Quioto', fr: 'Kyoto', de: 'Kyoto' },
    tagline: {
      en: 'Temples, gardens and wooden machiya streets.',
      es: 'Templos, jardines y calles de casas machiya.',
      'pt-BR': 'Templos, jardins e ruas de casas machiya.',
      fr: 'Temples, jardins et ruelles de maisons machiya.',
      de: 'Tempel, Gärten und Gassen mit Machiya-Holzhäusern.',
    },
    categories: ['culture', 'history', 'architecture', 'photography'],
    center: { lat: 35.0116, lng: 135.7681 }, time_zone: 'Asia/Tokyo', currency: 'JPY', languages: ['ja'],
    overview:
      'Japan’s imperial capital for more than a thousand years, Kyoto is home to hundreds of temples and shrines, traditional tea houses and carefully tended gardens. Early mornings and quieter side streets reward visitors who slow down.',
    highlights: ['Fushimi Inari’s thousands of torii gates', 'Gion’s historic streets', 'Zen gardens and tea culture'],
  },
  {
    path: 'portugal/lisbon', kind: 'city', country_code: 'PT', continent: 'europe', featured: true,
    name: { en: 'Lisbon', es: 'Lisboa', 'pt-BR': 'Lisboa', fr: 'Lisbonne', de: 'Lissabon' },
    tagline: {
      en: 'Seven hills, tiled façades and the sound of fado.',
      es: 'Siete colinas, fachadas de azulejos y el sonido del fado.',
      'pt-BR': 'Sete colinas, fachadas de azulejo e o som do fado.',
      fr: 'Sept collines, façades d’azulejos et le son du fado.',
      de: 'Sieben Hügel, Kachelfassaden und der Klang des Fado.',
    },
    categories: ['culture', 'food', 'history', 'photography', 'architecture'],
    center: { lat: 38.7223, lng: -9.1393 }, time_zone: 'Europe/Lisbon', currency: 'EUR', languages: ['pt'],
    overview:
      'Lisbon spills down a series of hills to the wide Tagus estuary. Historic trams rattle through Alfama and Graça, miradouros (viewpoints) open onto terracotta rooftops, and the riverside district of Belém holds monuments from Portugal’s age of exploration.',
    highlights: ['Getting lost in Alfama', 'Sunset from a miradouro', 'Belém’s riverside monuments', 'Pastelarias and petiscos'],
    best_time: 'Spring and early autumn are mild and pleasant. Summer is warm, dry and busy.',
    faqs: [
      { question: 'Is Lisbon walkable?', answer: 'Yes, but it is hilly. Comfortable shoes help, and trams, funiculars and the metro take the edge off the steepest climbs.' },
    ],
  },
  {
    path: 'spain/barcelona', kind: 'city', country_code: 'ES', continent: 'europe', featured: true,
    name: { en: 'Barcelona' },
    tagline: {
      en: 'Gaudí’s city between the mountains and the Mediterranean.',
      es: 'La ciudad de Gaudí entre la montaña y el Mediterráneo.',
      'pt-BR': 'A cidade de Gaudí entre as montanhas e o Mediterrâneo.',
      fr: 'La ville de Gaudí, entre montagnes et Méditerranée.',
      de: 'Gaudís Stadt zwischen Bergen und Mittelmeer.',
    },
    categories: ['architecture', 'beaches', 'food', 'nightlife', 'culture'],
    center: { lat: 41.3874, lng: 2.1686 }, time_zone: 'Europe/Madrid', currency: 'EUR', languages: ['ca', 'es'],
    overview:
      'Barcelona combines a medieval Gothic Quarter, the grid of the Eixample with its modernist masterpieces, and a long city beach. Catalan culture, food markets and late evenings define its rhythm.',
    highlights: ['The Sagrada Família and other works by Gaudí', 'The Gothic Quarter', 'Markets and tapas bars'],
  },
  {
    path: 'france/paris', kind: 'city', country_code: 'FR', continent: 'europe', featured: true,
    name: { en: 'Paris', es: 'París', 'pt-BR': 'Paris', fr: 'Paris', de: 'Paris' },
    tagline: {
      en: 'Museums, cafés and boulevards along the Seine.',
      es: 'Museos, cafés y bulevares a orillas del Sena.',
      'pt-BR': 'Museus, cafés e bulevares às margens do Sena.',
      fr: 'Musées, cafés et boulevards le long de la Seine.',
      de: 'Museen, Cafés und Boulevards an der Seine.',
    },
    categories: ['culture', 'food', 'architecture', 'history', 'shopping'],
    center: { lat: 48.8566, lng: 2.3522 }, time_zone: 'Europe/Paris', currency: 'EUR', languages: ['fr'],
    overview:
      'Paris rewards walking: from the islands in the Seine to Montmartre’s hill, its neighbourhoods each have their own markets, cafés and landmarks. World-class museums sit alongside small galleries and bookshops.',
    highlights: ['The Louvre and Musée d’Orsay', 'A walk along the Seine', 'Montmartre and the Marais'],
  },
  {
    path: 'italy/rome', kind: 'city', country_code: 'IT', continent: 'europe',
    name: { en: 'Rome', es: 'Roma', 'pt-BR': 'Roma', fr: 'Rome', de: 'Rom' },
    tagline: {
      en: 'Three thousand years of history around every corner.',
      es: 'Tres mil años de historia en cada esquina.',
      'pt-BR': 'Três mil anos de história em cada esquina.',
      fr: 'Trois mille ans d’histoire à chaque coin de rue.',
      de: 'Dreitausend Jahre Geschichte an jeder Ecke.',
    },
    categories: ['history', 'culture', 'food', 'architecture'],
    center: { lat: 41.9028, lng: 12.4964 }, time_zone: 'Europe/Rome', currency: 'EUR', languages: ['it'],
    overview:
      'Ancient ruins, Renaissance piazzas and Baroque fountains share the streets of Rome. Trastevere’s lanes and neighbourhood trattorias balance the grand monuments.',
    highlights: ['The Colosseum and Roman Forum', 'Trastevere at dusk', 'Piazzas and fountains of the centro storico'],
  },
  {
    path: 'mexico/mexico-city', kind: 'city', country_code: 'MX', continent: 'north_america', featured: true,
    name: { en: 'Mexico City', es: 'Ciudad de México', 'pt-BR': 'Cidade do México', fr: 'Mexico', de: 'Mexiko-Stadt' },
    tagline: {
      en: 'Murals, markets and some of the world’s best street food.',
      es: 'Murales, mercados y parte de la mejor comida callejera del mundo.',
      'pt-BR': 'Murais, mercados e algumas das melhores comidas de rua do mundo.',
      fr: 'Fresques, marchés et l’une des meilleures cuisines de rue au monde.',
      de: 'Wandbilder, Märkte und einige der besten Straßenküchen der Welt.',
    },
    categories: ['food', 'culture', 'history', 'architecture'],
    center: { lat: 19.4326, lng: -99.1332 }, time_zone: 'America/Mexico_City', currency: 'MXN', languages: ['es'],
    overview:
      'Built on the site of the Aztec capital Tenochtitlan, Mexico City layers pre-Hispanic ruins, colonial churches and modern architecture. Leafy neighbourhoods like Roma and Coyoacán are made for long walks between taquerías and cafés.',
    highlights: ['The historic centre and Zócalo', 'The National Museum of Anthropology', 'Food markets and taquerías'],
  },
  {
    path: 'peru/cusco', kind: 'city', country_code: 'PE', continent: 'south_america',
    name: { en: 'Cusco', es: 'Cusco', 'pt-BR': 'Cusco', fr: 'Cuzco', de: 'Cusco' },
    tagline: {
      en: 'The old Inca capital, high in the Andes.',
      es: 'La antigua capital inca, en lo alto de los Andes.',
      'pt-BR': 'A antiga capital inca, no alto dos Andes.',
      fr: 'L’ancienne capitale inca, perchée dans les Andes.',
      de: 'Die alte Inka-Hauptstadt hoch in den Anden.',
    },
    categories: ['history', 'adventure', 'culture', 'nature'],
    center: { lat: -13.532, lng: -71.9675 }, time_zone: 'America/Lima', currency: 'PEN', languages: ['es', 'qu'],
    overview:
      'Cusco’s colonial buildings stand on Inca stone foundations, and the city is the usual gateway to the Sacred Valley. At roughly 3,400 metres above sea level, many visitors plan a slow first day or two.',
    highlights: ['Inca stonework in the historic centre', 'The Sacred Valley', 'Andean markets and textiles'],
  },
  {
    path: 'morocco/marrakesh', kind: 'city', country_code: 'MA', continent: 'africa',
    name: { en: 'Marrakesh', es: 'Marrakech', 'pt-BR': 'Marrakech', fr: 'Marrakech', de: 'Marrakesch' },
    tagline: {
      en: 'Souks, riads and the rhythm of Jemaa el-Fnaa.',
      es: 'Zocos, riads y el ritmo de Yamaa el Fna.',
      'pt-BR': 'Souks, riads e o ritmo da Jemaa el-Fna.',
      fr: 'Souks, riads et le rythme de Jemaa el-Fna.',
      de: 'Souks, Riads und der Rhythmus des Djemaa el Fna.',
    },
    categories: ['culture', 'food', 'shopping', 'architecture'],
    center: { lat: 31.6295, lng: -7.9811 }, time_zone: 'Africa/Casablanca', currency: 'MAD', languages: ['ar', 'zgh', 'fr'],
    overview:
      'Inside Marrakesh’s ochre walls, a maze of souks leads to quiet riad courtyards, palaces and gardens. The Atlas Mountains are visible on clear days and close enough for a day trip.',
    highlights: ['Jemaa el-Fnaa at dusk', 'The souks of the medina', 'Gardens and palaces'],
  },
  {
    path: 'south-africa/cape-town', kind: 'city', country_code: 'ZA', continent: 'africa', featured: true,
    name: { en: 'Cape Town', es: 'Ciudad del Cabo', 'pt-BR': 'Cidade do Cabo', fr: 'Le Cap', de: 'Kapstadt' },
    tagline: {
      en: 'Table Mountain, two oceans and endless coastline.',
      es: 'La Montaña de la Mesa, dos océanos y costa sin fin.',
      'pt-BR': 'Montanha da Mesa, dois oceanos e um litoral sem fim.',
      fr: 'La montagne de la Table, deux océans et une côte infinie.',
      de: 'Tafelberg, zwei Ozeane und endlose Küste.',
    },
    categories: ['nature', 'adventure', 'beaches', 'food', 'photography'],
    center: { lat: -33.9249, lng: 18.4241 }, time_zone: 'Africa/Johannesburg', currency: 'ZAR', languages: ['en', 'af', 'xh'],
    overview:
      'Cape Town sits beneath the flat-topped Table Mountain, with beaches, vineyards and the Cape Peninsula all within reach. Hiking, coastal drives and a lively food scene make it a favourite for active travellers.',
    highlights: ['Hiking Table Mountain', 'The Cape Peninsula coast', 'Winelands day trips'],
  },
  {
    path: 'thailand/bangkok', kind: 'city', country_code: 'TH', continent: 'asia',
    name: { en: 'Bangkok' },
    tagline: {
      en: 'Golden temples and a city that never stops eating.',
      es: 'Templos dorados y una ciudad que nunca deja de comer.',
      'pt-BR': 'Templos dourados e uma cidade que nunca para de comer.',
      fr: 'Des temples dorés et une ville qui ne cesse jamais de manger.',
      de: 'Goldene Tempel und eine Stadt, die nie aufhört zu essen.',
    },
    categories: ['food', 'culture', 'nightlife', 'shopping'],
    center: { lat: 13.7563, lng: 100.5018 }, time_zone: 'Asia/Bangkok', currency: 'THB', languages: ['th'],
    overview:
      'Bangkok’s riverside temples and grand palace contrast with sky-high rooftops and sprawling markets. Long-tail boats and river ferries are a scenic way to move around the old city.',
    highlights: ['Wat Arun and Wat Pho', 'River ferries on the Chao Phraya', 'Street food in Chinatown'],
  },
  {
    path: 'australia/sydney', kind: 'city', country_code: 'AU', continent: 'oceania',
    name: { en: 'Sydney', es: 'Sídney', 'pt-BR': 'Sydney', fr: 'Sydney', de: 'Sydney' },
    tagline: {
      en: 'Harbour views, coastal walks and surf beaches.',
      es: 'Vistas a la bahía, paseos costeros y playas de surf.',
      'pt-BR': 'Vista para a baía, trilhas costeiras e praias de surfe.',
      fr: 'Vue sur la baie, balades côtières et plages de surf.',
      de: 'Hafenblicke, Küstenwanderungen und Surfstrände.',
    },
    categories: ['beaches', 'nature', 'food', 'architecture'],
    center: { lat: -33.8688, lng: 151.2093 }, time_zone: 'Australia/Sydney', currency: 'AUD', languages: ['en'],
    overview:
      'Sydney is built around one of the world’s great natural harbours. Ferries link waterfront neighbourhoods, and the coastline south of the city is lined with ocean pools and walking trails.',
    highlights: ['The harbour by ferry', 'The Bondi to Coogee coastal walk', 'The Sydney Opera House'],
  },
  {
    path: 'united-states/new-york-city', kind: 'city', country_code: 'US', continent: 'north_america',
    name: { en: 'New York City', es: 'Nueva York', 'pt-BR': 'Nova York', fr: 'New York', de: 'New York City' },
    tagline: {
      en: 'Five boroughs, countless neighbourhoods, one skyline.',
      es: 'Cinco distritos, incontables barrios y un solo horizonte.',
      'pt-BR': 'Cinco distritos, incontáveis bairros e um único horizonte.',
      fr: 'Cinq arrondissements, d’innombrables quartiers, une seule skyline.',
      de: 'Fünf Boroughs, unzählige Viertel, eine Skyline.',
    },
    categories: ['culture', 'food', 'architecture', 'shopping', 'nightlife'],
    center: { lat: 40.7128, lng: -74.006 }, time_zone: 'America/New_York', currency: 'USD', languages: ['en'],
    overview:
      'New York City’s energy comes from its neighbourhoods as much as its landmarks. Museums, parks, food from every corner of the world and an extensive subway make it endlessly explorable.',
    highlights: ['Central Park', 'Museums along Fifth Avenue', 'Neighbourhood food in Queens and Brooklyn'],
  },
  {
    path: 'iceland/reykjavik', kind: 'city', country_code: 'IS', continent: 'europe',
    name: { en: 'Reykjavík' },
    tagline: {
      en: 'A colourful capital at the edge of the Arctic.',
      es: 'Una capital colorida al borde del Ártico.',
      'pt-BR': 'Uma capital colorida à beira do Ártico.',
      fr: 'Une capitale colorée aux portes de l’Arctique.',
      de: 'Eine bunte Hauptstadt am Rand der Arktis.',
    },
    categories: ['nature', 'adventure', 'photography', 'wellness'],
    center: { lat: 64.1466, lng: -21.9426 }, time_zone: 'Atlantic/Reykjavik', currency: 'ISK', languages: ['is'],
    overview:
      'The world’s northernmost capital is small, walkable and creative, and the starting point for exploring Iceland’s waterfalls, geothermal areas and coastline.',
    highlights: ['Hallgrímskirkja and the old harbour', 'Geothermal pools', 'Day trips to waterfalls and lava fields'],
  },

  // ---- Neighbourhoods (used for feed filtering; no dedicated pages yet) --------------------
  { path: 'brazil/rio-de-janeiro/copacabana', kind: 'neighborhood', country_code: 'BR', continent: 'south_america', name: { en: 'Copacabana' }, center: { lat: -22.9711, lng: -43.1822 }, time_zone: 'America/Sao_Paulo', categories: ['beaches'] },
  { path: 'brazil/rio-de-janeiro/ipanema', kind: 'neighborhood', country_code: 'BR', continent: 'south_america', name: { en: 'Ipanema' }, center: { lat: -22.9838, lng: -43.2096 }, time_zone: 'America/Sao_Paulo', categories: ['beaches'] },
  { path: 'brazil/rio-de-janeiro/santa-teresa', kind: 'neighborhood', country_code: 'BR', continent: 'south_america', name: { en: 'Santa Teresa' }, center: { lat: -22.9216, lng: -43.1886 }, time_zone: 'America/Sao_Paulo', categories: ['culture'] },
  { path: 'japan/tokyo/asakusa', kind: 'neighborhood', country_code: 'JP', continent: 'asia', name: { en: 'Asakusa' }, center: { lat: 35.7148, lng: 139.7967 }, time_zone: 'Asia/Tokyo', categories: ['culture'] },
  { path: 'japan/tokyo/shibuya', kind: 'neighborhood', country_code: 'JP', continent: 'asia', name: { en: 'Shibuya' }, center: { lat: 35.6595, lng: 139.7005 }, time_zone: 'Asia/Tokyo', categories: ['nightlife'] },
  { path: 'portugal/lisbon/alfama', kind: 'neighborhood', country_code: 'PT', continent: 'europe', name: { en: 'Alfama' }, center: { lat: 38.7114, lng: -9.13 }, time_zone: 'Europe/Lisbon', categories: ['culture'] },
];

export const PLACES: PlaceFixture[] = [
  { destination: 'brazil/rio-de-janeiro', slug: 'christ-the-redeemer', name: 'Christ the Redeemer', category: 'attraction', summary: 'The Art Deco statue on Corcovado mountain overlooking the city.', location: { lat: -22.9519, lng: -43.2105 } },
  { destination: 'brazil/rio-de-janeiro', slug: 'sugarloaf-mountain', name: 'Sugarloaf Mountain', category: 'viewpoint', summary: 'A granite peak at the mouth of Guanabara Bay, reached by cable car.', location: { lat: -22.9486, lng: -43.1566 } },
  { destination: 'brazil/rio-de-janeiro/copacabana', slug: 'copacabana-beach', name: 'Copacabana Beach', category: 'beach', summary: 'A four-kilometre curve of sand with its famous wave-patterned promenade.', location: { lat: -22.9711, lng: -43.1822 } },
  { destination: 'brazil/rio-de-janeiro/ipanema', slug: 'ipanema-beach', name: 'Ipanema Beach', category: 'beach', summary: 'A beach known for its sunsets from Arpoador rock and its lively posts (postos).', location: { lat: -22.9868, lng: -43.205 } },
  { destination: 'brazil/rio-de-janeiro', slug: 'tijuca-national-park', name: 'Tijuca National Park', category: 'park', summary: 'A vast urban rainforest with trails, waterfalls and viewpoints.', location: { lat: -22.953, lng: -43.285 } },
  { destination: 'brazil/rio-de-janeiro/santa-teresa', slug: 'selaron-steps', name: 'Selarón Steps', category: 'attraction', summary: 'A staircase covered in tiles collected from around the world by artist Jorge Selarón.', location: { lat: -22.9154, lng: -43.1791 } },
  { destination: 'brazil/rio-de-janeiro', slug: 'museum-of-tomorrow', name: 'Museum of Tomorrow', category: 'museum', summary: 'A science museum in a striking building on the revitalised port waterfront.', location: { lat: -22.894, lng: -43.1797 } },
  { destination: 'brazil/rio-de-janeiro', slug: 'botanical-garden', name: 'Rio de Janeiro Botanical Garden', category: 'park', summary: 'Historic gardens famous for their avenue of imperial palms.', location: { lat: -22.9674, lng: -43.2245 } },
  { destination: 'japan/tokyo/asakusa', slug: 'senso-ji', name: 'Sensō-ji', category: 'attraction', summary: 'Tokyo’s oldest temple, approached through the Nakamise shopping street.', location: { lat: 35.7148, lng: 139.7967 } },
  { destination: 'japan/tokyo', slug: 'meiji-jingu', name: 'Meiji Jingu', category: 'attraction', summary: 'A Shinto shrine set in a forest of around 100,000 trees.', location: { lat: 35.6764, lng: 139.6993 } },
  { destination: 'japan/tokyo/shibuya', slug: 'shibuya-crossing', name: 'Shibuya Crossing', category: 'viewpoint', summary: 'The famous scramble crossing outside Shibuya Station.', location: { lat: 35.6595, lng: 139.7005 } },
  { destination: 'japan/tokyo', slug: 'tsukiji-outer-market', name: 'Tsukiji Outer Market', category: 'market', summary: 'Lanes of food stalls and shops selling seafood, knives and snacks.', location: { lat: 35.6654, lng: 139.7707 } },
  { destination: 'japan/kyoto', slug: 'fushimi-inari-taisha', name: 'Fushimi Inari Taisha', category: 'attraction', summary: 'A shrine famous for trails lined with thousands of vermilion torii gates.', location: { lat: 34.9671, lng: 135.7727 } },
  { destination: 'portugal/lisbon', slug: 'belem-tower', name: 'Belém Tower', category: 'attraction', summary: 'A 16th-century fortified tower on the Tagus riverbank.', location: { lat: 38.6916, lng: -9.216 } },
  { destination: 'portugal/lisbon/alfama', slug: 'miradouro-de-santa-luzia', name: 'Miradouro de Santa Luzia', category: 'viewpoint', summary: 'A tiled terrace with views over Alfama’s rooftops to the river.', location: { lat: 38.7118, lng: -9.1302 } },
  { destination: 'spain/barcelona', slug: 'sagrada-familia', name: 'Sagrada Família', category: 'attraction', summary: 'Antoni Gaudí’s monumental basilica, under construction since 1882.', location: { lat: 41.4036, lng: 2.1744 } },
  { destination: 'france/paris', slug: 'louvre', name: 'Louvre Museum', category: 'museum', summary: 'One of the world’s largest art museums, in a former royal palace.', location: { lat: 48.8606, lng: 2.3376 } },
  { destination: 'italy/rome', slug: 'colosseum', name: 'Colosseum', category: 'attraction', summary: 'The great amphitheatre of ancient Rome.', location: { lat: 41.8902, lng: 12.4922 } },
  { destination: 'mexico/mexico-city', slug: 'national-museum-of-anthropology', name: 'National Museum of Anthropology', category: 'museum', summary: 'Major collections of pre-Hispanic art and archaeology, including the Aztec Sun Stone.', location: { lat: 19.426, lng: -99.1863 } },
  { destination: 'peru/cusco', slug: 'sacsayhuaman', name: 'Sacsayhuamán', category: 'attraction', summary: 'Inca ceremonial complex with enormous fitted stone walls above the city.', location: { lat: -13.5094, lng: -71.9817 } },
  { destination: 'morocco/marrakesh', slug: 'jemaa-el-fnaa', name: 'Jemaa el-Fnaa', category: 'attraction', summary: 'The main square of the medina, busy with food stalls and performers in the evening.', location: { lat: 31.6258, lng: -7.9891 } },
  { destination: 'south-africa/cape-town', slug: 'table-mountain', name: 'Table Mountain', category: 'trail', summary: 'The flat-topped mountain above the city, reached on foot or by cableway.', location: { lat: -33.9628, lng: 18.4098 } },
  { destination: 'thailand/bangkok', slug: 'wat-arun', name: 'Wat Arun', category: 'attraction', summary: 'The Temple of Dawn, with its porcelain-studded spire on the Chao Phraya.', location: { lat: 13.7437, lng: 100.4889 } },
  { destination: 'australia/sydney', slug: 'sydney-opera-house', name: 'Sydney Opera House', category: 'attraction', summary: 'The sail-roofed performing arts centre on Bennelong Point.', location: { lat: -33.8568, lng: 151.2153 } },
  { destination: 'united-states/new-york-city', slug: 'central-park', name: 'Central Park', category: 'park', summary: 'Manhattan’s 843-acre park of lawns, lakes and woodland.', location: { lat: 40.7829, lng: -73.9654 } },
  { destination: 'iceland/reykjavik', slug: 'hallgrimskirkja', name: 'Hallgrímskirkja', category: 'attraction', summary: 'The city’s landmark church, inspired by basalt columns.', location: { lat: 64.1417, lng: -21.9266 } },
];
