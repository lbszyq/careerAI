"""operation_reviews 数据访问（关键操作审计与二次确认）。"""
import uuid
from datetime import datetime, timezone

from app.models.operation_review import OperationReview
from app.repositories.base import BaseRepository


class OperationReviewRepository(BaseRepository):
    async def create(
        self,
        user_id: uuid.UUID,
        action: str,
        resource_type: str,
        resource_id: str,
        payload: dict,
        status: str,
    ) -> OperationReview:
        row = OperationReview(
            user_id=user_id, action=action, resource_type=resource_type,
            resource_id=resource_id, payload=payload, status=status,
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def get(self, review_id: uuid.UUID) -> OperationReview | None:
        return await self.session.get(OperationReview, review_id)

    async def decide(self, review: OperationReview, status: str) -> None:
        """确认终态落库：approved / rejected，记录 decided_at。"""
        review.status = status
        review.decided_at = datetime.now(timezone.utc)
        await self.session.flush()
