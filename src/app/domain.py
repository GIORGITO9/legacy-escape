"""Modelo canónico del dominio Afiliaciones.

Es el idioma que hablan el gateway y sus consumidores. No conoce tablas, columnas
ni códigos del sistema anterior: esa traducción vive solo en el adapter.
"""

from dataclasses import asdict, dataclass, field
from typing import List, Optional

MEMBER_STATUSES = ("ACTIVE", "RETIRED", "SUSPENDED")
RELATIONSHIPS = ("SPOUSE", "CHILD", "FATHER", "MOTHER")
MIGRATION_STATES = ("LEGACY", "DUAL", "MODERN")
DOMAINS = ("affiliations", "companies", "contributions")


class LegacyUnavailable(Exception):
    """La base del sistema anterior no responde."""


class NotFound(Exception):
    """El recurso pedido no existe."""


class Conflict(Exception):
    """El requestId ya se usó para otro afiliado."""


@dataclass
class CompanyRef:
    id: str
    name: str


@dataclass
class Member:
    document: str
    fullName: str
    status: str
    company: Optional[CompanyRef]

    def to_dict(self):
        return asdict(self)


@dataclass
class Beneficiary:
    document: str
    fullName: str
    relationship: str

    def to_dict(self):
        return asdict(self)


@dataclass
class Company:
    id: str
    name: str
    activeMembers: int

    def to_dict(self):
        return asdict(self)


@dataclass
class Retirement:
    requestId: str
    document: str
    date: str
    reason: str
    state: str = "APPLIED"
    movementId: Optional[int] = None
    extra: dict = field(default_factory=dict)

    def to_dict(self):
        data = asdict(self)
        data.pop("extra")
        data.update(self.extra)
        return data


def full_name(parts: List[Optional[str]]) -> str:
    return " ".join(p.strip() for p in parts if p and p.strip())
