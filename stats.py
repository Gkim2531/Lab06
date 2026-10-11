import calendar
from datetime import date, timedelta
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from ..database import get_db
from ..schemas import TrendPoint, TrendResult, TrendSeries
from ..utils import money

router = APIRouter(prefix="/api/stats", tags=["统计分析"])


def _month_add(d: date, months: int) -> date:
    """日期按月偏移， clamps 到目标月的最后一天。"""
    m = d.month - 1 + months
    y = d.year + m // 12
    m = m % 12 + 1
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


@router.get("/overview", summary="销售概况", response_model=dict)
def overview(
    start_date: Optional[date] = Query(None, description="缺省为全部历史"),
    end_date: Optional[date] = Query(None, description="缺省为全部历史"),
    db=Depends(get_db),
):
    """范围内：销售额、销量、交易次数、发生销售的去重商品数、分类数、日均销量。"""
    if start_date and end_date and start_date > end_date:
        raise HTTPException(status_code=422, detail="start_date 不能晚于 end_date")
    where, params = [], []
    if start_date:
        where.append("s.sale_date >= %s")
        params.append(start_date)
    if end_date:
        where.append("s.sale_date <= %s")
        params.append(end_date)
    where_sql = (" WHERE " + " AND ".join(where)) if where else ""
    with db.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) AS order_count, COALESCE(SUM(s.quantity), 0) AS total_quantity,"
            " COALESCE(SUM(p.price * s.quantity), 0) AS total_amount,"
            " COUNT(DISTINCT s.product_id) AS product_count,"
            " COUNT(DISTINCT p.category) AS category_count,"
            " MIN(s.sale_date) AS first_sale_date, MAX(s.sale_date) AS last_sale_date"
            " FROM sales s JOIN products p ON s.product_id = p.product_id"
            + where_sql,
            params,
        )
        r = cur.fetchone()
    total_quantity = int(r["total_quantity"])
    # 日均销量分母优先取显式范围（含首尾日），否则取数据最早最晚销售日
    if start_date and end_date:
        days = (end_date - start_date).days + 1
    elif r["first_sale_date"]:
        days = (r["last_sale_date"] - r["first_sale_date"]).days + 1
    else:
        days = None
    return {
        "total_amount": money(r["total_amount"]),
        "total_quantity": total_quantity,
        "order_count": int(r["order_count"]),
        "product_count": int(r["product_count"]),
        "category_count": int(r["category_count"]),
        "avg_daily_quantity": round(total_quantity / days, 2) if days else None,
        "start_date": start_date.isoformat() if start_date else None,
        "end_date": end_date.isoformat() if end_date else None,
    }


@router.get("/category", summary="按分类统计", response_model=dict)
def by_category(db=Depends(get_db)):
    """每个分类的销量、销售额、交易次数、销售额占比（按销售额倒序）。"""
    with db.cursor() as cur:
        cur.execute(
            "SELECT p.category,"
            " COUNT(*) AS order_count,"
            " SUM(s.quantity) AS total_quantity,"
            " SUM(p.price * s.quantity) AS total_amount"
            " FROM sales s JOIN products p ON s.product_id = p.product_id"
            " GROUP BY p.category ORDER BY total_amount DESC"
        )
        rows = cur.fetchall()
        cur.execute(
            "SELECT COALESCE(SUM(p.price * s.quantity), 0) AS total"
            " FROM sales s JOIN products p ON s.product_id = p.product_id"
        )
        grand_total = Decimal(cur.fetchone()["total"])
    items = []
    for r in rows:
        amount = Decimal(r["total_amount"])
        items.append(
            {
                "category": r["category"],
                "order_count": int(r["order_count"]),
                "total_quantity": int(r["total_quantity"]),
                "total_amount": money(amount),
                "amount_ratio": round(amount / grand_total, 4) if grand_total else 0,
            }
        )
    return {"total": len(items), "items": items}


@router.get("/top-products", summary="热销商品排行", response_model=dict)
def top_products(
    limit: int = Query(10, ge=1, le=100),
    sort_by: str = Query("amount", pattern="^(amount|quantity)$"),
    db=Depends(get_db),
):
    order_col = "total_amount" if sort_by == "amount" else "total_quantity"
    with db.cursor() as cur:
        cur.execute(
            f"SELECT s.product_id, p.product_name, p.category, p.price,"
            f" COUNT(*) AS order_count,"
            f" SUM(s.quantity) AS total_quantity,"
            f" SUM(p.price * s.quantity) AS total_amount"
            f" FROM sales s JOIN products p ON s.product_id = p.product_id"
            f" GROUP BY s.product_id, p.product_name, p.category, p.price"
            f" ORDER BY {order_col} DESC LIMIT %s",
            (limit,),
        )
        rows = cur.fetchall()
    items = [
        {
            "product_id": r["product_id"],
            "product_name": r["product_name"],
            "category": r["category"],
            "price": money(r["price"]),
            "order_count": int(r["order_count"]),
            "total_quantity": int(r["total_quantity"]),
            "total_amount": money(r["total_amount"]),
        }
        for r in rows
    ]
    return {"total": len(items), "items": items}


