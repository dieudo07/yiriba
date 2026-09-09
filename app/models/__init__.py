"""Yiriba SaaS — All models (imported for SQLAlchemy registration)."""

from app.models.school import School  # noqa: F401
from app.models.permission import Permission, Role, RolePermission  # noqa: F401
from app.models.user import User, UserStatus, UserRole  # noqa: F401
from app.models.student import Student  # noqa: F401
from app.models.enums import StudentStatus, ParentRole  # noqa: F401
from app.models.parent_student import ParentStudent  # noqa: F401
from app.models.cycle import Cycle, Level  # noqa: F401
from app.models.class_ import Class, Subject, ClassSubject, TeacherClass, Enrollment  # noqa: F401
from app.models.grade import Evaluation, Grade  # noqa: F401
from app.models.attendance import Attendance, StatutPresence  # noqa: F401
from app.models import attendance_ext as _attendance_ext  # noqa: F401 — colonnes justification/validation
from app.models.payment import FeeObligation, FeeInstallment, Payment, PaymentStatus  # noqa: F401
from app.models.bulletin import Bulletin  # noqa: F401
from app.models.notification import Notification, NotificationChannel, NotificationCategory, NotificationStatus  # noqa: F401
from app.models.audit import AuditLog  # noqa: F401
from app.models.school_setting import SchoolSetting  # noqa: F401
from app.models.academic_year import AcademicYear, AcademicPeriod  # noqa: F401
from app.models.subscription import SubscriptionPlan, Subscription, SubscriptionStatus  # noqa: F401
from app.models.timetable import Timetable, TimeSlot  # noqa: F401
from app.models.teacher_subject import TeacherSubject  # noqa: F401
from app.models.notification_setting import NotificationSetting  # noqa: F401
from app.models.message import Conversation, ConversationParticipant, Message  # noqa: F401
from app.models.discipline import DisciplinaryRuleSet, DisciplinaryRecord  # noqa: F401
from app.models.platform import PlatformSetting, SubscriptionPayment, SupportRequest  # noqa: F401
