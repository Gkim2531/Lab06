"""健康检查路由：GET /health 检查数据库连接。"""

import pymysql
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pymysql.cursors import DictCursor

from app import config

router = APIRouter(tags=["health"])

FAIL_BODY = {"status": "error", "detail": "数据库连接失败"}


@router.get(
    "/health",
    summary="健康检查",
    responses={
        200: {"description": "数据库连接正常", "content": {"application/json": {"example": {"status": "ok"}}}},
        503: {"description": "数据库连接失败", "content": {"application/json": {"example": FAIL_BODY}}},
    },
)
def health():
    """建立一次数据库连接并执行 SELECT 1 验证连通性，用完即关闭。"""
    conn = None
    try:
        conn = pymysql.connect(
            host=config.MYSQL_HOST,
            port=config.MYSQL_PORT,
            user=config.MYSQL_USER,
            password=config.MYSQL_PASSWORD,
            database=config.MYSQL_DATABASE,
            charset="utf8mb4",
            cursorclass=DictCursor,
            connect_timeout=3,
        )
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
            cur.fetchone()
    except pymysql.MySQLError:
        return JSONResponse(status_code=503, content=FAIL_BODY)
    finally:
        if conn is not None:
            conn.close()
    return {"status": "ok"}
