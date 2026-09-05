# ============================================================
# GIS-WORKTABLE Dockerfile
# 后端 FastAPI + 前端静态文件，单容器部署
# ============================================================
FROM python:3.11-slim

# 系统依赖：GDAL / PROJ / GEOS（rasterio / geopandas / osmnx 运行时需要）
RUN apt-get update && apt-get install -y --no-install-recommends \
    gdal-bin \
    libgdal-dev \
    proj-bin \
    libproj-dev \
    libgeos-dev \
    && rm -rf /var/lib/apt/lists/*

# 工作目录
WORKDIR /app

# 先装依赖（利用 Docker 层缓存，代码变更不触发重装）
COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r /app/backend/requirements.txt

# 拷贝项目代码
COPY backend/ /app/backend/
COPY frontend/ /app/frontend/
COPY knowledge/ /app/knowledge/
COPY skills/ /app/skills/

# 运行时环境变量
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app
ENV PORT=8000

# 暴露端口
EXPOSE 8000

# 启动后端（main.py 末尾挂载 frontend 静态文件）
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
