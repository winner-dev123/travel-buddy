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

# Notices about the traveller's own plan (billing.notice; BILL-011).
_PLAN_TITLE: Final[Text] = {
    "en": "Your Premium",
    "es": "Tu Premium",
    "pt-BR": "Seu Premium",
    "fr": "Votre Premium",
    "de": "Dein Premium",
}
BILLING_VARIANTS: Final[frozenset[str]] = frozenset(
    {"payment_failed", "payment_confirmed", "refunded", "expiring"}
)

# subscription_notice variants; bodies may use {group}.
SUBSCRIPTION_BODIES: Final[dict[str, Text]] = {
    "payment_failed": {
        "en": "Your payment didn't go through. Check your payment method so you don't lose access.",
        "es": "Tu pago no se completó. Revisa tu método de pago para no perder el acceso.",
        "pt-BR": "Seu pagamento não foi concluído. Verifique sua forma de pagamento para não "
        "perder o acesso.",
        "fr": "Votre paiement n'a pas abouti. Vérifiez votre moyen de paiement pour ne pas "
        "perdre l'accès.",
        "de": "Deine Zahlung ist nicht durchgegangen. Prüfe deine Zahlungsmethode, damit du "
        "den Zugang behältst.",
    },
    "payment_confirmed": {
        "en": "Your payment went through. Premium is active.",
        "es": "Tu pago se confirmó. Premium está activo.",
        "pt-BR": "Seu pagamento foi confirmado. O Premium está ativo.",
        "fr": "Votre paiement est confirmé. Premium est actif.",
        "de": "Deine Zahlung ist eingegangen. Premium ist aktiv.",
    },
    "refunded": {
        "en": "Your payment was refunded, so the purchase it paid for has ended.",
        "es": "Te reembolsamos el pago, así que la compra que cubría ha terminado.",
        "pt-BR": "Seu pagamento foi reembolsado, então a compra que ele pagou terminou.",
        "fr": "Votre paiement a été remboursé : l'achat correspondant a pris fin.",
        "de": "Deine Zahlung wurde erstattet, daher endet der damit bezahlte Kauf.",
    },
    "expiring": {
        "en": "Your Premium ends in a few days. Renew to keep your benefits.",
        "es": "Tu Premium termina en unos días. Renuévalo para conservar tus ventajas.",
        "pt-BR": "Seu Premium termina em poucos dias. Renove para manter seus benefícios.",
        "fr": "Votre Premium se termine dans quelques jours. Renouvelez-le pour garder vos "
        "avantages.",
        "de": "Dein Premium endet in ein paar Tagen. Verlängere es, um deine Vorteile zu behalten.",
    },
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


# new_message whose message is a gift (payload.message_kind == "gift"; DM-016).
GIFT_TEXTS: Final[tuple[Text, Text]] = (
    {
        "en": "New gift",
        "es": "Nuevo regalo",
        "pt-BR": "Novo presente",
        "fr": "Nouveau cadeau",
        "de": "Neues Geschenk",
    },
    {
        "en": "{actor} sent you a gift.",
        "es": "{actor} te envió un regalo.",
        "pt-BR": "{actor} enviou um presente para você.",
        "fr": "{actor} vous a envoyé un cadeau.",
        "de": "{actor} hat dir ein Geschenk geschickt.",
    },
)


# Guides and travel companies (ADR-0036, docs/18 §6): (kind, payload.variant) → (title, body).
# Bodies may use {provider} (payload.provider_name) and {actor}.
_REQUEST_UPDATE: Final[Text] = {
    "en": "Request update",
    "es": "Novedades de tu solicitud",
    "pt-BR": "Atualização do pedido",
    "fr": "Mise à jour de la demande",
    "de": "Neuigkeiten zur Anfrage",
}
_APPLICATION: Final[Text] = {
    "en": "Your provider profile",
    "es": "Tu perfil de proveedor",
    "pt-BR": "Seu perfil de prestador",
    "fr": "Votre profil de prestataire",
    "de": "Dein Anbieterprofil",
}
PROVIDER_TEXTS: Final[dict[tuple[str, str], tuple[Text, Text]]] = {
    ("provider_invitation", ""): (
        {
            "en": "Team invitation",
            "es": "Invitación al equipo",
            "pt-BR": "Convite para a equipe",
            "fr": "Invitation à rejoindre l'équipe",
            "de": "Einladung ins Team",
        },
        {
            "en": "{actor} invited you to join {provider}.",
            "es": "{actor} te invitó a unirte a {provider}.",
            "pt-BR": "{actor} convidou você para fazer parte de {provider}.",
            "fr": "{actor} vous invite à rejoindre {provider}.",
            "de": "{actor} hat dich zu {provider} eingeladen.",
        },
    ),
    ("provider_application", "approved"): (
        _APPLICATION,
        {
            "en": "{provider} is approved and now visible to travelers.",
            "es": "{provider} fue aprobado y ya es visible para los viajeros.",
            "pt-BR": "{provider} foi aprovado e já aparece para os viajantes.",
            "fr": "{provider} est approuvé et désormais visible par les voyageurs.",
            "de": "{provider} ist freigegeben und für Reisende sichtbar.",
        },
    ),
    ("provider_application", "changes_requested"): (
        _APPLICATION,
        {
            "en": "Our team asked for a few changes to {provider}.",
            "es": "Nuestro equipo pidió algunos cambios en {provider}.",
            "pt-BR": "Nossa equipe pediu alguns ajustes em {provider}.",
            "fr": "Notre équipe demande quelques modifications pour {provider}.",
            "de": "Unser Team bittet um ein paar Änderungen an {provider}.",
        },
    ),
    ("provider_application", "rejected"): (
        _APPLICATION,
        {
            "en": "We couldn't approve {provider}. See the note from our team.",
            "es": "No pudimos aprobar {provider}. Consulta la nota de nuestro equipo.",
            "pt-BR": "Não foi possível aprovar {provider}. Veja a nota da nossa equipe.",
            "fr": "Nous n'avons pas pu approuver {provider}. Consultez la note de notre équipe.",
            "de": "{provider} wurde nicht freigegeben. Sieh dir die Notiz unseres Teams an.",
        },
    ),
    ("provider_application", "suspended"): (
        _APPLICATION,
        {
            "en": "{provider} is suspended and hidden from travelers.",
            "es": "{provider} está suspendido y oculto para los viajeros.",
            "pt-BR": "{provider} foi suspenso e não aparece para os viajantes.",
            "fr": "{provider} est suspendu et masqué aux voyageurs.",
            "de": "{provider} ist gesperrt und für Reisende ausgeblendet.",
        },
    ),
    ("provider_application", "reinstated"): (
        _APPLICATION,
        {
            "en": "{provider} is visible to travelers again.",
            "es": "{provider} vuelve a ser visible para los viajeros.",
            "pt-BR": "{provider} voltou a aparecer para os viajantes.",
            "fr": "{provider} est de nouveau visible par les voyageurs.",
            "de": "{provider} ist für Reisende wieder sichtbar.",
        },
    ),
    ("provider_inquiry", ""): (
        {
            "en": "New request",
            "es": "Nueva solicitud",
            "pt-BR": "Novo pedido",
            "fr": "Nouvelle demande",
            "de": "Neue Anfrage",
        },
        {
            "en": "{actor} sent {provider} a request.",
            "es": "{actor} envió una solicitud a {provider}.",
            "pt-BR": "{actor} enviou um pedido para {provider}.",
            "fr": "{actor} a envoyé une demande à {provider}.",
            "de": "{actor} hat {provider} eine Anfrage geschickt.",
        },
    ),
    ("provider_inquiry_update", "accepted"): (
        _REQUEST_UPDATE,
        {
            "en": "{provider} accepted your request.",
            "es": "{provider} aceptó tu solicitud.",
            "pt-BR": "{provider} aceitou seu pedido.",
            "fr": "{provider} a accepté votre demande.",
            "de": "{provider} hat deine Anfrage angenommen.",
        },
    ),
    ("provider_inquiry_update", "declined"): (
        _REQUEST_UPDATE,
        {
            "en": "{provider} can't take your request.",
            "es": "{provider} no puede aceptar tu solicitud.",
            "pt-BR": "{provider} não pode atender seu pedido.",
            "fr": "{provider} ne peut pas donner suite à votre demande.",
            "de": "{provider} kann deine Anfrage nicht annehmen.",
        },
    ),
    ("provider_inquiry_update", "completed"): (
        _REQUEST_UPDATE,
        {
            "en": "How was it with {provider}? Leave a review.",
            "es": "¿Qué tal con {provider}? Deja una reseña.",
            "pt-BR": "Como foi com {provider}? Deixe uma avaliação.",
            "fr": "Comment s'est passé votre expérience avec {provider} ? Laissez un avis.",
            "de": "Wie war es mit {provider}? Schreib eine Bewertung.",
        },
    ),
    ("provider_inquiry_update", "cancelled_by_provider"): (
        _REQUEST_UPDATE,
        {
            "en": "{provider} cancelled your request.",
            "es": "{provider} canceló tu solicitud.",
            "pt-BR": "{provider} cancelou seu pedido.",
            "fr": "{provider} a annulé votre demande.",
            "de": "{provider} hat deine Anfrage storniert.",
        },
    ),
    ("provider_inquiry_update", "withdrawn"): (
        _REQUEST_UPDATE,
        {
            "en": "{actor} withdrew their request to {provider}.",
            "es": "{actor} retiró su solicitud a {provider}.",
            "pt-BR": "{actor} retirou o pedido para {provider}.",
            "fr": "{actor} a retiré sa demande à {provider}.",
            "de": "{actor} hat die Anfrage an {provider} zurückgezogen.",
        },
    ),
    ("provider_inquiry_update", "cancelled_by_traveler"): (
        _REQUEST_UPDATE,
        {
            "en": "{actor} cancelled their request to {provider}.",
            "es": "{actor} canceló su solicitud a {provider}.",
            "pt-BR": "{actor} cancelou o pedido para {provider}.",
            "fr": "{actor} a annulé sa demande à {provider}.",
            "de": "{actor} hat die Anfrage an {provider} storniert.",
        },
    ),
    ("provider_review", ""): (
        {
            "en": "New review",
            "es": "Nueva reseña",
            "pt-BR": "Nova avaliação",
            "fr": "Nouvel avis",
            "de": "Neue Bewertung",
        },
        {
            "en": "{actor} reviewed {provider}.",
            "es": "{actor} dejó una reseña de {provider}.",
            "pt-BR": "{actor} avaliou {provider}.",
            "fr": "{actor} a laissé un avis sur {provider}.",
            "de": "{actor} hat {provider} bewertet.",
        },
    ),
}
PROVIDER_KINDS: Final = frozenset(kind for kind, _ in PROVIDER_TEXTS)


def render(
    kind: str, payload: Mapping[str, Any], *, actor: str | None, locale: str
) -> tuple[str, str]:
    """(title, body) for a stored notification in ``locale``."""
    if kind in PROVIDER_KINDS:
        variant = str(payload.get("variant") or "")
        texts = PROVIDER_TEXTS.get((kind, variant)) or next(
            v for (k, _), v in PROVIDER_TEXTS.items() if k == kind
        )
        provider = str(payload.get("provider_name") or "")
        name = actor or _pick(SOMEONE, locale)
        return _pick(texts[0], locale), _pick(texts[1], locale).format(
            actor=name, provider=provider
        )
    if kind == "new_message" and payload.get("message_kind") == "gift":
        title, body = GIFT_TEXTS
        name = actor or _pick(SOMEONE, locale)
        return _pick(title, locale), _pick(body, locale).format(actor=name)
    if kind == "subscription_notice":
        body = SUBSCRIPTION_BODIES.get(
            str(payload.get("variant")), SUBSCRIPTION_BODIES["group_premium_lapsed"]
        )
        group = str(payload.get("group_name") or "")
        title = _PLAN_TITLE if payload.get("variant") in BILLING_VARIANTS else _PREMIUM_TITLE
        return _pick(title, locale), _pick(body, locale).format(group=group)
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
            *PROVIDER_KINDS,
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
