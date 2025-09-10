# 1. 使用一个轻量级的 Python 官方镜像作为基础
FROM python:3.10-slim

# 2. 设置工作目录
WORKDIR /app

# Install uv
ENV UV_VERSION=0.7.11

RUN pip install --no-cache-dir uv==${UV_VERSION}


# 4. 复制应用程序代码到工作目录
COPY ./src/*  ./src/

#复制依赖文件并安装依赖
COPY pyproject.toml uv.lock ./
RUN uv sync --locked



# 5. 当容器启动时，运行 Python 脚本
CMD ["uv", "run", "./src/app/difybot.py"]