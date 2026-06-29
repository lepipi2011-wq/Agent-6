"""Datenmodell — Entity-Graph + Claims.

Kanonische Entitäten (Organization/Brand/Model/Pattern/Application/Contact) plus
ein generisches Claim (jede Aussage mit Quelle, Methode, Confidence, Zeit).
Läuft auf SQLite (Dev/Validierung) und Postgres (Prod) — dieselbe Definition.
"""
from __future__ import annotations
import datetime as dt
from sqlalchemy import (create_engine, String, Integer, Float, DateTime, ForeignKey, Text, JSON)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker


class Base(DeclarativeBase):
    pass


def _now():
    return dt.datetime.now(dt.timezone.utc)


class Organization(Base):
    __tablename__ = "organization"
    id: Mapped[int] = mapped_column(primary_key=True)
    canonical_name: Mapped[str] = mapped_column(String(400), index=True)
    norm_name: Mapped[str] = mapped_column(String(400), index=True)   # für Dedup
    lei: Mapped[str | None] = mapped_column(String(20), index=True)    # GLEIF — starker Schlüssel
    vat: Mapped[str | None] = mapped_column(String(32), index=True)    # VIES
    hr_number: Mapped[str | None] = mapped_column(String(64))          # Handelsregister
    country: Mapped[str | None] = mapped_column(String(4), index=True)
    domain: Mapped[str | None] = mapped_column(String(255))
    address: Mapped[str | None] = mapped_column(String(400))
    status: Mapped[str | None] = mapped_column(String(32))             # oem | distributor | unknown
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    first_seen: Mapped[dt.datetime] = mapped_column(DateTime, default=_now)
    last_verified: Mapped[dt.datetime | None] = mapped_column(DateTime)
    brands: Mapped[list["Brand"]] = relationship(back_populates="organization")
    models: Mapped[list["Model"]] = relationship(back_populates="organization")
    contacts: Mapped[list["Contact"]] = relationship(back_populates="organization")


class Brand(Base):
    __tablename__ = "brand"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), index=True)
    organization_id: Mapped[int | None] = mapped_column(ForeignKey("organization.id"))
    organization: Mapped[Organization | None] = relationship(back_populates="brands")


class Model(Base):
    __tablename__ = "model"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), index=True)
    organization_id: Mapped[int | None] = mapped_column(ForeignKey("organization.id"))
    pattern_code: Mapped[str | None] = mapped_column(String(8), index=True)
    segment: Mapped[str | None] = mapped_column(String(120))
    specs: Mapped[dict | None] = mapped_column(JSON)  # weight_t, power_kw, can, hmi_type
    organization: Mapped[Organization | None] = relationship(back_populates="models")


class Pattern(Base):
    __tablename__ = "pattern"
    code: Mapped[str] = mapped_column(String(8), primary_key=True)
    name: Mapped[str | None] = mapped_column(String(255))
    img_query: Mapped[str | None] = mapped_column(Text)
    text_terms: Mapped[str | None] = mapped_column(Text)
    ref_oem: Mapped[str | None] = mapped_column(String(255))
    segment: Mapped[str | None] = mapped_column(String(120))
    is_candidate: Mapped[int] = mapped_column(Integer, default=0)  # 1 = aus Application-Discovery, noch nicht bestätigt


class Application(Base):
    __tablename__ = "application"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), index=True)
    description: Mapped[str | None] = mapped_column(Text)
    source_url: Mapped[str | None] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(32), default="candidate")  # candidate|verified|rejected


class Contact(Base):
    __tablename__ = "contact"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organization.id"))
    name: Mapped[str | None] = mapped_column(String(255))
    role: Mapped[str | None] = mapped_column(String(120))
    email: Mapped[str | None] = mapped_column(String(255))
    email_status: Mapped[str | None] = mapped_column(String(32))
    source_url: Mapped[str | None] = mapped_column(String(500))
    organization: Mapped[Organization | None] = relationship(back_populates="contacts")


class Claim(Base):
    """Jede Einzelaussage über eine Entität — mit Provenienz und Confidence."""
    __tablename__ = "claim"
    id: Mapped[int] = mapped_column(primary_key=True)
    subject_type: Mapped[str] = mapped_column(String(32), index=True)  # organization|model|...
    subject_id: Mapped[int] = mapped_column(Integer, index=True)
    predicate: Mapped[str] = mapped_column(String(64), index=True)     # address|oem_status|pattern|funk|...
    object_value: Mapped[str | None] = mapped_column(Text)
    source_url: Mapped[str | None] = mapped_column(String(500))
    source_type: Mapped[str | None] = mapped_column(String(32))        # register|impressum|vies|gleif|vlm|search
    method: Mapped[str | None] = mapped_column(String(64))
    confidence: Mapped[float] = mapped_column(Float, default=0.5)
    observed_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now)


class MergeCandidate(Base):
    """Schwacher Match, der NICHT automatisch gemerged wurde — für Mensch-Review."""
    __tablename__ = "merge_candidate"
    id: Mapped[int] = mapped_column(primary_key=True)
    new_org_id: Mapped[int] = mapped_column(ForeignKey("organization.id"))
    matched_org_id: Mapped[int] = mapped_column(ForeignKey("organization.id"))
    new_name: Mapped[str] = mapped_column(String(400))
    matched_name: Mapped[str] = mapped_column(String(400))
    tier: Mapped[str] = mapped_column(String(24))       # substring | brand-token
    reason: Mapped[str | None] = mapped_column(String(200))
    score: Mapped[float] = mapped_column(Float, default=0.0)
    decision: Mapped[str] = mapped_column(String(16), default="pending")  # pending|merge|keep-separate
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now)


def make_engine(url: str = "sqlite:///agent6.db"):
    return create_engine(url, future=True)


def init_db(engine):
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)
