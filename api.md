# 销售数据分析后端 · 接口文档（api.md）

依据 [spec.md](spec.md) 制定。Base URL：`http://127.0.0.1:8000`。

## 通用约定

**方法约定**：除 CSV 上传为 `POST` 外，其余接口均为 `GET`。业务路径统一以 `/api` 开头。

**分页**：列表类接口统一参数 `page`（缺省 1，≥1）、`page_size`（缺省 20，1~200，越界 422）。统一响应结构：

```json
{ "total": 992, "page": 1, "page_size": 20, "items": [ ... ] }
```

**日期**：一律 `YYYY-MM-DD`；筛选区间均为闭区间（含首尾日）；格式非法 422。

**金额**：统一返回**两位小数字符串**（如 `"9452112.00"`），不做浮点返回。

**空结果**：列表/统计返回 200 + 空 `items` / 0 值，不报错；按 ID 查询不存在返回 404。

**错误响应格式**：

```json
{ "detail": "错误描述" }
```

或含结构化明细（如上传冲突）：

```json
{ "detail": { "message": "...", "conflicts": [ ... ] } }
```

**统计口径**（见 spec 5.1）：销量 = Σquantity；销售额 = Σprice×quantity；交易次数 = 记录行数；概况商品数 = 范围内发生销售的去重商品数；日均销量 = 销量 ÷ 含首尾日的日历天数。

---

## 健康检查

| 方法 | 路径 | 功能 |
|---|---|---|
| GET | `/health` | 检查数据库连接状态 |

**成功 200**：`{ "status": "ok" }`

**失败 503**：数据库不可达时 `{ "status": "error", "detail": "数据库连接失败" }`。

---

## A. 销售数据管理

| 方法 | 路径 | 功能 |
|---|---|---|
| POST | `/api/sales/upload` | CSV 上传（事务追加） |
| GET | `/api/products/categories` | 分类选项 |
| GET | `/api/products` | 商品分页列表 |
| GET | `/api/products/{product_id}` | 商品详情（含销售统计） |
| GET | `/api/sales` | 销售明细分页 |

### A1. POST `/api/sales/upload` — CSV 上传

**功能**：上传 CSV 事务追加。判重跳过 + 商品冲突拒绝 + 保留现有数据。校验与判重规则见 spec A1。

**请求**：`multipart/form-data`；文件字段名 **`csv_file`**；`.csv` 文件；UTF-8 编码（**兼容 BOM**）；**最大 10MB**，超限返回 413。

**成功 200**：返回总行数、新增商品数、新增销售数、重复跳过数。

```json
{
  "total_rows": 992,
  "new_products": 0,
  "new_sales": 0,
  "skipped_sales": 992,
  "message": "无新增数据（全部为重复销售记录）"
}
```

部分新增示例：`{ "total_rows": 2, "new_products": 1, "new_sales": 1, "skipped_sales": 1, "message": "导入完成" }`

**错误**：

| 码 | 场景 |
|---|---|
| 413 | 文件超过 10MB |
| 422 | 非 UTF-8、缺必需列、无数据行；行级校验失败（空字段/价格非数字/数量非正整数/日期非法）；CSV 内部商品信息不一致；与库内商品冲突（附 `conflicts` 明细）。均整体拒绝、零写入 |

### A2. GET `/api/products/categories` — 分类选项

**参数**：无。**成功 200**：`{ "total": 5, "items": ["家具", "家电", "日用品", "电子产品", "运动用品"] }`（动态去重，无排序保证）。

### A3. GET `/api/products` — 商品分页列表

| 参数 | 类型 | 缺省 | 校验/说明 |
|---|---|---|---|
| `category` | string | 无 | 精确匹配 |
| `keyword` | string | 无 | 名称模糊匹配，大小写不敏感 |
| `page` | int | 1 | ≥1 |
| `page_size` | int | 20 | 1~200 |

**成功 200**（`price` 为两位小数字符串）：

```json
{
  "total": 1, "page": 1, "page_size": 5,
  "items": [
    { "product_id": "P001", "product_name": "iPhone 14", "category": "电子产品", "price": "5999.00" }
  ]
}
```

### A4. GET `/api/products/{product_id}` — 商品详情（含统计）

统计基于**全部历史**（不支持日期范围），口径见通用约定。无销售记录时 `avg_daily_quantity` 为 `null`，其余统计为 0。

**成功 200**（P001 实测数据，金额按字符串格式）：

```json
{
  "product_id": "P001", "product_name": "iPhone 14", "category": "电子产品", "price": "5999.00",
  "total_quantity": 217, "total_amount": "1301783.00", "order_count": 42,
  "avg_daily_quantity": 0.59,
  "first_sale_date": "2024-10-09", "last_sale_date": "2025-10-08"
}
```

**错误**：404 商品不存在。

### A5. GET `/api/sales` — 销售明细分页

