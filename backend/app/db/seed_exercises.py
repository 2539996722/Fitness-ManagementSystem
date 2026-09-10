"""从数据集导入 1,324 个动作到数据库。

数据源：
- ./data/exercises-dataset-zh/data/exercises.json
- ./data/exercises-dataset-zh/data/name_zh.json

执行方式：
    python -m app.db.seed_exercises

特性：
- 幂等（重复执行安全）
- 批量插入（每批 500 条）
- 进度提示
- 错误跳过单条，不中断整体
"""

import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from loguru import logger
from sqlalchemy import select

from app.core.config import settings
from app.db.models import Exercise
from app.db.session import async_session

BATCH_SIZE = 500


async def load_json_files() -> tuple[list[dict], dict[str, str]]:
    """读取数据集 JSON 文件。

    路径解析顺序：
    1. 环境变量 EXERCISES_DATA_DIR（绝对路径优先）
    2. settings.exercises_data_dir（默认 ./data/exercises-dataset-zh，相对 cwd）
    3. 项目根的 data/exercises-dataset-zh（自动 fallback）
    """
    # 项目根：backend/app/db/seed_exercises.py → 3 层向上
    project_root = Path(__file__).resolve().parents[3]

    # 候选路径
    candidates = []
    if settings.exercises_path:
        candidates.append(settings.exercises_path / "data")
    candidates.append(project_root / "data" / "exercises-dataset-zh" / "data")

    # 用第一个存在的
    data_dir = None
    for cand in candidates:
        if cand.exists():
            data_dir = cand
            break

    if data_dir is None:
        logger.error("❌ 数据集文件不存在，尝试过的路径：")
        for c in candidates:
            logger.error("   - {}", c)
        logger.error("请下载数据集到项目根的 data/exercises-dataset-zh/ 目录")
        sys.exit(1)

    exercises_file = data_dir / "exercises.json"
    name_zh_file = data_dir / "name_zh.json"

    logger.info("📖 读取 {} ...", exercises_file)
    with open(exercises_file, "r", encoding="utf-8") as f:
        exercises = json.load(f)
    logger.info("✅ 读取到 {} 条动作", len(exercises))

    name_zh = {}
    if name_zh_file.exists():
        with open(name_zh_file, "r", encoding="utf-8") as f:
            name_zh = json.load(f)
        logger.info("✅ 读取到 {} 个中文名映射", len(name_zh))
    else:
        logger.warning("⚠️ 未找到 {}，将跳过中文名导入", name_zh_file)

    return exercises, name_zh


def to_exercise_model(record: dict, name_zh_map: dict[str, str]) -> Exercise:
    """数据集记录 → Exercise ORM 模型。"""
    en_name = record.get("name", "").strip()
    zh_name = name_zh_map.get(en_name)

    # 时间解析（ISO 8601 → datetime）
    created_at_str = record.get("created_at", "")
    created_at = None
    if created_at_str:
        try:
            created_at = datetime.fromisoformat(created_at_str.replace("Z", "+00:00")).replace(tzinfo=None)
        except ValueError:
            created_at = datetime.utcnow()

    # 图片路径转换：images/0001.jpg → /static/images/0001.jpg
    image = record.get("image", "")
    gif_url = record.get("gif_url", "")
    if image:
        image = image.replace("images/", "/static/images/")
    if gif_url:
        gif_url = gif_url.replace("videos/", "/static/videos/")

    return Exercise(
        id=record["id"],
        name_en=en_name,
        name_zh=zh_name,
        category=record.get("category", ""),
        body_part=record.get("body_part", ""),
        equipment=record.get("equipment", ""),
        target=record.get("target", ""),
        secondary_muscles=record.get("secondary_muscles", []),
        instructions=record.get("instructions", {}),
        image=image,
        gif_url=gif_url,
       attribution=record.get("attribution"),
       created_at=created_at or datetime.now(timezone.utc).replace(tzinfo=None),
   )


async def seed() -> None:
    """主流程：读取 → 转换 → 批量 upsert → 完成。"""
    start = datetime.now(timezone.utc).replace(tzinfo=None)

    exercises_data, name_zh_map = await load_json_files()

    logger.info("🚀 开始导入到数据库...")
    inserted = 0
    updated = 0
    skipped = 0

    async with async_session() as session:
        # 已有 ID 集合（用于判断 update / insert）
        existing_ids = set(
            (await session.execute(select(Exercise.id))).scalars().all()
        )
        logger.info("📊 数据库已有 {} 条记录", len(existing_ids))

        for i in range(0, len(exercises_data), BATCH_SIZE):
            batch = exercises_data[i : i + BATCH_SIZE]
            batch_models = []
            for record in batch:
                try:
                    if not record.get("id") or not record.get("name"):
                        skipped += 1
                        continue
                    batch_models.append(to_exercise_model(record, name_zh_map))
                except Exception as e:
                    logger.warning("跳过异常记录 id={}: {}", record.get("id"), e)
                    skipped += 1

            # 批量 upsert（MySQL ON DUPLICATE KEY UPDATE）
            for model in batch_models:
                if model.id in existing_ids:
                    updated += 1
                else:
                    inserted += 1
                session.add(model)

            try:
                await session.commit()
            except Exception as e:
                await session.rollback()
                logger.error("批量提交失败，跳过该批：{}", e)
                continue

            progress = min(i + BATCH_SIZE, len(exercises_data))
            logger.info(
                "  进度：{}/{} ({:.1f}%) | 新增 {} | 更新 {} | 跳过 {}",
                progress,
                len(exercises_data),
                progress / len(exercises_data) * 100,
                inserted,
                updated,
                skipped,
            )

    elapsed = (datetime.now(timezone.utc).replace(tzinfo=None) - start).total_seconds()
    logger.info(
        "🎉 导入完成！新增 {} 条 | 更新 {} 条 | 跳过 {} 条 | 耗时 {:.1f}s",
        inserted,
        updated,
        skipped,
        elapsed,
    )


if __name__ == "__main__":
    asyncio.run(seed())
