"""
MongoDB Session Service for Google ADK
=======================================

Custom implementation of ADK's BaseSessionService using MongoDB.
Provides persistent session storage with full async support.

Features:
- Persistent sessions across restarts
- Async MongoDB operations (motor)
- Session state management
- Event/message history storage
- User-scoped session listing

Usage:
    from core.mongodb_session import MongoDBSessionService

    session_service = MongoDBSessionService(
        mongo_uri="mongodb://localhost:27017",
        database="ai_agents"
    )
"""

import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Check if motor (async MongoDB) is available
try:
    from motor.motor_asyncio import AsyncIOMotorClient

    HAS_MOTOR = True
except ImportError:
    HAS_MOTOR = False
    logger.warning("motor not installed. Run: pip install motor")

# Check if ADK is available for type hints
try:
    from google.adk.events import Event
    from google.adk.sessions import BaseSessionService, Session

    HAS_ADK = True
except ImportError:
    HAS_ADK = False
    BaseSessionService = object  # Fallback to object if ADK not available

    # Define minimal Session class for standalone use
    @dataclass
    class Session:
        id: str
        app_name: str
        user_id: str
        state: Dict[str, Any] = field(default_factory=dict)
        events: List[Any] = field(default_factory=list)
        last_update_time: float = field(default_factory=lambda: datetime.now().timestamp())


@dataclass
class SessionDocument:
    """MongoDB document structure for sessions."""

    session_id: str
    app_name: str
    user_id: str
    state: Dict[str, Any]
    events: List[Dict[str, Any]]
    created_at: datetime
    updated_at: datetime

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "app_name": self.app_name,
            "user_id": self.user_id,
            "state": self.state,
            "events": self.events,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SessionDocument":
        return cls(
            session_id=data.get("session_id", ""),
            app_name=data.get("app_name", ""),
            user_id=data.get("user_id", ""),
            state=data.get("state", {}),
            events=data.get("events", []),
            created_at=data.get("created_at", datetime.now()),
            updated_at=data.get("updated_at", datetime.now()),
        )


