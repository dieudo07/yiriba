"""Yiriba SaaS — Messaging service: conversations, messages, permissions."""

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select, func, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.message import Conversation, ConversationParticipant, Message
from app.models.user import User
from app.models.class_ import TeacherClass, Class, Enrollment
from app.models.parent_student import ParentStudent
from app.models.student import Student
from app.services.audit_service import safe_audit


async def get_user_role_type(db: AsyncSession, user_id: int) -> str:
    """Get the role_type of a user."""
    result = await db.execute(select(User.role_type).where(User.id == user_id))
    row = result.scalar_one_or_none()
    return row if row else "unknown"


async def can_user_initiate_conversation(
    db: AsyncSession, school_id: int, sender_id: int, recipient_id: int
) -> tuple[bool, str]:
    """Check if sender can initiate a conversation with recipient.

    Rules:
    - Admin/Secrétaire/Comptable: can message any teacher or parent in the school
    - Teacher: can message ONLY parents of students in their own classes
    - Parent: can message school admin ONLY (not teachers directly)
    """
    sender_role = await get_user_role_type(db, sender_id)
    recipient = (await db.execute(select(User).where(User.id == recipient_id))).scalar_one_or_none()
    if not recipient:
        return False, "Destinataire introuvable"
    if recipient.school_id != school_id:
        return False, "Destinataire hors de cette ecole"
    if recipient.is_active is False:
        return False, "Destinataire inactif"

    # Admin/Secrétaire/Comptable can message any teacher or parent
    if sender_role in ("admin", "directeur", "secretaire", "comptable"):
        if recipient.role_type in ("teacher", "parent", "admin", "directeur", "secretaire", "comptable"):
            return True, ""
        return False, "Ce role ne peut pas recevoir de messages"

    # Teacher: can message ONLY parents of students in their classes
    if sender_role == "teacher":
        if recipient.role_type == "teacher":
            return False, "Un enseignant ne peut pas initier de conversation avec un autre enseignant"
        if recipient.role_type == "parent":
            # Check if this parent has a student in one of the teacher's classes
            teacher_classes = (await db.execute(
                select(TeacherClass.class_id).where(
                    TeacherClass.teacher_id == sender_id,
                    TeacherClass.school_id == school_id,
                )
            )).scalars().all()
            if not teacher_classes:
                return False, "Aucune classe affectee"
            parent_students = (await db.execute(
                select(ParentStudent.student_id).where(ParentStudent.parent_id == recipient_id)
            )).scalars().all()
            if not parent_students:
                return False, "Ce parent n'a pas d'eleve rattache"
            # Check if any of the parent's students are in the teacher's classes
            for student_id in parent_students:
                enrollments = (await db.execute(
                    select(Enrollment.class_id).where(
                        Enrollment.student_id == student_id,
                        Enrollment.class_id.in_(teacher_classes),
                    )
                )).scalars().all()
                if enrollments:
                    return True, ""
            return False, "Cet eleve n'est pas dans vos classes"
        if recipient.role_type in ("admin", "directeur", "secretaire"):
            return True, ""
        return False, "Ce role ne peut pas recevoir de messages"

    # Parent: can message school admin only (not teachers)
    if sender_role == "parent":
        if recipient.role_type == "teacher":
            return False, "Vous ne pouvez pas demarrer une conversation avec un enseignant. L'enseignant doit vous ecrire en premier."
        if recipient.role_type in ("admin", "directeur", "secretaire"):
            return True, ""
        return False, "Ce role ne peut pas recevoir de messages"

    return False, "Role non autorise"


