from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from ..database import get_db
from ..schemas import ProductOut
from ..utils import money

router = APIRouter(prefix="/api/products", tags=["商品管理"])


def _row_to_out(row: dict) -> ProductOut:
    return ProductOut(
        product_id=row["product_id"],
        product_name=row["product_name"],
        category=row["category"],
        price=money(row["price"]),
    )


@router.get("", summary="商品分页列表", response_model=dict)
def list_products(
    category: Optional[str] = Query(None, description="按分类筛选"),
    keyword: Optional[str] = Query(None, description="按商品名称模糊筛选（大小写不敏感）"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    db=Depends(get_db),
):
    where, params = [], []
    if category:
        where.append("category = %s")
        params.append(category)
    if keyword:
        # utf8mb4_0900_ai_ci 排序规则本身大小写不敏感
        where.append("product_name LIKE %s")
        params.append(f"%{keyword}%")
    where_sql = (" WHERE " + " AND ".join(where)) if where else ""
    with db.cursor() as cur:
        cur.execute(f"SELECT COUNT(*) AS c FROM products{where_sql}", params)
        total = cur.fetchone()["c"]
        cur.execute(
            f"SELECT * FROM products{where_sql} ORDER BY product_id LIMIT %s OFFSET %s",
            (*params, page_size, (page - 1) * page_size),
        )
        items = [_row_to_out(r) for r in cur.fetchall()]
    return {"total": total, "page": page, "page_size": page_size, "items": items}


@router.get("/categories", summary="全部分类", response_model=dict)
def list_categories(db=Depends(get_db)):
    with db.cursor() as cur:
        cur.execute("SELECT DISTINCT category FROM products ORDER BY category")
        categories = [r["category"] for r in cur.fetchall()]
    return {"total": len(categories), "items": categories}


@router.get("/{product_id}", summary="商品详情（含销售统计）", response_model=dict)
def get_product(product_id: str, db=Depends(get_db)):
    with db.cursor() as cur:
        cur.execute("SELECT * FROM products WHERE product_id = %s", (product_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"商品不存在: {product_id}")
        cur.execute(
            "SELECT COUNT(*) AS order_count, COALESCE(SUM(s.quantity), 0) AS total_quantity,"
            " COALESCE(SUM(p.price * s.quantity), 0) AS total_amount,"
            " MIN(s.sale_date) AS first_sale_date, MAX(s.sale_date) AS last_sale_date"
            " FROM sales s JOIN products p ON s.product_id = p.product_id"
            " WHERE s.product_id = %s",
            (product_id,),
        )
        agg = cur.fetchone()
    total_quantity = int(agg["total_quantity"])
    if agg["first_sale_date"]:
        # 日均销量分母 = 最早至最晚销售日的日历天数（含首尾）
        days = (agg["last_sale_date"] - agg["first_sale_date"]).days + 1
        avg_daily_quantity = round(total_quantity / days, 2)
    else:
        days = None
        avg_daily_quantity = None
    result = _row_to_out(row).model_dump()
    result.update(
        {
            "total_quantity": total_quantity,
            "total_amount": money(agg["total_amount"]),
            "order_count": int(agg["order_count"]),
            "avg_daily_quantity": avg_daily_quantity,
            "first_sale_date": agg["first_sale_date"].isoformat() if agg["first_sale_date"] else None,
            "last_sale_date": agg["last_sale_date"].isoformat() if agg["last_sale_date"] else None,
        }
    )
    return result
