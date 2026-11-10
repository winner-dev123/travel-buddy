"""Travel styles and suggested interests with localized labels (PROF-004, I18N-003).

Profiles store interests as free-form codes (max 40 characters); this catalog is the curated set
clients offer as chips, grouped for display. Codes are stable, labels follow the UI locale.
"""

from __future__ import annotations

from typing import Final

Labels = dict[str, str]  # locale → label

TRAVEL_STYLES: Final[dict[str, Labels]] = {
    "adventure": {
        "en": "Adventure",
        "es": "Aventura",
        "pt-BR": "Aventura",
        "fr": "Aventure",
        "de": "Abenteuer",
    },
    "backpacking": {
        "en": "Backpacking",
        "es": "Mochilero",
        "pt-BR": "Mochilão",
        "fr": "Sac à dos",
        "de": "Backpacking",
    },
    "luxury": {"en": "Luxury", "es": "Lujo", "pt-BR": "Luxo", "fr": "Luxe", "de": "Luxus"},
    "food": {
        "en": "Food",
        "es": "Gastronomía",
        "pt-BR": "Gastronomia",
        "fr": "Gastronomie",
        "de": "Kulinarik",
    },
    "culture": {
        "en": "Culture",
        "es": "Cultura",
        "pt-BR": "Cultura",
        "fr": "Culture",
        "de": "Kultur",
    },
    "photography": {
        "en": "Photography",
        "es": "Fotografía",
        "pt-BR": "Fotografia",
        "fr": "Photographie",
        "de": "Fotografie",
    },
    "digital_nomad": {
        "en": "Digital nomad",
        "es": "Nómada digital",
        "pt-BR": "Nômade digital",
        "fr": "Nomade numérique",
        "de": "Digitaler Nomade",
    },
    "nature": {
        "en": "Nature",
        "es": "Naturaleza",
        "pt-BR": "Natureza",
        "fr": "Nature",
        "de": "Natur",
    },
    "family": {
        "en": "Family",
        "es": "En familia",
        "pt-BR": "Em família",
        "fr": "En famille",
        "de": "Familie",
    },
}

