from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.repositories.transaction_repository import get_transaction
from app.schemas.transaction import TransactionResponse

router = APIRouter(prefix="/transactions", tags=["transactions"])


@router.get("/{transaction_id}", response_model=TransactionResponse)
def get_transaction_status(
    transaction_id: str, db: Annotated[Session, Depends(get_db)]
) -> TransactionResponse:
    transaction = get_transaction(db, transaction_id)
    if transaction is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "transaction_not_found", "transaction_id": transaction_id},
        )
    return TransactionResponse.model_validate(transaction)
