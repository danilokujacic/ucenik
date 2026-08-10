from beanie import Document, init_beanie
from pymongo import AsyncMongoClient

from ucenik.core.config import settings

mongodb_client: AsyncMongoClient | None = None


async def init_db(document_models: list[type[Document]]) -> None:
    global mongodb_client
    mongodb_client = AsyncMongoClient(settings.mongodb_url)
    await init_beanie(database=mongodb_client[settings.mongodb_db_name], document_models=document_models)


async def close_db() -> None:
    if mongodb_client is not None:
        await mongodb_client.close()
