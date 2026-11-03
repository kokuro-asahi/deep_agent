from fastapi import APIRouter, Depends, Query, Response
from psycopg.errors import UniqueViolation
from starlette.concurrency import run_in_threadpool

from app.auth import auth_error, get_admin_user
from app.business_store import business_store
from app.schemas import AccountCreate, AccountUpdate, CurrentUser, ManagedUser, ManagedUserList


router = APIRouter(prefix="/v1/admin/users", tags=["account-management"])


@router.get("", response_model=ManagedUserList)
async def accounts(
    response: Response,
    q: str = Query(default="", max_length=100),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    admin: CurrentUser = Depends(get_admin_user),
):
    response.headers["Cache-Control"] = "no-store"
    return await run_in_threadpool(business_store.list_accounts, q.strip(), limit, offset)


@router.post("", response_model=ManagedUser, status_code=201)
async def create_account(body: AccountCreate, response: Response, admin: CurrentUser = Depends(get_admin_user)):
    values = body.model_dump()
    values["password"] = body.password.get_secret_value()
    try:
        row = await run_in_threadpool(business_store.create_account, values)
    except UniqueViolation:
        raise auth_error(409, "USERNAME_TAKEN", "该账号已存在，请使用其他账号") from None
    response.headers["Cache-Control"] = "no-store"
    return row


@router.patch("/{user_id}", response_model=ManagedUser)
async def update_account(user_id: str, body: AccountUpdate, response: Response, admin: CurrentUser = Depends(get_admin_user)):
    values = body.model_dump(exclude_unset=True)
    if body.password is not None:
        values["password"] = body.password.get_secret_value()
    try:
        row = await run_in_threadpool(business_store.update_account, user_id, admin.user_id, values)
    except UniqueViolation:
        raise auth_error(409, "USERNAME_TAKEN", "该账号已存在，请使用其他账号") from None
    if row is None:
        raise auth_error(404, "ACCOUNT_NOT_FOUND", "账号不存在")
    response.headers["Cache-Control"] = "no-store"
    return row
