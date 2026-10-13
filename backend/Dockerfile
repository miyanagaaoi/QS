# 询价报价系统 · 后端镜像（v1.0）
# 说明：PRD 选型为 Python 3.11+，实际落地 3.12（开发机 3.12.14 实测通过）。
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    TZ=Asia/Shanghai

WORKDIR /app

# 国内构建加速：apt 与 pip 均走镜像源。
# 原因：默认的 deb.debian.org / pypi.org 在国内网络下经常超时（实测卡在
# apt-get update 的 Packages 索引拉取上数分钟不返回）。如需海外构建，
# 用 `docker build --build-arg APT_MIRROR=deb.debian.org ...` 覆盖即可。
ARG APT_MIRROR=mirrors.tuna.tsinghua.edu.cn
ARG PIP_INDEX=https://pypi.tuna.tsinghua.edu.cn/simple

# tzdata 用于固定容器时区为北京时间（与后端 app_now() 口径一致）；
# 不装 curl —— 基础镜像没有 curl，健康检查改用容器自带的 python（见下）。
RUN set -eux; \
    if [ -f /etc/apt/sources.list.d/debian.sources ]; then \
        sed -i "s|deb.debian.org|${APT_MIRROR}|g" /etc/apt/sources.list.d/debian.sources; \
    fi; \
    if [ -f /etc/apt/sources.list ]; then \
        sed -i "s|deb.debian.org|${APT_MIRROR}|g" /etc/apt/sources.list; \
    fi; \
    apt-get update; \
    apt-get install -y --no-install-recommends tzdata; \
    ln -snf /usr/share/zoneinfo/Asia/Shanghai /etc/localtime; \
    echo "Asia/Shanghai" > /etc/timezone; \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -i "${PIP_INDEX}" -r requirements.txt

COPY app ./app

# 数据目录：SQLite 文件与上传附件（挂载卷持久化）
RUN mkdir -p /app/data/uploads

EXPOSE 8000

# 健康检查用 python 自带的 urllib，避免为健康检查额外安装 curl
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4).status==200 else 1)"

# 生产建议 2 个 worker；SQLite 场景保持单进程写入更稳妥，故默认 1
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
