"""为现有用户保存本地 BGE 动态配置，使运行中的后端立即生效。"""

from __future__ import annotations

import asyncio

from sqlalchemy import select

from backend.database import AsyncSessionLocal, engine
from backend.models.llm_config import UserLlmConfig
from backend.models.user import User


async def main() -> None:
    async with AsyncSessionLocal() as db:
        user_ids = list((await db.execute(select(User.id))).scalars().all())
        existing = {
            item.user_id: item
            for item in (
                await db.execute(
                    select(UserLlmConfig).where(UserLlmConfig.config_type == "embedding")
                )
            )
            .scalars()
            .all()
        }
        created = 0
        for user_id in user_ids:
            config = existing.get(user_id)
            if config is None:
                config = UserLlmConfig(user_id=user_id, config_type="embedding")
                db.add(config)
                created += 1
            config.provider = "bge"
            config.model_name = "BAAI/bge-large-zh-v1.5"
            config.api_base = "http://127.0.0.1:8080"
            config.api_key_encrypted = ""
            config.dimension = 1024
            config.is_active = 1
        await db.commit()
        print(f"local_bge_user_configs={len(user_ids)} created={created}")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
