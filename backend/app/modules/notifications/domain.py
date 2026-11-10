"""Localized notification text (pure). Rendered at read time in the reader's locale, so stored
rows hold only render data and a later locale change applies to old notifications too."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Final

from app.core.i18n import DEFAULT_LOCALE

Text = Mapping[str, str]  # locale → text

SOMEONE: Final[Text] = {
    "en": "Someone",
    "es": "Alguien",
    "pt-BR": "Alguém",
    "fr": "Quelqu'un",
    "de": "Jemand",
}

_GUIDELINES: Final[Text] = {
    "en": "Community guidelines",
    "es": "Normas de la comunidad",
    "pt-BR": "Diretrizes da comunidade",
    "fr": "Règles de la communauté",
    "de": "Community-Richtlinien",
}

# type → (title, body); bodies may use {actor}.
_TEMPLATES: Final[dict[str, tuple[Text, Text]]] = {
    "follow_request": (
        {
            "en": "New follow request",
            "es": "Nueva solicitud para seguirte",
            "pt-BR": "Nova solicitação para seguir",
            "fr": "Nouvelle demande d'abonnement",
            "de": "Neue Folgeanfrage",
        },
        {
            "en": "{actor} wants to follow you.",
            "es": "{actor} quiere seguirte.",
            "pt-BR": "{actor} quer seguir você.",
            "fr": "{actor} souhaite vous suivre.",
            "de": "{actor} möchte dir folgen.",
        },
    ),
    "new_follower": (
        {
            "en": "New follower",
            "es": "Nuevo seguidor",
            "pt-BR": "Novo seguidor",
            "fr": "Nouvel abonné",
            "de": "Neuer Follower",
        },
        {
            "en": "{actor} started following you.",
            "es": "{actor} empezó a seguirte.",
            "pt-BR": "{actor} começou a seguir você.",
            "fr": "{actor} a commencé à vous suivre.",
            "de": "{actor} folgt dir jetzt.",
        },
    ),
    "connection_request": (
        {
            "en": "Connection request",
            "es": "Solicitud de conexión",
            "pt-BR": "Pedido de conexão",
            "fr": "Demande de connexion",
            "de": "Kontaktanfrage",
        },
        {
            "en": "{actor} wants to connect with you.",
            "es": "{actor} quiere conectar contigo.",
            "pt-BR": "{actor} quer se conectar com você.",
            "fr": "{actor} souhaite se connecter avec vous.",
            "de": "{actor} möchte sich mit dir verbinden.",
        },
    ),
    "connection_accepted": (
        {
            "en": "You're connected",
            "es": "Ya estáis conectados",
            "pt-BR": "Vocês estão conectados",
            "fr": "Vous êtes connectés",
            "de": "Ihr seid verbunden",
        },
        {
            "en": "{actor} accepted your connection request.",
            "es": "{actor} aceptó tu solicitud de conexión.",
            "pt-BR": "{actor} aceitou seu pedido de conexão.",
            "fr": "{actor} a accepté votre demande de connexion.",
            "de": "{actor} hat deine Kontaktanfrage angenommen.",
        },
    ),
    "new_message": (
        {
            "en": "New message",
            "es": "Nuevo mensaje",
            "pt-BR": "Nova mensagem",
            "fr": "Nouveau message",
            "de": "Neue Nachricht",
        },
        {
            "en": "{actor} sent you a message.",
            "es": "{actor} te envió un mensaje.",
            "pt-BR": "{actor} enviou uma mensagem para você.",
            "fr": "{actor} vous a envoyé un message.",
            "de": "{actor} hat dir eine Nachricht geschickt.",
        },
    ),
    "post_reaction": (
        {
            "en": "New reaction",
            "es": "Nueva reacción",
            "pt-BR": "Nova reação",
            "fr": "Nouvelle réaction",
            "de": "Neue Reaktion",
        },
        {
            "en": "{actor} reacted to your post.",
            "es": "{actor} reaccionó a tu publicación.",
            "pt-BR": "{actor} reagiu à sua publicação.",
            "fr": "{actor} a réagi à votre publication.",
            "de": "{actor} hat auf deinen Beitrag reagiert.",
        },
    ),
    "post_comment": (
        {
            "en": "New comment",
            "es": "Nuevo comentario",
            "pt-BR": "Novo comentário",
            "fr": "Nouveau commentaire",
            "de": "Neuer Kommentar",
        },
        {
            "en": "{actor} commented on your post.",
            "es": "{actor} comentó tu publicación.",
            "pt-BR": "{actor} comentou na sua publicação.",
            "fr": "{actor} a commenté votre publication.",
            "de": "{actor} hat deinen Beitrag kommentiert.",
        },
    ),
}

# moderation_notice variant (``payload.variant``) → body. The title is always _GUIDELINES.
MODERATION_BODIES: Final[dict[str, Text]] = {
    "removed_post": {
        "en": "One of your posts was removed because it breaks our community guidelines.",
        "es": "Se eliminó una de tus publicaciones porque incumple nuestras normas de la "
        "comunidad.",
        "pt-BR": "Uma das suas publicações foi removida porque viola nossas diretrizes da "
        "comunidade.",
        "fr": "Une de vos publications a été supprimée car elle enfreint nos règles de la "
        "communauté.",
        "de": "Einer deiner Beiträge wurde entfernt, weil er gegen unsere Community-Richtlinien "
        "verstößt.",
    },
    "removed_comment": {
        "en": "One of your comments was removed because it breaks our community guidelines.",
        "es": "Se eliminó uno de tus comentarios porque incumple nuestras normas de la comunidad.",
        "pt-BR": "Um dos seus comentários foi removido porque viola nossas diretrizes da "
        "comunidade.",
        "fr": "Un de vos commentaires a été supprimé car il enfreint nos règles de la communauté.",
        "de": "Einer deiner Kommentare wurde entfernt, weil er gegen unsere "
        "Community-Richtlinien verstößt.",
    },
    "removed_message": {
        "en": "One of your messages was removed because it breaks our community guidelines.",
        "es": "Se eliminó uno de tus mensajes porque incumple nuestras normas de la comunidad.",
        "pt-BR": "Uma das suas mensagens foi removida porque viola nossas diretrizes da "
        "comunidade.",
        "fr": "Un de vos messages a été supprimé car il enfreint nos règles de la communauté.",
        "de": "Eine deiner Nachrichten wurde entfernt, weil sie gegen unsere "
        "Community-Richtlinien verstößt.",
    },
    "restored_message": {
        "en": "One of your messages was reviewed and restored.",
        "es": "Revisamos uno de tus mensajes y lo restablecimos.",
        "pt-BR": "Uma das suas mensagens foi revisada e restaurada.",
        "fr": "Un de vos messages a été examiné et rétabli.",
        "de": "Eine deiner Nachrichten wurde überprüft und wiederhergestellt.",
    },
    "limited_post": {
        "en": "One of your posts will be shown to fewer people because of our community "
        "guidelines.",
        "es": "Una de tus publicaciones se mostrará a menos personas debido a nuestras normas de "
        "la comunidad.",
        "pt-BR": "Uma das suas publicações será exibida para menos pessoas devido às nossas "
        "diretrizes da comunidade.",
        "fr": "Une de vos publications sera montrée à moins de personnes en raison de nos règles "
        "de la communauté.",
        "de": "Einer deiner Beiträge wird aufgrund unserer Community-Richtlinien weniger "
        "Personen angezeigt.",
    },
    "restored_post": {
        "en": "One of your posts was reviewed and restored.",
        "es": "Revisamos una de tus publicaciones y la restablecimos.",
        "pt-BR": "Uma das suas publicações foi revisada e restaurada.",
        "fr": "Une de vos publications a été examinée et rétablie.",
        "de": "Einer deiner Beiträge wurde überprüft und wiederhergestellt.",
    },
    "restored_comment": {
        "en": "One of your comments was reviewed and restored.",
        "es": "Revisamos uno de tus comentarios y lo restablecimos.",
        "pt-BR": "Um dos seus comentários foi revisado e restaurado.",
        "fr": "Un de vos commentaires a été examiné et rétabli.",
        "de": "Einer deiner Kommentare wurde überprüft und wiederhergestellt.",
    },
    "warned": {
        "en": "We've sent you a warning about activity that breaks our community guidelines.",
        "es": "Te enviamos una advertencia por actividad que incumple nuestras normas de la "
        "comunidad.",
        "pt-BR": "Enviamos um aviso sobre uma atividade que viola nossas diretrizes da comunidade.",
        "fr": "Nous vous avons adressé un avertissement concernant une activité qui enfreint nos "
        "règles de la communauté.",
        "de": "Wir haben dich wegen Aktivitäten verwarnt, die gegen unsere "
        "Community-Richtlinien verstoßen.",
    },
    "restricted": {
        "en": "Some features are temporarily limited on your account because of our community "
        "guidelines.",
        "es": "Algunas funciones de tu cuenta están limitadas temporalmente debido a nuestras "
        "normas de la comunidad.",
        "pt-BR": "Alguns recursos da sua conta estão temporariamente limitados devido às nossas "
        "diretrizes da comunidade.",
        "fr": "Certaines fonctionnalités de votre compte sont temporairement limitées en raison "
        "de nos règles de la communauté.",
        "de": "Einige Funktionen deines Kontos sind aufgrund unserer Community-Richtlinien "
        "vorübergehend eingeschränkt.",
    },
    "reinstated": {
        "en": "Your account has been reinstated.",
        "es": "Tu cuenta ha sido restablecida.",
        "pt-BR": "Sua conta foi restabelecida.",
        "fr": "Votre compte a été rétabli.",
        "de": "Dein Konto wurde wiederhergestellt.",
    },
}


def moderation_variant(action: str, target_type: str) -> str | None:
    """Which notice an action produces for the affected user; ``None`` = no notice (suspended
    and banned accounts can't sign in, and other actions have no user-facing effect)."""
    if action == "remove_content" and target_type in ("post", "comment", "message"):
        return f"removed_{target_type}"
    if action == "restore_content" and target_type in ("post", "comment", "message"):
        return f"restored_{target_type}"
    if action == "limit_visibility" and target_type == "post":
        return "limited_post"
    return {"warn": "warned", "restrict": "restricted", "reinstate": "reinstated"}.get(action)


def _pick(text: Text, locale: str) -> str:
    return text.get(locale) or text[DEFAULT_LOCALE]


_PREMIUM_TITLE: Final[Text] = {
    "en": "Group premium",
    "es": "Premium del grupo",
    "pt-BR": "Premium do grupo",
    "fr": "Premium du groupe",
    "de": "Gruppen-Premium",
}

# subscription_notice variants; bodies may use {group}.
SUBSCRIPTION_BODIES: Final[dict[str, Text]] = {
    "group_premium_grace": {
        "en": "The owner's Premium has ended. {group} keeps its admin tools for a grace period.",
        "es": "El Premium del propietario ha terminado. {group} conserva sus herramientas de "
        "administración durante un periodo de gracia.",
        "pt-BR": "O Premium do dono terminou. {group} mantém as ferramentas de administração "
        "por um período de carência.",
        "fr": "Le Premium du propriétaire a pris fin. {group} garde ses outils d'administration "
        "pendant une période de grâce.",
        "de": "Das Premium des Eigentümers ist abgelaufen. {group} behält die Admin-Werkzeuge "
        "für eine Übergangszeit.",
    },
    "group_premium_grace_ending": {
        "en": "{group}'s grace period ends in 3 days. Invitations will pause unless Premium is "
        "renewed or ownership moves to a Premium member.",
        "es": "El periodo de gracia de {group} termina en 3 días. Las invitaciones se pausarán "
        "salvo que se renueve Premium o la propiedad pase a un miembro Premium.",
        "pt-BR": "O período de carência de {group} termina em 3 dias. Os convites serão pausados "
        "a menos que o Premium seja renovado ou a propriedade passe a um membro Premium.",
        "fr": "La période de grâce de {group} se termine dans 3 jours. Les invitations seront "
        "suspendues sauf si Premium est renouvelé ou si un membre Premium devient propriétaire.",
        "de": "Die Übergangszeit von {group} endet in 3 Tagen. Einladungen werden pausiert, "
        "sofern Premium nicht verlängert oder die Gruppe an ein Premium-Mitglied übertragen wird.",
    },
    "group_premium_lapsed": {
        "en": "Premium tools in {group} are paused. Chat, members and safety tools keep working.",
        "es": "Las herramientas Premium de {group} están en pausa. El chat, los miembros y las "
        "herramientas de seguridad siguen funcionando.",
        "pt-BR": "As ferramentas Premium de {group} estão pausadas. Chat, membros e ferramentas "
        "de segurança continuam funcionando.",
        "fr": "Les outils Premium de {group} sont suspendus. La discussion, les membres et les "
        "outils de sécurité continuent de fonctionner.",
        "de": "Die Premium-Werkzeuge von {group} sind pausiert. Chat, Mitglieder und "
        "Sicherheitswerkzeuge funktionieren weiter.",
    },
}


# ai_generation_ready: (title, body) by outcome.
AI_GENERATION_TEXTS: Final[dict[str, tuple[Text, Text]]] = {
    "succeeded": (
        {
            "en": "Your itinerary is ready",
            "es": "Tu itinerario está listo",
            "pt-BR": "Seu roteiro está pronto",
            "fr": "Votre itinéraire est prêt",
            "de": "Dein Reiseplan ist fertig",
        },
        {
            "en": "Open it to review the plan and add it to your trip.",
            "es": "Ábrelo para revisar el plan y añadirlo a tu viaje.",
            "pt-BR": "Abra para revisar o plano e adicioná-lo à sua viagem.",
            "fr": "Ouvrez-le pour revoir le programme et l'ajouter à votre voyage.",
            "de": "Öffne ihn, um den Plan zu prüfen und zu deiner Reise hinzuzufügen.",
        },
    ),
    "failed": (
        {
            "en": "We couldn't finish your itinerary",
            "es": "No pudimos terminar tu itinerario",
            "pt-BR": "Não conseguimos concluir seu roteiro",
            "fr": "Nous n'avons pas pu terminer votre itinéraire",
            "de": "Wir konnten deinen Reiseplan nicht fertigstellen",
        },
        {
            "en": "It didn't count towards your monthly limit. Please try again.",
            "es": "No se descontó de tu límite mensual. Inténtalo de nuevo.",
            "pt-BR": "Isso não foi descontado do seu limite mensal. Tente novamente.",
            "fr": "Cela n'a pas été décompté de votre limite mensuelle. Réessayez.",
            "de": "Das wurde nicht auf dein Monatslimit angerechnet. Bitte versuch es erneut.",
        },
    ),
}


# challenge_started / challenge_result: (title, body) by variant; bodies use {title}.
CHALLENGE_TEXTS: Final[dict[str, tuple[Text, Text]]] = {
    "started": (
        {
            "en": "A challenge has started",
            "es": "Empezó un desafío",
            "pt-BR": "Um desafio começou",
            "fr": "Un défi a commencé",
            "de": "Eine Challenge hat begonnen",
        },
        {
            "en": "{title} is live in your group. Good luck!",
            "es": "{title} ya está activo en tu grupo. ¡Suerte!",
            "pt-BR": "{title} já está valendo no seu grupo. Boa sorte!",
            "fr": "{title} est lancé dans votre groupe. Bonne chance !",
            "de": "{title} läuft jetzt in deiner Gruppe. Viel Glück!",
        },
    ),
    "published": (
        {
            "en": "Challenge results are in",
            "es": "Ya hay resultados del desafío",
            "pt-BR": "Saiu o resultado do desafio",
            "fr": "Les résultats du défi sont là",
            "de": "Die Ergebnisse der Challenge sind da",
        },
        {
            "en": "See who solved {title}.",
            "es": "Mira quién resolvió {title}.",
            "pt-BR": "Veja quem resolveu {title}.",
            "fr": "Découvrez qui a résolu {title}.",
            "de": "Sieh nach, wer {title} gelöst hat.",
        },
    ),
    "reward_issued": (
        {
            "en": "Your reward is ready",
            "es": "Tu premio está listo",
            "pt-BR": "Seu prêmio está pronto",
            "fr": "Votre récompense est prête",
            "de": "Deine Belohnung ist bereit",
        },
        {
            "en": "Your reward for {title} is waiting in My rewards.",
            "es": "Tu premio de {title} te espera en Mis premios.",
            "pt-BR": "Seu prêmio de {title} está em Meus prêmios.",
            "fr": "Votre récompense pour {title} vous attend dans Mes récompenses.",
            "de": "Deine Belohnung für {title} wartet unter Meine Belohnungen.",
        },
    ),
    "cancelled": (
        {
            "en": "Challenge cancelled",
            "es": "Desafío cancelado",
            "pt-BR": "Desafio cancelado",
            "fr": "Défi annulé",
            "de": "Challenge abgesagt",
        },
        {
            "en": "{title} was cancelled by the group admins.",
            "es": "Los administradores del grupo cancelaron {title}.",
            "pt-BR": "Os administradores do grupo cancelaram {title}.",
            "fr": "Les administrateurs du groupe ont annulé {title}.",
            "de": "{title} wurde von den Gruppen-Admins abgesagt.",
        },
    ),
}


# data_export_ready (BL-6.03): the archive and its 7-day link are ready.
DATA_EXPORT_TEXTS: Final[tuple[Text, Text]] = (
    {
        "en": "Your data is ready",
        "es": "Tus datos están listos",
        "pt-BR": "Seus dados estão prontos",
        "fr": "Vos données sont prêtes",
        "de": "Deine Daten sind bereit",
    },
    {
        "en": "Download your archive within 7 days from Settings > Your data.",
        "es": "Descarga tu archivo en los próximos 7 días desde Ajustes > Tus datos.",
        "pt-BR": "Baixe seu arquivo em até 7 dias em Configurações > Seus dados.",
        "fr": "Téléchargez votre archive sous 7 jours depuis Réglages > Vos données.",
        "de": "Lade dein Archiv innerhalb von 7 Tagen unter Einstellungen > Deine Daten herunter.",
    },
)


def render(
    kind: str, payload: Mapping[str, Any], *, actor: str | None, locale: str
) -> tuple[str, str]:
    """(title, body) for a stored notification in ``locale``."""
    if kind == "subscription_notice":
        body = SUBSCRIPTION_BODIES.get(
            str(payload.get("variant")), SUBSCRIPTION_BODIES["group_premium_lapsed"]
        )
        group = str(payload.get("group_name") or "")
        return _pick(_PREMIUM_TITLE, locale), _pick(body, locale).format(group=group)
    if kind in ("challenge_started", "challenge_result"):
        default = "started" if kind == "challenge_started" else "cancelled"
        title, body = CHALLENGE_TEXTS.get(str(payload.get("variant")), CHALLENGE_TEXTS[default])
        return _pick(title, locale), _pick(body, locale).format(title=payload.get("title") or "")
    if kind == "ai_generation_ready":
        outcome = "succeeded" if payload.get("status") == "succeeded" else "failed"
        title, body = AI_GENERATION_TEXTS[outcome]
        return _pick(title, locale), _pick(body, locale)
    if kind == "data_export_ready":
        return _pick(DATA_EXPORT_TEXTS[0], locale), _pick(DATA_EXPORT_TEXTS[1], locale)
    if kind == "moderation_notice":
        body = MODERATION_BODIES.get(str(payload.get("variant")), MODERATION_BODIES["warned"])
        return _pick(_GUIDELINES, locale), _pick(body, locale)
    title, body = _TEMPLATES[kind]
    name = actor or _pick(SOMEONE, locale)
    return _pick(title, locale), _pick(body, locale).format(actor=name)


def renderable_kinds() -> frozenset[str]:
    return frozenset(
        {
            *_TEMPLATES,
            "ai_generation_ready",
            "challenge_started",
            "challenge_result",
            "data_export_ready",
            "moderation_notice",
            "subscription_notice",
        }
    )


def in_quiet_hours(now_local_minutes: int, start: str, end: str) -> bool:
    """Whether a local time (minutes after midnight) falls in ``[start, end)``; the window may
    cross midnight (NOTIF-003)."""

    def minutes(value: str) -> int:
        hours, mins = value.split(":")
        return int(hours) * 60 + int(mins)

    begin, finish = minutes(start), minutes(end)
    if begin < finish:
        return begin <= now_local_minutes < finish
    return now_local_minutes >= begin or now_local_minutes < finish
