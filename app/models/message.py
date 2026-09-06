"""Yiriba SaaS — Messaging models: conversations, participants, messages."""

import enum
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class ConversationType(str, enum.Enum):
    DIRECT = "direct"
    BROADCAST = "broadcast"


class Conversation(Base):
    """Conversation between users within a school."""

    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    school_id: Mapped[int] = mapped_column(
        ForeignKey("schools.id", ondelete="CASCADE"), nullable=False, index=True
    )
    type: Mapped[str] = mapped_column(String(20), nullable=False, default="direct")
    subject: Mapped[str | None] = mapped_column(String(200))
    created_by: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relations
    participants: Mapped[list["ConversationParticipant"]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan"
    )
    messages: Mapped[list["Message"]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan"
    )
    creator: Mapped["User"] = relationship(foreign_keys=[created_by])  # noqa: F821

    def __repr__(self) -> str:
        return f"<Conversation id={self.id} type='{self.type}'>"


class ConversationParticipant(Base):
    """Participant in a conversation. Tracks last_read_at for unread count."""

    __tablename__ = "conversation_participants"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    last_read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relations
    conversation: Mapped["Conversation"] = relationship(back_populates="participants")  # noqa: F821
    user: Mapped["User"] = relationship()  # noqa: F821

    __table_args__ = (
        UniqueConstraint("conversation_id", "user_id", name="uq_conv_participant"),
    )

    def __repr__(self) -> str:
        return f"<ConversationParticipant conv={self.conversation_id} user={self.user_id}>"


class Message(Base):
    """A message within a conversation."""

    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sender_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    attachment_url: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relations
    conversation: Mapped["Conversation"] = relationship(back_populates="messages")  # noqa: F821
    sender: Mapped["User"] = relationship(foreign_keys=[sender_id])  # noqa: F821

    def __repr__(self) -> str:
        return f"<Message id={self.id} conv={self.conversation_id}>"
