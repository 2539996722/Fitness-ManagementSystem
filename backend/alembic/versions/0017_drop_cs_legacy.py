"""清理 customer_service 遗留数据（M12+ 收尾）。

历史背景：M4 合并后 trainer 兼原 customer_service，DB 字段保留 'customer_service' 字符串
以兼容历史账号。M12 决定彻底清理：
- users.role = 'customer_service'             → 'trainer'
- conversations.conversation_type 同上
- messages.sender_type 同上

ponytail:
- 字段实际是 String(16)，不是 MySQL ENUM，无需 ALTER TABLE；纯 UPDATE。
- 所有转换无副作用：原 CS 账号被升级为 trainer 后，conversations.assigned_trainer_id
  仍指向同一 user.id，会话状态机照常走 trainer_active 分支。
- 跑迁移前强烈建议先备份：
  mysqldump fithub --where="role='customer_service'" > /tmp/cs_users_backup.sql
  mysqldump fithub conversations --where="conversation_type='customer_service'" > /tmp/cs_convs_backup.sql
  mysqldump fithub messages --where="sender_type='customer_service'" > /tmp/cs_msgs_backup.sql
"""
from typing import Union

import sqlalchemy as sa
from alembic import op


revision: str = "0017"
down_revision: Union[str, None] = "0016"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    """把 DB 中残留的 'customer_service' 字符串全部归一为 'trainer'。"""
    # 1. users.role
    op.execute(
        "UPDATE users SET role = 'trainer' WHERE role = 'customer_service'"
    )
    # 2. conversations.conversation_type
    op.execute(
        "UPDATE conversations SET conversation_type = 'trainer' "
        "WHERE conversation_type = 'customer_service'"
    )
    # 3. messages.sender_type
    op.execute(
        "UPDATE messages SET sender_type = 'trainer' "
        "WHERE sender_type = 'customer_service'"
    )


def downgrade() -> None:
    """无原子回滚：需从迁移前 mysqldump 备份恢复。

    为避免误导，这里仅打印警告，不做任何破坏性还原。
    """
    import warnings
    warnings.warn(
        "0017 downgrade is a no-op. 恢复 'customer_service' 字符串需从迁移前 mysqldump 备份恢复。",
        RuntimeWarning,
    )
