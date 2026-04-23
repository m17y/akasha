FROM python:3.12-slim

# 系统依赖: git(deploy), ffmpeg(音视频转写), yt-dlp 依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
        git \
        ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# 安装 uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# 创建 venv，先装依赖（利用 Docker 层缓存）
COPY pyproject.toml ./
RUN uv venv /app/.venv && \
    uv pip install --python /app/.venv/bin/python \
    chromadb pyyaml openai anthropic httpx "mkdocs>=1.6,<2.0" mkdocs-material lark-oapi uvicorn starlette "mcp>=1.25.0"

# 复制项目代码并安装
COPY . .
RUN uv pip install --python /app/.venv/bin/python -e .

# 安装可选工具
RUN uv pip install --python /app/.venv/bin/python yt-dlp || true
RUN uv pip install --python /app/.venv/bin/python faster-whisper || true

ENV PATH="/app/.venv/bin:$PATH"

# 默认数据目录
ENV AKASHA_VAULT_PATH="/data/akasha"
ENV AKASHA_CHROMA_DIR="/data/chroma"
# Docker 里 site serve 需要监听 0.0.0.0
ENV AKASHA_SITE_HOST="0.0.0.0"
# HuggingFace 模型缓存持久化到 /data
ENV HF_HOME="/data/hf_cache"

VOLUME ["/data"]

EXPOSE 8800

ENTRYPOINT ["akasha"]
CMD ["start"]