class MongoDBSessionService(BaseSessionService):
    """
    MongoDB-backed session service for Google ADK.

    Inherits from BaseSessionService to be compatible with ADK's Runner.
    Implements persistent MongoDB storage.

    Args:
        mongo_uri: MongoDB connection string
        database: Database name (default: "adk_sessions")
        collection: Collection name (default: "sessions")
    """

    def __init__(self, mongo_uri: str = None, database: str = "ai_agents", collection: str = "sessions"):
        if not HAS_MOTOR:
            raise ImportError("motor is required for MongoDB sessions. Run: pip install motor")

        # Get URI from param or environment
        self.mongo_uri = mongo_uri or os.environ.get("MONGODB_URI", "mongodb://localhost:27017")
        self.database_name = database
        self.collection_name = collection

        # Initialize async client
        self._client: Optional[AsyncIOMotorClient] = None
        self._db = None
        self._collection = None

        logger.info("MongoDBSessionService initialized for database: %s", database)

    async def _ensure_connected(self):
        """Ensure MongoDB connection is established."""
        if self._client is None:
            self._client = AsyncIOMotorClient(self.mongo_uri)
            self._db = self._client[self.database_name]
            self._collection = self._db[self.collection_name]

            # Create indexes for efficient queries
            await self._collection.create_index("session_id", unique=True)
            await self._collection.create_index([("app_name", 1), ("user_id", 1)])
            await self._collection.create_index("updated_at")

            logger.info("MongoDB connection established with indexes")

    async def create_session(
        self,
        app_name: str,
        user_id: str,
        session_id: str = None,
        state: Dict[str, Any] = None,
    ) -> Session:
        """
        Create a new session in MongoDB.

        Args:
            app_name: Application name
            user_id: User identifier
            session_id: Optional session ID (generated if not provided)
            state: Initial state dictionary

        Returns:
            Created Session object
        """
        await self._ensure_connected()

        if session_id is None:
            session_id = f"session-{datetime.now().strftime('%Y%m%d-%H%M%S-%f')}"

        now = datetime.now()

        doc = SessionDocument(
            session_id=session_id,
            app_name=app_name,
            user_id=user_id,
            state=state or {},
            events=[],
            created_at=now,
            updated_at=now,
        )

        await self._collection.insert_one(doc.to_dict())
        logger.debug("Created session: {session_id} for user: %s", user_id)

        return self._doc_to_session(doc)

    async def get_session(
        self,
        app_name: str,
        user_id: str,
        session_id: str,
    ) -> Optional[Session]:
        """
        Retrieve a session from MongoDB.

        Args:
            app_name: Application name
            user_id: User identifier
            session_id: Session ID to retrieve

        Returns:
            Session object or None if not found
        """
        await self._ensure_connected()

        doc_data = await self._collection.find_one(
            {
                "session_id": session_id,
                "app_name": app_name,
                "user_id": user_id,
            }
        )

        if doc_data:
            doc = SessionDocument.from_dict(doc_data)
            return self._doc_to_session(doc)

        return None

    async def list_sessions(
        self,
        app_name: str,
        user_id: str,
        limit: int = 20,
    ) -> List[Session]:
        """
        List sessions for a user.

        Args:
            app_name: Application name
            user_id: User identifier
            limit: Maximum number of sessions to return

        Returns:
            List of Session objects, newest first
        """
        await self._ensure_connected()

        cursor = (
            self._collection.find(
                {
                    "app_name": app_name,
                    "user_id": user_id,
                }
            )
            .sort("updated_at", -1)
            .limit(limit)
        )

        sessions = []
        async for doc_data in cursor:
            doc = SessionDocument.from_dict(doc_data)
            sessions.append(self._doc_to_session(doc))

        return sessions

    async def update_session(
        self,
        session: Session,
    ) -> Session:
        """
        Update an existing session in MongoDB.

        Args:
            session: Session object with updated state/events

        Returns:
            Updated Session object
        """
        await self._ensure_connected()

        # Convert events to serializable format
        events_data = []
        for event in session.events or []:
            if hasattr(event, "to_dict"):
                events_data.append(event.to_dict())
            elif isinstance(event, dict):
                events_data.append(event)
            else:
                events_data.append({"data": str(event)})

        await self._collection.update_one(
            {"session_id": session.id},
            {
                "$set": {
                    "state": session.state,
                    "events": events_data,
                    "updated_at": datetime.now(),
                }
            },
        )

        logger.debug("Updated session: %s", session.id)
        return session

    async def delete_session(
        self,
        app_name: str,
        user_id: str,
        session_id: str,
    ) -> bool:
        """
        Delete a session from MongoDB.

        Args:
            app_name: Application name
            user_id: User identifier
            session_id: Session ID to delete

        Returns:
            True if deleted, False if not found
        """
        await self._ensure_connected()

        result = await self._collection.delete_one(
            {
                "session_id": session_id,
                "app_name": app_name,
                "user_id": user_id,
            }
        )

        deleted = result.deleted_count > 0
        if deleted:
            logger.debug("Deleted session: %s", session_id)

        return deleted

    async def append_event(
        self,
        session: Session,
        event: Any,
    ) -> Session:
        """
        Append an event to a session.

        Args:
            session: Session to update
            event: Event to append

        Returns:
            Updated Session object
        """
        await self._ensure_connected()

        # Convert event to serializable format
        if hasattr(event, "to_dict"):
            event_data = event.to_dict()
        elif isinstance(event, dict):
            event_data = event
        else:
            event_data = {"data": str(event), "timestamp": datetime.now().isoformat()}

        await self._collection.update_one(
            {"session_id": session.id}, {"$push": {"events": event_data}, "$set": {"updated_at": datetime.now()}}
        )

        session.events.append(event)
        return session

    def _doc_to_session(self, doc: SessionDocument) -> Session:
        """Convert MongoDB document to ADK Session object."""
        if HAS_ADK:
            # Use ADK's Session class
            session = Session(
                id=doc.session_id,
                app_name=doc.app_name,
                user_id=doc.user_id,
            )
            session.state = doc.state
            session.events = doc.events  # Events are stored as dicts
            if hasattr(session, "last_update_time"):
                session.last_update_time = doc.updated_at.timestamp()
            return session
        else:
            # Use our dataclass
            return Session(
                id=doc.session_id,
                app_name=doc.app_name,
                user_id=doc.user_id,
                state=doc.state,
                events=doc.events,
                last_update_time=doc.updated_at.timestamp(),
            )

    async def close(self):
        """Close MongoDB connection."""
        if self._client:
            self._client.close()
            self._client = None
            logger.info("MongoDB connection closed")


# ============================================================================
# Chat History Service (for Streamlit UI)
# ============================================================================