async def can_user_reply_in_conversation(
    db: AsyncSession, school_id: int, user_id: int, conversation_id: int
) -> tuple[bool, str]:
    """Check if user can reply in an existing conversation.

    Parent can only reply if teacher initiated first.
    """
    conv = (await db.execute(
        select(Conversation).where(Conversation.id == conversation_id, Conversation.school_id == school_id)
    )).scalar_one_or_none()
    if not conv:
        return False, "Conversation introuvable"

    # Check user is a participant
    participant = (await db.execute(
        select(ConversationParticipant).where(
            ConversationParticipant.conversation_id == conversation_id,
            ConversationParticipant.user_id == user_id,
        )
    )).scalar_one_or_none()
    if not participant:
        return False, "Vous n'etes pas participant a cette conversation"

    user_role = await get_user_role_type(db, user_id)

    # Parent can only reply if teacher/admin initiated first, or if the parent
    # himself created the conversation (ex. message to school administration)
    if user_role == "parent":
        if conv.created_by == user_id:
            return True, ""
        # Check if the conversation was initiated by a teacher (or admin)
        creator = (await db.execute(
            select(User.role_type).where(User.id == conv.created_by)
        )).scalar_one_or_none()
        if creator in ("teacher", "admin", "directeur", "secretaire"):
            return True, ""
        return False, "Vous ne pouvez pas repondre a cette conversation"

    return True, ""


async def create_conversation(
    db: AsyncSession,
    school_id: int,
    created_by: int,
    recipient_ids: list[int],
    conv_type: str = "direct",
    subject: str | None = None,
) -> Conversation:
    """Create a conversation and add participants."""
    conv = Conversation(
        school_id=school_id,
        type=conv_type,
        subject=subject,
        created_by=created_by,
    )
    db.add(conv)
    await db.flush()

    # Add creator as participant
    db.add(ConversationParticipant(conversation_id=conv.id, user_id=created_by))
    # Add recipients
    for rid in recipient_ids:
        if rid != created_by:
            db.add(ConversationParticipant(conversation_id=conv.id, user_id=rid))

    await db.flush()
    return conv


async def send_message(
    db: AsyncSession,
    school_id: int,
    conversation_id: int,
    sender_id: int,
    content: str,
    attachment_url: str | None = None,
) -> Message:
    """Send a message in a conversation. Creates in-app notifications for other participants."""
    msg = Message(
        conversation_id=conversation_id,
        sender_id=sender_id,
        content=content,
        attachment_url=attachment_url,
    )
    db.add(msg)
    await db.flush()

    # Update last_read_at for sender
    sender_participant = (await db.execute(
        select(ConversationParticipant).where(
            ConversationParticipant.conversation_id == conversation_id,
            ConversationParticipant.user_id == sender_id,
        )
    )).scalar_one_or_none()
    if sender_participant:
        sender_participant.last_read_at = datetime.now(timezone.utc)

    # Create in-app notification for other participants
    from app.models.notification import Notification
    participants = (await db.execute(
        select(ConversationParticipant.user_id).where(
            ConversationParticipant.conversation_id == conversation_id,
            ConversationParticipant.user_id != sender_id,
        )
    )).scalars().all()

    sender = (await db.execute(select(User).where(User.id == sender_id))).scalar_one_or_none()
    sender_name = f"{sender.first_name} {sender.last_name}" if sender else "Un utilisateur"

    for pid in participants:
        notif = Notification(
            school_id=school_id,
            recipient_id=pid,
            channel="in_app",
            category="announcement",
            subject="Nouveau message",
            body=f"{sender_name}: {content[:100]}",
            status="sent",
            is_read=False,
            related_entity_type="message",
            related_entity_id=conversation_id,
        )
        db.add(notif)

    await db.flush()
    return msg


async def mark_conversation_read(db: AsyncSession, conversation_id: int, user_id: int) -> None:
    """Mark a conversation as read for a user."""
    participant = (await db.execute(
        select(ConversationParticipant).where(
            ConversationParticipant.conversation_id == conversation_id,
            ConversationParticipant.user_id == user_id,
        )
    )).scalar_one_or_none()
    if participant:
        participant.last_read_at = datetime.now(timezone.utc)
        await db.flush()


