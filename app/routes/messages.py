"""Yiriba SaaS — Messaging routes: conversations, messages, unread counts."""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.middleware.rbac import get_current_user, get_school_id, require_permission
from app.models.message import Conversation, ConversationParticipant, Message
from app.models.user import User
from app.services import message_service
from app.services.audit_service import safe_audit

router = APIRouter(prefix="/api/messages", tags=["messages"])


# --- Schemas ---
class ConversationCreate(BaseModel):
    recipient_id: int
    subject: str | None = None
    content: str


class MessageSend(BaseModel):
    content: str
    attachment_url: str | None = None


class BroadcastCreate(BaseModel):
    subject: str
    content: str
    target: str  # "all_parents", "all_teachers", "class_parents:{class_id}"


# --- Endpoints ---

@router.get("/unread-count")
async def unread_message_count(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    school_id = get_school_id(user)
    count = await message_service.get_unread_message_count(db, school_id, user.id)
    return {"unread_count": count}


@router.get("/recipients")
async def list_recipients(
    user: User = Depends(require_permission("message.read")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    school_id = get_school_id(user)
    recipients = await message_service.get_available_recipients(db, school_id, user.id)
    return {"recipients": recipients}


@router.get("/conversations")
async def list_conversations(
    user: User = Depends(require_permission("message.read")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    school_id = get_school_id(user)

    # Get conversations where user is participant
    conv_ids = (await db.execute(
        select(ConversationParticipant.conversation_id).where(
            ConversationParticipant.user_id == user.id,
        )
    )).scalars().all()

    if not conv_ids:
        return {"conversations": []}

    result = await db.execute(
        select(Conversation).where(
            Conversation.id.in_(conv_ids),
            Conversation.is_archived == False,  # noqa: E712
        ).order_by(Conversation.created_at.desc())
    )
    conversations = result.scalars().all()

    conv_list = []
    for conv in conversations:
        # Get other participants
        participants_q = await db.execute(
            select(ConversationParticipant).where(
                ConversationParticipant.conversation_id == conv.id,
            )
        )
        participants = participants_q.scalars().all()

        other_users = []
        for p in participants:
            if p.user_id != user.id:
                u = (await db.execute(select(User).where(User.id == p.user_id))).scalar_one_or_none()
                if u:
                    other_users.append({"id": u.id, "name": f"{u.first_name} {u.last_name}", "role": u.role_type})

        # Get last message
        last_msg = (await db.execute(
            select(Message).where(Message.conversation_id == conv.id).order_by(Message.created_at.desc()).limit(1)
        )).scalar_one_or_none()

        # Count unread
        user_participant = (await db.execute(
            select(ConversationParticipant).where(
                ConversationParticipant.conversation_id == conv.id,
                ConversationParticipant.user_id == user.id,
            )
        )).scalar_one_or_none()

        unread = 0
        if user_participant and user_participant.last_read_at:
            unread = (await db.execute(
                select(func.count(Message.id)).where(
                    Message.conversation_id == conv.id,
                    Message.sender_id != user.id,
                    Message.created_at > user_participant.last_read_at,
                )
            )).scalar() or 0
        elif not user_participant or not user_participant.last_read_at:
            unread = (await db.execute(
                select(func.count(Message.id)).where(
                    Message.conversation_id == conv.id,
                    Message.sender_id != user.id,
                )
            )).scalar() or 0

        conv_list.append({
            "id": conv.id,
            "type": conv.type,
            "subject": conv.subject,
            "participants": other_users,
            "last_message": {
                "content": last_msg.content[:100] if last_msg else "",
                "sender_id": last_msg.sender_id if last_msg else None,
                "created_at": last_msg.created_at.isoformat() if last_msg else conv.created_at.isoformat(),
            } if last_msg else None,
            "unread_count": unread,
            "created_at": conv.created_at.isoformat(),
        })

    return {"conversations": conv_list}


@router.post("/conversations", status_code=201)
async def create_conversation(
    data: ConversationCreate,
    user: User = Depends(require_permission("message.send")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    school_id = get_school_id(user)

    # Permission check
    can, reason = await message_service.can_user_initiate_conversation(
        db, school_id, user.id, data.recipient_id
    )
    if not can:
        raise HTTPException(status_code=403, detail=reason)

    # Check for existing direct conversation
    existing = await db.execute(
        select(ConversationParticipant.conversation_id).where(
            ConversationParticipant.user_id == user.id,
        )
    )
    my_conv_ids = existing.scalars().all()

    if my_conv_ids:
        existing_conv = (await db.execute(
            select(Conversation).where(
                Conversation.id.in_(my_conv_ids),
                Conversation.type == "direct",
            )
        )).scalars().all()

        for conv in existing_conv:
            participants = (await db.execute(
                select(ConversationParticipant.user_id).where(
                    ConversationParticipant.conversation_id == conv.id,
                )
            )).scalars().all()
            if set(participants) == {user.id, data.recipient_id}:
                # Existing conversation found — send message there instead
                msg = await message_service.send_message(
                    db, school_id, conv.id, user.id, data.content
                )
                await db.commit()
                return {"conversation_id": conv.id, "message_id": msg.id, "existing": True}

    # Create new conversation
    conv = await message_service.create_conversation(
        db, school_id, user.id, [data.recipient_id], subject=data.subject
    )
    msg = await message_service.send_message(db, school_id, conv.id, user.id, data.content)

    await safe_audit(db, school_id=school_id, user_id=user.id,
                     action="message.create", resource="conversation", resource_id=conv.id)
    await db.commit()
    return {"conversation_id": conv.id, "message_id": msg.id, "existing": False}


@router.get("/conversations/{conv_id}")
async def get_conversation_messages(
    conv_id: int,
    after: int | None = None,
    user: User = Depends(require_permission("message.read")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    school_id = get_school_id(user)

    # Verify user is participant
    can, reason = await message_service.can_user_reply_in_conversation(db, school_id, user.id, conv_id)
    if not can:
        raise HTTPException(status_code=403, detail=reason)

    # Get messages
    query = select(Message).where(Message.conversation_id == conv_id)
    if after:
        query = query.where(Message.id > after)
    query = query.order_by(Message.created_at.asc()).limit(100)

    result = await db.execute(query)
    messages = result.scalars().all()

    msg_list = []
    for m in messages:
        sender = (await db.execute(select(User).where(User.id == m.sender_id))).scalar_one_or_none()
        msg_list.append({
            "id": m.id,
            "sender_id": m.sender_id,
            "sender_name": f"{sender.first_name} {sender.last_name}" if sender else "Inconnu",
            "content": m.content,
            "attachment_url": m.attachment_url,
            "created_at": m.created_at.isoformat(),
        })

    # Mark as read
    await message_service.mark_conversation_read(db, conv_id, user.id)
    await db.commit()

    conv = (await db.execute(
        select(Conversation).where(Conversation.id == conv_id)
    )).scalar_one_or_none()

    return {
        "messages": msg_list,
        "subject": conv.subject if conv else None,
        "type": conv.type if conv else None,
        "created_at": conv.created_at.isoformat() if conv and conv.created_at else None,
    }


@router.post("/conversations/{conv_id}/messages", status_code=201)
async def send_message_in_conversation(
    conv_id: int,
    data: MessageSend,
    user: User = Depends(require_permission("message.send")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    school_id = get_school_id(user)

    can, reason = await message_service.can_user_reply_in_conversation(db, school_id, user.id, conv_id)
    if not can:
        raise HTTPException(status_code=403, detail=reason)

    msg = await message_service.send_message(
        db, school_id, conv_id, user.id, data.content, data.attachment_url
    )
    await db.commit()
    return {"message_id": msg.id}


@router.post("/broadcast", status_code=201)
async def create_broadcast(
    data: BroadcastCreate,
    user: User = Depends(require_permission("message.send")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Create a broadcast conversation to multiple recipients."""
    school_id = get_school_id(user)
    user_role = await message_service.get_user_role_type(db, user.id)

    if user_role not in ("admin", "directeur", "secretaire"):
        raise HTTPException(status_code=403, detail="Seuls les administrateurs peuvent diffuser")

    # Determine recipients based on target
    from app.models.class_ import TeacherClass, Class, Enrollment
    from app.models.parent_student import ParentStudent

    recipient_ids = set()

    if data.target == "all_parents":
        parents = (await db.execute(
            select(User).where(
                User.school_id == school_id,
                User.role_type == "parent",
                User.is_active == True,  # noqa: E712
            )
        )).scalars().all()
        recipient_ids = {p.id for p in parents}

    elif data.target == "all_teachers":
        teachers = (await db.execute(
            select(User).where(
                User.school_id == school_id,
                User.role_type == "teacher",
                User.is_active == True,  # noqa: E712
            )
        )).scalars().all()
        recipient_ids = {t.id for t in teachers}

    elif data.target.startswith("class_parents:"):
        class_id = int(data.target.split(":")[1])
        student_ids = (await db.execute(
            select(Enrollment.student_id).where(
                Enrollment.class_id == class_id,
                Enrollment.school_id == school_id,
            )
        )).scalars().all()
        if student_ids:
            parent_ids = (await db.execute(
                select(ParentStudent.parent_id).where(
                    ParentStudent.student_id.in_(student_ids),
                )
            )).scalars().all()
            recipient_ids = set(parent_ids)

    if not recipient_ids:
        raise HTTPException(status_code=400, detail="Aucun destinataire trouve")

    # Create broadcast conversation
    conv = await message_service.create_conversation(
        db, school_id, user.id, list(recipient_ids),
        conv_type="broadcast", subject=data.subject,
    )
    msg = await message_service.send_message(db, school_id, conv.id, user.id, data.content)

    await safe_audit(db, school_id=school_id, user_id=user.id,
                     action="message.broadcast", resource="conversation", resource_id=conv.id)
    await db.commit()
    return {"conversation_id": conv.id, "message_id": msg.id, "recipients_count": len(recipient_ids)}
