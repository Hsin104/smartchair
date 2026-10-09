FROM python:3.12-slim

WORKDIR /app

# psycopg2-binary、faiss-cpu、tensorflow 都有現成 wheel，不需要額外編譯工具鏈
#
# 用 BuildKit cache mount 快取 pip 下載的 wheel（跨 build 持久保存，不受 layer cache
# 失效影響）：requirements.txt 任何一行變動都會讓整個 RUN 重跑，若不快取，tensorflow
# 等大型套件（約 600MB）每次改動都要整個重新下載。2026-10-09 曾在慢速網路環境下
# 卡住超過一小時，之後才加上這個 cache mount。
COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements.txt

# print() 在容器裡預設會緩衝、log 延遲才出現，設成非緩衝模式即時看到輸出
ENV PYTHONUNBUFFERED=1

COPY . .

EXPOSE 8000 8010

CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]
