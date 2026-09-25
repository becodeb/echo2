"""Alta sin invitación: por dominio del email o por email exacto.

Cada organización tiene `join_rules`, una lista que edita un superadmin con
dominios ("northfield.edu.ar") o emails exactos ("mariana@gmail.com"). Se
suma AUTO_JOIN_DOMAINS del entorno, que es la forma vieja de lo mismo.

Reglas:
- Solo cuentas vinculadas a Google: es la única vía en la que Echo sabe que
  el email es de quien dice ser. Con contraseña cualquiera se inventaría una
  casilla del colegio.
- Email exacto: entra solo a todas las organizaciones que lo listan. Es una
  asignación explícita de una persona.
- Dominio con una sola organización: entra solo.
- Dominio con varias (las sedes de un mismo colegio): no entra a ninguna; la
  pantalla de bienvenida le pregunta de qué sede es.
- Siempre como `member`: subirle el rol sigue siendo decisión de un admin.

Ninguna función hace commit: lo hace quien llama.
"""
import re
import uuid
from dataclasses import dataclass, field

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..models import Organization, OrganizationMember, User
from .audit import audit

_EMAIL_RE = re.compile(r"^[^@\s]+@[a-z0-9-]+(\.[a-z0-9-]+)+$")
_DOMAIN_RE = re.compile(r"^(?=.{4,253}$)([a-z0-9-]+\.)+[a-z]{2,}$")

# Un dominio público como regla metería en la organización a cualquiera que
# se registre con esa casilla. Para una persona puntual, se usa su email.
PUBLIC_DOMAINS = {
    "gmail.com", "googlemail.com", "hotmail.com", "hotmail.com.ar", "outlook.com",
    "outlook.com.ar", "live.com", "live.com.ar", "yahoo.com", "yahoo.com.ar",
    "icloud.com", "me.com", "proton.me", "protonmail.com", "aol.com", "fibertel.com.ar",
}


class InvalidRule(ValueError):
    pass


def normalize_rule(raw: str) -> str:
    """Normaliza un dominio o un email. Levanta InvalidRule si no sirve."""
    value = raw.strip().lower()
    if "@" in value.lstrip("@"):
        if not _EMAIL_RE.match(value):
            raise InvalidRule(f"«{raw.strip()}» no es un email válido")
        return value
    value = value.lstrip("@")
    if not _DOMAIN_RE.match(value):
        raise InvalidRule(f"«{raw.strip()}» no es un dominio válido (ej: colegio.edu.ar)")
    if value in PUBLIC_DOMAINS:
        raise InvalidRule(
            f"«{value}» es un correo público: sumaría a cualquiera. Para una persona puntual, cargá su email."
        )
    return value


def normalize_rules(raw_rules: list[str]) -> list[str]:
    out: list[str] = []
    for raw in raw_rules:
        if not raw.strip():
            continue
        rule = normalize_rule(raw)
        if rule not in out:
            out.append(rule)
    return out


@dataclass
class Matches:
    by_email: list[Organization] = field(default_factory=list)
    by_domain: list[Organization] = field(default_factory=list)

    @property
    def all(self) -> list[Organization]:
        return self.by_email + self.by_domain


async def matching_organizations(db: AsyncSession, email: str) -> Matches:
    email = email.lower()
    domain = email.rsplit("@", 1)[-1]
    env_slugs = get_settings().auto_join_domain_map.get(domain, [])
    conditions = [
        Organization.join_rules.contains([email]),
        Organization.join_rules.contains([domain]),
    ]
    if env_slugs:
        conditions.append(Organization.slug.in_(env_slugs))
    orgs = (
        (
            await db.execute(
                select(Organization)
                .where(Organization.deleted_at.is_(None), or_(*conditions))
                .order_by(Organization.name)
            )
        )
        .scalars()
        .all()
    )
    matches = Matches()
    for org in orgs:
        if email in (org.join_rules or []):
            matches.by_email.append(org)
        else:
            matches.by_domain.append(org)
    return matches


async def _member_org_ids(db: AsyncSession, user_id: uuid.UUID) -> set[uuid.UUID]:
    return set(
        (
            await db.execute(
                select(OrganizationMember.organization_id).where(OrganizationMember.user_id == user_id)
            )
        )
        .scalars()
        .all()
    )


async def _join(db: AsyncSession, user: User, org: Organization, how: str) -> None:
    db.add(OrganizationMember(organization_id=org.id, user_id=user.id, role="member"))
    await audit(db, org.id, user.id, "org.domain_joined", "organization", str(org.id), detail={"via": how})


async def auto_join(db: AsyncSession, user: User) -> None:
    """Se llama en cada login con Google y en cada refresh de sesión."""
    if not user.google_sub:
        return
    matches = await matching_organizations(db, user.email)
    if not matches.all:
        return
    member_of = await _member_org_ids(db, user.id)

    for org in matches.by_email:
        if org.id not in member_of:
            await _join(db, user, org, "email")
            member_of.add(org.id)

    # Por dominio solo si no hay nada que elegir y todavía no está en ninguna
    # de esas organizaciones (si ya eligió sede, no se lo suma a la otra).
    if len(matches.by_domain) == 1 and not member_of & {org.id for org in matches.all}:
        await _join(db, user, matches.by_domain[0], "domain")


@dataclass
class PendingChoice:
    requires_google: bool
    organizations: list[Organization]


async def pending_choice(db: AsyncSession, user: User) -> PendingChoice:
    """Sedes entre las que tiene que elegir, si su dominio tiene varias.

    Para una cuenta sin Google devuelve las organizaciones de su dominio igual,
    marcadas: la pantalla le explica que tiene que entrar con Google.
    """
    matches = await matching_organizations(db, user.email)
    member_of = await _member_org_ids(db, user.id)
    if member_of & {org.id for org in matches.all}:
        return PendingChoice(requires_google=False, organizations=[])
    if not user.google_sub:
        return PendingChoice(requires_google=bool(matches.all), organizations=matches.all)
    options = matches.by_domain if len(matches.by_domain) > 1 else []
    return PendingChoice(requires_google=False, organizations=options)


class NotAllowed(Exception):
    pass


async def join_chosen(db: AsyncSession, user: User, org_id: uuid.UUID) -> Organization:
    """Suma al usuario a la sede que eligió, si su email lo habilita."""
    if not user.google_sub:
        raise NotAllowed("Para unirte sin invitación tenés que entrar con Google con tu email institucional.")
    matches = await matching_organizations(db, user.email)
    org = next((org for org in matches.all if org.id == org_id), None)
    if org is None:
        raise NotAllowed("Tu email no está habilitado para unirse a esa organización.")
    if org.id not in await _member_org_ids(db, user.id):
        await _join(db, user, org, "choice")
    return org