class MongoDBChatHistory:
    """
    MongoDB-backed chat history for Streamlit UI.

    Separate from ADK sessions - this stores the UI message history.
    """

    def __init__(self, mongo_uri: str = None, database: str = "ai_agents", collection: str = "chat_history"):
        if not HAS_MOTOR:
            raise ImportError("motor is required. Run: pip install motor")

        self.mongo_uri = mongo_uri or os.environ.get("MONGODB_URI", "mongodb://localhost:27017")
        self.database_name = database
        self.collection_name = collection
        self._client = None
        self._collection = None

    async def _ensure_connected(self):
        if self._client is None:
            self._client = AsyncIOMotorClient(self.mongo_uri)
            self._collection = self._client[self.database_name][self.collection_name]
            await self._collection.create_index("session_id", unique=True)
            await self._collection.create_index("updated_at")

    async def save_chat(
        self,
        session_id: str,
        messages: List[Dict],
        release: str = None,
    ):
        """Save chat messages."""
        await self._ensure_connected()

        now = datetime.now()
        await self._collection.update_one(
            {"session_id": session_id},
            {
                "$set": {
                    "messages": messages,
                    "release": release,
                    "updated_at": now,
                },
                "$setOnInsert": {
                    "created_at": now,
                },
            },
            upsert=True,
        )

    async def load_chat(self, session_id: str) -> Optional[Dict]:
        """Load chat by session ID."""
        await self._ensure_connected()
        return await self._collection.find_one({"session_id": session_id})

    async def list_chats(self, limit: int = 10) -> List[Dict]:
        """List recent chats."""
        await self._ensure_connected()

        cursor = self._collection.find().sort("updated_at", -1).limit(limit)
        return [doc async for doc in cursor]

    async def delete_chat(self, session_id: str) -> bool:
        """Delete a chat."""
        await self._ensure_connected()
        result = await self._collection.delete_one({"session_id": session_id})
        return result.deleted_count > 0


# ============================================================================
# Synchronous Wrappers (for Streamlit which may not be fully async)
# ============================================================================

import asyncio
import threading

# Dedicated event loop for MongoDB operations
_mongo_loop = None
_mongo_thread = None
_mongo_lock = threading.Lock()


def _start_mongo_loop(loop):
    """Run MongoDB event loop in dedicated thread."""
    asyncio.set_event_loop(loop)
    loop.run_forever()


def _run_async(coro):
    """Run async coroutine using dedicated MongoDB event loop thread."""
    global _mongo_loop, _mongo_thread

    with _mongo_lock:
        if _mongo_loop is None or _mongo_loop.is_closed():
            _mongo_loop = asyncio.new_event_loop()
            _mongo_thread = threading.Thread(target=_start_mongo_loop, args=(_mongo_loop,), daemon=True)
            _mongo_thread.start()

    future = asyncio.run_coroutine_threadsafe(coro, _mongo_loop)
    return future.result(timeout=30)


class SyncMongoDBChatHistory:
    """Synchronous wrapper for MongoDB chat history."""

    def __init__(self, **kwargs):
        self._async_service = MongoDBChatHistory(**kwargs)

    def save_chat(self, session_id: str, messages: List[Dict], release: str = None):
        return _run_async(self._async_service.save_chat(session_id, messages, release))

    def load_chat(self, session_id: str) -> Optional[Dict]:
        return _run_async(self._async_service.load_chat(session_id))

    def list_chats(self, limit: int = 10) -> List[Dict]:
        return _run_async(self._async_service.list_chats(limit))

    def delete_chat(self, session_id: str) -> bool:
        return _run_async(self._async_service.delete_chat(session_id))


# ============================================================================
# Factory function
# ============================================================================


def get_mongodb_session_service(
    mongo_uri: str = None,
    database: str = "ai_agents",
) -> MongoDBSessionService:
    """
    Get MongoDB session service instance.

    Args:
        mongo_uri: MongoDB URI (default: from MONGODB_URI env var)
        database: Database name

    Returns:
        MongoDBSessionService instance
    """
    return MongoDBSessionService(mongo_uri=mongo_uri, database=database, collection="sessions")


def get_mongodb_chat_history(
    mongo_uri: str = None,
    database: str = "ai_agents",
    sync: bool = True,
) -> Any:
    """
    Get MongoDB chat history service.

    Args:
        mongo_uri: MongoDB URI
        database: Database name
        sync: If True, return sync wrapper

    Returns:
        Chat history service instance
    """
    if sync:
        return SyncMongoDBChatHistory(mongo_uri=mongo_uri, database=database)
    return MongoDBChatHistory(mongo_uri=mongo_uri, database=database)
