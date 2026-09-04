# 研报 Agent 服务镜像
FROM python:3.11-slim

WORKDIR /app

# 先装依赖（利用 Docker 层缓存: 代码变、依赖不变时不用重装）
COPY requirements.txt .
RUN pip install -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple/

# 再拷代码
COPY *.py .
COPY README.md .

EXPOSE 8123

# key 通过 -e 注入，绝不写进镜像（Kama 项目的教训）
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8123"]
