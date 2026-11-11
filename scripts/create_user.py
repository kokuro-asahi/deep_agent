"""Create a login account using the project's PostgreSQL settings."""

import argparse
import sys
from getpass import getpass

from psycopg import OperationalError
from psycopg.errors import UniqueViolation
from pydantic import ValidationError

from app.business_store import business_store
from app.schemas import AccountCreate


def main() -> None:
    parser = argparse.ArgumentParser(description="创建一个可登录 Agent 工作区的普通账号。")
    parser.add_argument("username", help="登录用户名")
    args = parser.parse_args()

    if not sys.stdin.isatty():
        parser.error("请在交互式终端运行，以便隐藏输入的密码。")

    try:
        password = getpass("密码：")
        confirmation = getpass("确认密码：")
    except (EOFError, KeyboardInterrupt):
        parser.exit(1, "\n已取消创建账号。\n")
    if password != confirmation:
        parser.error("两次输入的密码不一致。")

    try:
        account = AccountCreate(username=args.username.strip(), password=password)
    except ValidationError:
        parser.error("请输入 1 到 100 个字符的用户名和 1 到 1024 个字符的密码。")

    values = account.model_dump(exclude={"password"})
    values["password"] = account.password.get_secret_value()
    try:
        created = business_store.create_account(values)
    except UniqueViolation:
        parser.exit(1, "该用户名已存在，请使用其他用户名。\n")
    except OperationalError:
        parser.exit(1, "无法连接 PostgreSQL，请检查数据库服务和项目的 PG_* 配置。\n")
    finally:
        business_store.stop()

    print(f"已创建账号 {created['username']}，可以使用刚设置的密码登录。")


if __name__ == "__main__":
    main()
