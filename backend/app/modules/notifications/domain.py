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


def render(
    kind: str, payload: Mapping[str, Any], *, actor: str | None, locale: str
) -> tuple[str, str]:
    """(title, body) for a stored notification in ``locale``."""
    if kind == "moderation_notice":
        body = MODERATION_BODIES.get(str(payload.get("variant")), MODERATION_BODIES["warned"])
        return _pick(_GUIDELINES, locale), _pick(body, locale)
    title, body = _TEMPLATES[kind]
    name = actor or _pick(SOMEONE, locale)
    return _pick(title, locale), _pick(body, locale).format(actor=name)


def renderable_kinds() -> frozenset[str]:
    return frozenset({*_TEMPLATES, "moderation_notice"})
