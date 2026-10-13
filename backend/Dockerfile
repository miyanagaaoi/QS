# 询价报价系统 · 后端镜像
# 说明：PRD 选型为 Python 3.11+，实际落地 3.12（开发机 3.12.14 实测通过）。
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    TZ=Asia/Shanghai

WORKDIR /app

# curl 用于健康检查；tzdata 固定容器时区为北京时间（与后端 app_now() 口径一致）
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl tzdata \
    && ln -snf /usr/share/zoneinfo/Asia/Shanghai /etc/localtime \
    && echo "Asia/Shanghai" > /etc/timezone \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

# 数据目录：SQLite 文件与上传附件（挂载卷持久化）
RUN mkdir -p /app/data/uploads

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/api/health || exit 1

# 生产建议 2 个 worker；SQLite 场景保持单进程写入更稳妥，故默认 1
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
