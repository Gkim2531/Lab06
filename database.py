from collections.abc import Iterator

import pymysql
from pymysql.cursors import DictCursor

from . import config


def get_db() -> Iterator[pymysql.connections.Connection]:
    """FastAPI 依赖：每个请求一个数据库连接，结束后关闭。"""
    conn = pymysql.connect(
        host=config.MYSQL_HOST,
        port=config.MYSQL_PORT,
        user=config.MYSQL_USER,
        password=config.MYSQL_PASSWORD,
        database=config.MYSQL_DATABASE,
        charset="utf8mb4",
        cursorclass=DictCursor,
        autocommit=False,
    )
    try:
        yield conn
    finally:
        conn.close()
