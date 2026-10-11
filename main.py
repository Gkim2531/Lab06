from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers import health, products, sales, stats

app = FastAPI(title="销售数据分析后端", version="1.0.0")

# 允许前端跨域调用
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(products.router)
app.include_router(sales.router)
app.include_router(stats.router)


@app.get("/", summary="服务信息", response_model=dict)
def root():
    return {
        "name": "销售数据分析后端",
        "docs": "/docs",
        "routers": ["/api/products", "/api/sales", "/api/stats"],
    }