# (code, group, labels). The first ten match the mobile onboarding chips.
INTERESTS: Final[tuple[tuple[str, str, Labels], ...]] = (
    (
        "food",
        "food",
        {
            "en": "Food",
            "es": "Gastronomía",
            "pt-BR": "Gastronomia",
            "fr": "Gastronomie",
            "de": "Essen",
        },
    ),
    (
        "culture",
        "culture",
        {"en": "Culture", "es": "Cultura", "pt-BR": "Cultura", "fr": "Culture", "de": "Kultur"},
    ),
    (
        "history",
        "culture",
        {
            "en": "History",
            "es": "Historia",
            "pt-BR": "História",
            "fr": "Histoire",
            "de": "Geschichte",
        },
    ),
    (
        "nature",
        "outdoors",
        {"en": "Nature", "es": "Naturaleza", "pt-BR": "Natureza", "fr": "Nature", "de": "Natur"},
    ),
    (
        "hiking",
        "outdoors",
        {
            "en": "Hiking",
            "es": "Senderismo",
            "pt-BR": "Trilhas",
            "fr": "Randonnée",
            "de": "Wandern",
        },
    ),
    (
        "beaches",
        "outdoors",
        {"en": "Beaches", "es": "Playas", "pt-BR": "Praias", "fr": "Plages", "de": "Strände"},
    ),
    (
        "nightlife",
        "city",
        {
            "en": "Nightlife",
            "es": "Vida nocturna",
            "pt-BR": "Vida noturna",
            "fr": "Vie nocturne",
            "de": "Nachtleben",
        },
    ),
    ("art", "culture", {"en": "Art", "es": "Arte", "pt-BR": "Arte", "fr": "Art", "de": "Kunst"}),
    (
        "photography",
        "city",
        {
            "en": "Photography",
            "es": "Fotografía",
            "pt-BR": "Fotografia",
            "fr": "Photographie",
            "de": "Fotografie",
        },
    ),
    (
        "budget",
        "style",
        {
            "en": "Budget travel",
            "es": "Viajar con poco",
            "pt-BR": "Viagem econômica",
            "fr": "Petit budget",
            "de": "Low Budget",
        },
    ),
    (
        "street_food",
        "food",
        {
            "en": "Street food",
            "es": "Comida callejera",
            "pt-BR": "Comida de rua",
            "fr": "Cuisine de rue",
            "de": "Streetfood",
        },
    ),
    (
        "coffee",
        "food",
        {"en": "Coffee", "es": "Café", "pt-BR": "Café", "fr": "Café", "de": "Kaffee"},
    ),
    (
        "wine",
        "food",
        {"en": "Wine", "es": "Vino", "pt-BR": "Vinho", "fr": "Vin", "de": "Wein"},
    ),
    (
        "museums",
        "culture",
        {"en": "Museums", "es": "Museos", "pt-BR": "Museus", "fr": "Musées", "de": "Museen"},
    ),
    (
        "architecture",
        "culture",
        {
            "en": "Architecture",
            "es": "Arquitectura",
            "pt-BR": "Arquitetura",
            "fr": "Architecture",
            "de": "Architektur",
        },
    ),
    (
        "music",
        "culture",
        {
            "en": "Live music",
            "es": "Música en vivo",
            "pt-BR": "Música ao vivo",
            "fr": "Concerts",
            "de": "Livemusik",
        },
    ),
    (
        "markets",
        "city",
        {"en": "Markets", "es": "Mercados", "pt-BR": "Mercados", "fr": "Marchés", "de": "Märkte"},
    ),
    (
        "mountains",
        "outdoors",
        {"en": "Mountains", "es": "Montaña", "pt-BR": "Montanhas", "fr": "Montagne", "de": "Berge"},
    ),
    (
        "wildlife",
        "outdoors",
        {
            "en": "Wildlife",
            "es": "Fauna",
            "pt-BR": "Vida selvagem",
            "fr": "Faune",
            "de": "Tierbeobachtung",
        },
    ),
    (
        "surfing",
        "outdoors",
        {"en": "Surfing", "es": "Surf", "pt-BR": "Surfe", "fr": "Surf", "de": "Surfen"},
    ),
    (
        "cycling",
        "outdoors",
        {"en": "Cycling", "es": "Ciclismo", "pt-BR": "Ciclismo", "fr": "Vélo", "de": "Radfahren"},
    ),
    (
        "road_trips",
        "style",
        {
            "en": "Road trips",
            "es": "Viajes por carretera",
            "pt-BR": "Viagens de carro",
            "fr": "Road trips",
            "de": "Roadtrips",
        },
    ),
    (
        "slow_travel",
        "style",
        {
            "en": "Slow travel",
            "es": "Viajar sin prisa",
            "pt-BR": "Viagem sem pressa",
            "fr": "Voyage lent",
            "de": "Langsam reisen",
        },
    ),
    (
        "sustainable_travel",
        "style",
        {
            "en": "Sustainable travel",
            "es": "Viaje sostenible",
            "pt-BR": "Viagem sustentável",
            "fr": "Voyage durable",
            "de": "Nachhaltig reisen",
        },
    ),
)


def catalog(locale: str) -> dict[str, list[dict[str, str]]]:
    """Contract ``TravelInterestCatalog`` in ``locale`` (English when a label is missing)."""
    return {
        "travel_styles": [
            {"code": code, "label": labels.get(locale, labels["en"])}
            for code, labels in TRAVEL_STYLES.items()
        ],
        "interests": [
            {"code": code, "label": labels.get(locale, labels["en"]), "group": group}
            for code, group, labels in INTERESTS
        ],
    }
