import csv
import io
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile
from pymysql import err

from ..database import get_db
from ..schemas import SaleOut, UploadResult
from ..utils import money

router = APIRouter(prefix="/api/sales", tags=["销售数据管理"])

REQUIRED_COLUMNS = {"product_id", "product_name", "category", "price", "quantity", "sale_date"}
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB


def _row_to_out(row: dict) -> SaleOut:
    price = Decimal(row["price"]) if row.get("price") is not None else None
    quantity = row["quantity"]
    return SaleOut(
        sale_id=row["sale_id"],
        product_id=row["product_id"],
        product_name=row.get("product_name"),
        category=row.get("category"),
        price=money(price) if price is not None else None,
        quantity=quantity,
        sale_date=row["sale_date"],
        amount=money(price * quantity) if price is not None else None,
    )


@router.get("", summary="销售记录列表", response_model=dict)
def list_sales(
    product_id: Optional[str] = Query(None, description="按商品筛选"),
    start_date: Optional[date] = Query(None, description="起始日期"),
    end_date: Optional[date] = Query(None, description="结束日期"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    db=Depends(get_db),
):
    if start_date and end_date and start_date > end_date:
        raise HTTPException(status_code=422, detail="start_date 不能晚于 end_date")
    where, params = [], []
    if product_id:
        where.append("s.product_id = %s")
        params.append(product_id)
    if start_date:
        where.append("s.sale_date >= %s")
        params.append(start_date)
    if end_date:
        where.append("s.sale_date <= %s")
        params.append(end_date)
    where_sql = (" WHERE " + " AND ".join(where)) if where else ""
    base_sql = (
        "FROM sales s JOIN products p ON s.product_id = p.product_id" + where_sql
    )
    with db.cursor() as cur:
        cur.execute(f"SELECT COUNT(*) AS c {base_sql}", params)
        total = cur.fetchone()["c"]
        cur.execute(
            f"SELECT s.sale_id, s.product_id, p.product_name, p.category, p.price,"
            f" s.quantity, s.sale_date {base_sql}"
            f" ORDER BY s.sale_date DESC, s.sale_id DESC LIMIT %s OFFSET %s",
            (*params, page_size, (page - 1) * page_size),
        )
        items = [_row_to_out(r) for r in cur.fetchall()]
    return {"total": total, "page": page, "page_size": page_size, "items": items}


@router.post("/upload", summary="上传 CSV 追加销售数据（事务）", response_model=UploadResult)
async def upload_sales_csv(csv_file: UploadFile, db=Depends(get_db)):
    content = await csv_file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(status_code=413, detail="CSV 文件超过 10MB 限制")
    try:
        text = content.decode("utf-8-sig")  # 兼容带 BOM 的 UTF-8
    except UnicodeDecodeError:
        raise HTTPException(status_code=422, detail="CSV 文件必须是 UTF-8 编码")

    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames or not REQUIRED_COLUMNS.issubset(set(reader.fieldnames)):
        raise HTTPException(
            status_code=422,
            detail=f"CSV 缺少必需列，需要: {sorted(REQUIRED_COLUMNS)}",
        )
    # 跳过完全空白的行
    rows = [r for r in reader if any((v or "").strip() for v in r.values())]
    if not rows:
        raise HTTPException(status_code=422, detail="CSV 没有数据行")

    # ---------- 第一步：解析 CSV，并校验 CSV 内部的商品信息一致性 ----------
    csv_products: dict[str, tuple[str, str, Decimal]] = {}
    parsed_sales: list[tuple[str, int, date]] = []
    row_errors: list[str] = []

    for lineno, row in enumerate(rows, start=2):
        pid = (row.get("product_id") or "").strip()
        name = (row.get("product_name") or "").strip()
        category = (row.get("category") or "").strip()
        price_str = (row.get("price") or "").strip()
        qty_str = (row.get("quantity") or "").strip()
        date_str = (row.get("sale_date") or "").strip()

        if not all([pid, name, category, price_str, qty_str, date_str]):
            row_errors.append(f"第 {lineno} 行：存在空字段")
            continue
        try:
            price = Decimal(price_str)
        except InvalidOperation:
            row_errors.append(f"第 {lineno} 行：价格不是数字（{price_str}）")
            continue
        try:
            quantity = int(qty_str)
            if quantity <= 0:
                raise ValueError
        except ValueError:
            row_errors.append(f"第 {lineno} 行：数量必须是正整数（{qty_str}）")
            continue
        try:
            sale_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            row_errors.append(f"第 {lineno} 行：日期格式必须是 YYYY-MM-DD（{date_str}）")
            continue

        info = (name, category, price)
        existing = csv_products.get(pid)
        if existing is not None and existing != info:
            row_errors.append(
                f"第 {lineno} 行：商品 {pid} 信息与前面行不一致"
                f"（CSV 内部冲突）"
            )
            continue
        csv_products.setdefault(pid, info)
        parsed_sales.append((pid, quantity, sale_date))

    if row_errors:
        raise HTTPException(
            status_code=422,
            detail={"message": "CSV 数据校验失败，已拒绝导入", "errors": row_errors[:20]},
        )

    try:
        with db.cursor() as cur:
            # ---------- 第二步：与库内已有商品比对，冲突则整体拒绝 ----------
            existing_products: dict[str, tuple[str, str, Decimal]] = {}
            if csv_products:
                placeholders = ",".join(["%s"] * len(csv_products))
                cur.execute(
                    f"SELECT product_id, product_name, category, price"
                    f" FROM products WHERE product_id IN ({placeholders})",
                    list(csv_products),
                )
                existing_products = {
                    r["product_id"]: (r["product_name"], r["category"], Decimal(r["price"]))
                    for r in cur.fetchall()
                }

            conflicts = []
            for pid, info in csv_products.items():
                db_info = existing_products.get(pid)
                if db_info is not None and db_info != info:
                    conflicts.append(
                        {
                            "product_id": pid,
                            "csv": {"product_name": info[0], "category": info[1], "price": str(info[2])},
                            "db": {"product_name": db_info[0], "category": db_info[1], "price": str(db_info[2])},
                        }
                    )
            if conflicts:
                db.rollback()
                raise HTTPException(
                    status_code=422,
                    detail={
                        "message": "商品信息与数据库中已有商品冲突，已拒绝导入",
                        "conflicts": conflicts,
                    },
                )

            # ---------- 第三步：事务内追加（新商品 + 销售记录，重复销售跳过） ----------
            new_products = 0
            for pid, (name, category, price) in csv_products.items():
                if pid not in existing_products:
                    cur.execute(
                        "INSERT INTO products (product_id, product_name, category, price)"
                        " VALUES (%s, %s, %s, %s)",
                        (pid, name, category, price),
                    )
                    new_products += 1

            new_sales = 0
            skipped_sales = 0
            for pid, quantity, sale_date in parsed_sales:
                try:
                    cur.execute(
                        "INSERT INTO sales (product_id, quantity, sale_date)"
                        " VALUES (%s, %s, %s)",
                        (pid, quantity, sale_date),
                    )
                    new_sales += 1
                except err.IntegrityError as e:
                    # 1062：命中 (product_id, quantity, sale_date) 联合唯一约束，跳过
                    if e.args and e.args[0] == 1062:
                        skipped_sales += 1
                    else:
                        raise
            db.commit()
    except HTTPException:
        raise
    except err.IntegrityError as e:
        db.rollback()
        raise HTTPException(status_code=422, detail=f"数据完整性错误，已回滚：{e}")
    except Exception:
        db.rollback()
        raise

    return UploadResult(
        total_rows=len(rows),
        new_products=new_products,
        new_sales=new_sales,
        skipped_sales=skipped_sales,
        message="导入完成" if new_sales or new_products else "无新增数据（全部为重复销售记录）",
    )