async def get_unread_message_count(db: AsyncSession, school_id: int, user_id: int) -> int:
    """Get count of conversations with unread messages for a user."""
    # Get all conversations where user is participant
    conv_ids = (await db.execute(
        select(ConversationParticipant.conversation_id).where(
            ConversationParticipant.user_id == user_id,
        )
    )).scalars().all()

    if not conv_ids:
        return 0

    count = 0
    for conv_id in conv_ids:
        participant = (await db.execute(
            select(ConversationParticipant).where(
                ConversationParticipant.conversation_id == conv_id,
                ConversationParticipant.user_id == user_id,
            )
        )).scalar_one_or_none()
        if not participant or not participant.last_read_at:
            # Count all messages in this conversation
            msg_count = (await db.execute(
                select(func.count(Message.id)).where(
                    Message.conversation_id == conv_id,
                    Message.sender_id != user_id,
                )
            )).scalar() or 0
            count += msg_count
        else:
            # Count messages after last_read_at
            msg_count = (await db.execute(
                select(func.count(Message.id)).where(
                    Message.conversation_id == conv_id,
                    Message.sender_id != user_id,
                    Message.created_at > participant.last_read_at,
                )
            )).scalar() or 0
            count += msg_count

    return count


async def get_available_recipients(
    db: AsyncSession, school_id: int, sender_id: int
) -> list[dict]:
    """Get list of users the sender can message, filtered by permissions."""
    sender_role = await get_user_role_type(db, sender_id)
    recipients = []

    if sender_role in ("admin", "directeur", "secretaire", "comptable"):
        # Can message any teacher or parent
        result = await db.execute(
            select(User).where(
                User.school_id == school_id,
                User.is_active == True,  # noqa: E712
                User.id != sender_id,
                User.role_type.in_(["teacher", "parent", "admin", "directeur", "secretaire", "comptable"]),
            ).order_by(User.first_name)
        )
        for u in result.scalars().all():
            recipients.append({
                "id": u.id,
                "name": f"{u.first_name} {u.last_name}",
                "role": u.role_type,
                "email": u.email,
            })

    elif sender_role == "teacher":
        # Can message parents of students in their classes + school admin
        teacher_class_ids = (await db.execute(
            select(TeacherClass.class_id).where(
                TeacherClass.teacher_id == sender_id,
                TeacherClass.school_id == school_id,
            )
        )).scalars().all()

        # Parents of students in teacher's classes
        if teacher_class_ids:
            student_ids = (await db.execute(
                select(Enrollment.student_id).where(
                    Enrollment.class_id.in_(teacher_class_ids),
                    Enrollment.school_id == school_id,
                )
            )).scalars().all()
            if student_ids:
                parent_ids = (await db.execute(
                    select(ParentStudent.parent_id).where(
                        ParentStudent.student_id.in_(student_ids),
                    )
                )).scalars().all()
                if parent_ids:
                    parents = (await db.execute(
                        select(User).where(
                            User.id.in_(parent_ids),
                            User.school_id == school_id,
                            User.is_active == True,  # noqa: E712
                        )
                    )).scalars().all()
                    for u in parents:
                        recipients.append({
                            "id": u.id,
                            "name": f"{u.first_name} {u.last_name}",
                            "role": "parent",
                            "email": u.email,
                        })

        # School admin
        admins = (await db.execute(
            select(User).where(
                User.school_id == school_id,
                User.is_active == True,  # noqa: E712
                User.role_type.in_(["admin", "directeur", "secretaire"]),
                User.id != sender_id,
            )
        )).scalars().all()
        for u in admins:
            recipients.append({
                "id": u.id,
                "name": f"{u.first_name} {u.last_name}",
                "role": u.role_type,
                "email": u.email,
            })

    elif sender_role == "parent":
        # Can message school admin only
        admins = (await db.execute(
            select(User).where(
                User.school_id == school_id,
                User.is_active == True,  # noqa: E712
                User.role_type.in_(["admin", "directeur", "secretaire"]),
            )
        )).scalars().all()
        for u in admins:
            recipients.append({
                "id": u.id,
                "name": f"{u.first_name} {u.last_name}",
                "role": u.role_type,
                "email": u.email,
            })

    return recipients