| 参数 | 类型 | 缺省 | 校验/说明 |
|---|---|---|---|
| `product_id` | string | 无 | 精确匹配 |
| `start_date` | date | 不限 | 闭区间起点 |
| `end_date` | date | 不限 | 闭区间终点 |
| `page` / `page_size` | int | 1 / 20 | 同上 |

排序：日期倒序，同日期按单号倒序。`amount` = price×quantity（服务端计算，字符串金额）。

**成功 200**：

```json
{
  "total": 4, "page": 1, "page_size": 20,
  "items": [
    {
      "sale_id": 963, "product_id": "P001", "product_name": "iPhone 14",
      "category": "电子产品", "price": "5999.00", "quantity": 8,
      "sale_date": "2025-07-27", "amount": "47992.00"
    }
  ]
}
```

---

## B. 数据统计分析

| 方法 | 路径 | 功能 |
|---|---|---|
| GET | `/api/stats/overview` | 销售概况 |
| GET | `/api/stats/category` | 分类统计 |
| GET | `/api/stats/top-products` | 热销排行 |
| GET | `/api/stats/trend` | 日/月销售趋势（按分类分组） |
| GET | `/api/stats/product/{product_id}` | 单品销售统计 |

### B1. GET `/api/stats/overview` — 销售概况

| 参数 | 类型 | 缺省 | 说明 |
|---|---|---|---|
| `start_date` / `end_date` | date | 不限（全部历史） | 闭区间；倒置 422 |

**成功 200**（全历史实测，金额按字符串格式）：

```json
{
  "total_amount": "9452112.00", "total_quantity": 5338, "order_count": 992,
  "product_count": 30, "category_count": 5,
  "avg_daily_quantity": 14.58,
  "start_date": null, "end_date": null
}
```

`avg_daily_quantity` 分母：显式范围取区间天数（含首尾）；否则取最早至最晚销售日；范围内无数据且未指定范围时为 `null`。

### B2. GET `/api/stats/category` — 分类统计

无参数。**成功 200**：按销售额倒序，`amount_ratio` 保留 4 位小数（数值）。

```json
{
  "total": 5,
  "items": [
    {
      "category": "电子产品", "order_count": 306, "total_quantity": 1620,
      "total_amount": "5200000.00", "amount_ratio": 0.55
    }
  ]
}
```

### B3. GET `/api/stats/top-products` — 热销排行

| 参数 | 类型 | 缺省 | 校验 |
|---|---|---|---|
| `limit` | int | 10 | 1~100 |
| `sort_by` | string | `amount` | 枚举 `amount` / `quantity` |

**成功 200**：每项含 `product_id`、`product_name`、`category`、`price`（字符串金额）、`order_count`、`total_quantity`、`total_amount`（字符串金额）。

### B4. GET `/api/stats/trend` — 日/月销售趋势

| 参数 | 类型 | 缺省 | 校验/说明 |
|---|---|---|---|
| `period` | string | `day` | 枚举 `day` / `month` |
| `start_date` / `end_date` | date | day：近 30 天；month：近 12 个月（含当月），终点为今天 | 倒置 422 |
| `category` | string[] | 全部 5 类 | 可重复传参多选，如 `category=电子产品&category=家具` |

**补零与周期一致**：`buckets` 为覆盖范围每个自然日/月的统一时间轴；所有分类曲线与 `buckets` 一一对齐，无数据周期补 0；分类集合固定（含无数据分类）。

**成功 200**（`period=day, 2025-01-17~2025-01-21, category=家具` 实测）：

```json
{
  "period": "day",
  "start_date": "2025-01-17", "end_date": "2025-01-21",
  "buckets": ["2025-01-17", "2025-01-18", "2025-01-19", "2025-01-20", "2025-01-21"],
  "series": [
    { "category": "家具", "points": [
      { "quantity": 21, "amount": "25995.00" },
      { "quantity": 5, "amount": "3495.00" },
      { "quantity": 0, "amount": "0.00" },
      { "quantity": 0, "amount": "0.00" },
      { "quantity": 0, "amount": "0.00" }
    ] }
  ]
}
```

月趋势 `start_date`/`end_date` 及 `buckets` 元素为 `YYYY-MM` 格式。

### B5. GET `/api/stats/product/{product_id}` — 单品销售统计

与 A4 统计字段一致（`product_id`、`order_count`、`total_quantity`、`total_amount` 字符串金额、`avg_daily_quantity`、`first_sale_date`、`last_sale_date`），无商品基础信息。**错误**：404 商品不存在。

---

## 错误状态码汇总

| 码 | 含义 | 典型场景 |
|---|---|---|
| 404 | 商品不存在 | 商品详情/单品统计/销售记录不存在 |
| 413 | 上传文件超限 | CSV 超过 10MB |
| 422 | 输入非法 | 参数类型/格式/枚举/越界校验失败；日期区间倒置；CSV 编码、缺列、行级校验失败；CSV 内部或库内商品信息冲突 |
| 503 | 数据库连接失败 | `/health` 检测失败；任一接口执行时数据库不可达 |
| 500 | 未预期错误 | 其他服务器内部异常 |
