from datetime import date
from typing import Optional

from pydantic import BaseModel, Field


# ---------- 商品 ----------

class ProductOut(BaseModel):
    product_id: str = Field(..., max_length=20, description="商品编号")
    product_name: str = Field(..., max_length=100, description="商品名称")
    category: str = Field(..., max_length=50, description="商品分类")
    price: str = Field(..., description="单价，两位小数字符串，如 \"5999.00\"")


class ProductDetailOut(ProductOut):
    """商品详情：基本信息 + 全部历史销售统计。"""
    total_quantity: int = Field(..., description="销量合计")
    total_amount: str = Field(..., description="销售额合计，两位小数字符串")
    order_count: int = Field(..., description="交易次数")
    avg_daily_quantity: Optional[float] = Field(None, description="日均销量，无销售记录时为 null")
    first_sale_date: Optional[date] = None
    last_sale_date: Optional[date] = None


# ---------- 销售趋势 ----------

class TrendPoint(BaseModel):
    quantity: int = Field(..., description="该周期销量")
    amount: str = Field(..., description="该周期销售额，两位小数字符串")


class TrendSeries(BaseModel):
    category: str
    points: list[TrendPoint]  # 与全局 buckets 数组一一对齐，无数据周期补零


class TrendResult(BaseModel):
    period: str = Field(..., description="day 或 month")
    start_date: str = Field(..., description="day: YYYY-MM-DD；month: YYYY-MM")
    end_date: str
    buckets: list[str] = Field(..., description="统一时间轴，各分类曲线周期一致")
    series: list[TrendSeries]


# ---------- 销售记录 ----------

class SaleOut(BaseModel):
    sale_id: int
    product_id: str
    product_name: Optional[str] = None
    category: Optional[str] = None
    price: Optional[str] = Field(None, description="单价，两位小数字符串")
    quantity: int
    sale_date: date
    amount: Optional[str] = Field(None, description="该笔销售额 = 单价 x 数量，两位小数字符串")


# ---------- CSV 上传 ----------

class UploadResult(BaseModel):
    total_rows: int = Field(..., description="CSV 数据行数")
    new_products: int = Field(..., description="本次新增商品数")
    new_sales: int = Field(..., description="本次新增销售记录数")
    skipped_sales: int = Field(..., description="因联合唯一约束被跳过的重复销售记录数")
    message: str
