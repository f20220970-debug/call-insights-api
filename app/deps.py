"""Database and Redis clients, created once per process and overridable in tests."""
from motor.motor_asyncio import AsyncIOMotorClient
from redis.asyncio import Redis

from .config import settings

_state = {}


def get_db():
    if "db" not in _state:
        _state["db"] = AsyncIOMotorClient(settings.mongo_url)[settings.mongo_db]
    return _state["db"]


def get_redis():
    if "redis" not in _state:
        _state["redis"] = Redis.from_url(settings.redis_url)
    return _state["redis"]


def override(db=None, redis=None):
    if db is not None:
        _state["db"] = db
    if redis is not None:
        _state["redis"] = redis
