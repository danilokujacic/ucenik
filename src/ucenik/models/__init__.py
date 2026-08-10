"""Single source of truth for the full set of Beanie document models -
`init_db()` needs every one of them registered up front. Three separate
places need this exact list (`main.py`'s app lifespan, `workers/celery_app.py`'s
worker startup, `tests/conftest.py`'s test db) - keeping it here means adding
a new model is one line, not three easy-to-forget-one-of ones.
"""

from ucenik.models.auth_sessions import AuthSession
from ucenik.models.chat_messages import ChatMessage
from ucenik.models.chat_sessions import ChatSession
from ucenik.models.documents import Document
from ucenik.models.enrollments import Enrollment
from ucenik.models.item import Item
from ucenik.models.lecture_versions import LectureVersion
from ucenik.models.lectures import Lecture
from ucenik.models.plans import Plan
from ucenik.models.subjects import Subject
from ucenik.models.users import User

ALL_DOCUMENT_MODELS = [
    Item,
    User,
    AuthSession,
    Subject,
    Enrollment,
    Document,
    ChatSession,
    ChatMessage,
    Plan,
    Lecture,
    LectureVersion,
]
