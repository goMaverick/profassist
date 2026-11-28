"""Private Moodle dropout exports, identity mappings, and scored predictions."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


def _uuid() -> Mapped[uuid.UUID]:
    return mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


class ProfAssistDropoutExport(Base, TimestampMixin):
    """Immutable admin-imported day-35 snapshot bundle for one ProfAssist course."""

    __tablename__ = "pa_dropout_exports"
    __table_args__ = (
        UniqueConstraint(
            "organization_id", "course_id", "checksum", name="uq_pa_dropout_export_checksum"
        ),
    )

    id: Mapped[uuid.UUID] = _uuid()
    organization_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    course_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("pa_courses.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_by: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    external_export_id: Mapped[str] = mapped_column(String(128), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(16), nullable=False)
    checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    manifest_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    snapshots_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    outcomes_sha256: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    snapshots_csv: Mapped[str] = mapped_column(Text, nullable=False)
    outcomes_csv: Mapped[str] = mapped_column(Text, nullable=False, default="")
    manifest: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    cohorts: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False)
    outcome_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="validated")


class ProfAssistDropoutIdentity(Base, TimestampMixin):
    """Application-private binding from an export pseudonym to an enrolled Moodle student."""

    __tablename__ = "pa_dropout_identities"
    __table_args__ = (
        UniqueConstraint("organization_id", "student_key", name="uq_pa_dropout_identity_key"),
    )

    id: Mapped[uuid.UUID] = _uuid()
    organization_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("pa_students.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    student_key: Mapped[str] = mapped_column(String(128), nullable=False)


class ProfAssistDropoutPrediction(Base, TimestampMixin):
    """Immutable result for a mapped learner row, pinned to an export and model."""

    __tablename__ = "pa_dropout_predictions"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "course_id",
            "student_id",
            "cutoff_at",
            "model_name",
            "model_version",
            "export_checksum",
            name="uq_pa_dropout_prediction_input",
        ),
    )

    id: Mapped[uuid.UUID] = _uuid()
    organization_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    course_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("pa_courses.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    export_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("pa_dropout_exports.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("pa_students.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    student_key: Mapped[str] = mapped_column(String(128), nullable=False)
    cutoff_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    predicted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    probability: Mapped[float] = mapped_column(Float, nullable=False)
    risk_band: Mapped[str] = mapped_column(String(16), nullable=False)
    explanation: Mapped[list[dict] | None] = mapped_column(JSONB, nullable=True)
    prediction_status: Mapped[str] = mapped_column(String(16), nullable=False, default="scored")
    model_name: Mapped[str] = mapped_column(String(128), nullable=False)
    model_version: Mapped[str] = mapped_column(String(64), nullable=False)
    feature_schema_version: Mapped[str] = mapped_column(String(32), nullable=False)
    training_data_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    batch_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    export_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