@router.get("/trend", summary="日/月销售趋势（按分类分组，周期补零）", response_model=TrendResult)
def trend(
    period: str = Query("day", pattern="^(day|month)$"),
    start_date: Optional[date] = Query(None, description="缺省：day 为最近 30 天，month 为最近 12 个月"),
    end_date: Optional[date] = Query(None, description="缺省为今天"),
    category: Optional[list[str]] = Query(None, description="分类多选；缺省为全部分类"),
    db=Depends(get_db),
):
    today = date.today()
    end = end_date or today
    if period == "day":
        start = start_date or (end - timedelta(days=29))
    else:
        start = start_date or _month_add(end, -11)
    if start > end:
        raise HTTPException(status_code=422, detail="start_date 不能晚于 end_date")

    # 统一时间轴
    if period == "day":
        buckets: list[str] = []
        d = start
        while d <= end:
            buckets.append(d.isoformat())
            d += timedelta(days=1)
    else:
        buckets = []
        y, m = start.year, start.month
        while (y, m) <= (end.year, end.month):
            buckets.append(f"{y:04d}-{m:02d}")
            m += 1
            if m == 13:
                y, m = y + 1, 1

    with db.cursor() as cur:
        if category:
            cats = list(dict.fromkeys(category))  # 去重保序
        else:
            cur.execute("SELECT DISTINCT category FROM products ORDER BY category")
            cats = [r["category"] for r in cur.fetchall()]

        # 两种周期都用 DATE_FORMAT，保证 bucket 是字符串，与 buckets 时间轴类型一致
        bucket_expr = (
            "DATE_FORMAT(s.sale_date, '%%Y-%%m-%%d')" if period == "day"
            else "DATE_FORMAT(s.sale_date, '%%Y-%%m')"
        )
        where = ["s.sale_date >= %s", "s.sale_date <= %s"]
        params: list = [start, end]
        if cats:
            placeholders = ",".join(["%s"] * len(cats))
            where.append(f"p.category IN ({placeholders})")
            params.extend(cats)
        cur.execute(
            f"SELECT {bucket_expr} AS bucket, p.category,"
            f" SUM(s.quantity) AS total_quantity,"
            f" SUM(p.price * s.quantity) AS total_amount"
            f" FROM sales s JOIN products p ON s.product_id = p.product_id"
            f" WHERE {' AND '.join(where)}"
            f" GROUP BY bucket, p.category",
            params,
        )
        data = {
            (r["bucket"], r["category"]): (int(r["total_quantity"]), money(r["total_amount"]))
            for r in cur.fetchall()
        }

    # 每个分类按统一时间轴补零
    series = []
    for c in cats:
        points = [
            TrendPoint(
                quantity=data.get((b, c), (0, "0.00"))[0],
                amount=data.get((b, c), (0, "0.00"))[1],
            )
            for b in buckets
        ]
        series.append(TrendSeries(category=c, points=points))

    if period == "day":
        start_str, end_str = start.isoformat(), end.isoformat()
    else:
        start_str = f"{start.year:04d}-{start.month:02d}"
        end_str = f"{end.year:04d}-{end.month:02d}"
    return TrendResult(
        period=period,
        start_date=start_str,
        end_date=end_str,
        buckets=buckets,
        series=series,
    )


@router.get("/product/{product_id}", summary="单个商品销售统计", response_model=dict)
def product_stats(product_id: str, db=Depends(get_db)):
    with db.cursor() as cur:
        cur.execute("SELECT 1 FROM products WHERE product_id = %s", (product_id,))
        if not cur.fetchone():
            raise HTTPException(status_code=404, detail=f"商品不存在: {product_id}")
        cur.execute(
            "SELECT COUNT(*) AS order_count, COALESCE(SUM(s.quantity), 0) AS total_quantity,"
            " COALESCE(SUM(p.price * s.quantity), 0) AS total_amount,"
            " MIN(s.sale_date) AS first_sale_date, MAX(s.sale_date) AS last_sale_date"
            " FROM sales s JOIN products p ON s.product_id = p.product_id"
            " WHERE s.product_id = %s",
            (product_id,),
        )
        r = cur.fetchone()
    total_quantity = int(r["total_quantity"])
    if r["first_sale_date"]:
        days = (r["last_sale_date"] - r["first_sale_date"]).days + 1
        avg_daily_quantity = round(total_quantity / days, 2)
    else:
        avg_daily_quantity = None
    return {
        "product_id": product_id,
        "order_count": int(r["order_count"]),
        "total_quantity": total_quantity,
        "total_amount": money(r["total_amount"]),
        "avg_daily_quantity": avg_daily_quantity,
        "first_sale_date": r["first_sale_date"].isoformat() if r["first_sale_date"] else None,
        "last_sale_date": r["last_sale_date"].isoformat() if r["last_sale_date"] else None,
    }
