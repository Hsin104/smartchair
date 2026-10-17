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

# 收集 admin／DRF 的靜態檔供 WhiteNoise 提供（Gunicorn 本身不處理靜態檔）
# build 階段沒有 .env，settings.py 沒有 SECRET_KEY 會拒絕啟動；collectstatic 只複製檔案、不簽章，給一把佔位值即可
RUN DJANGO_SECRET_KEY=build-only-placeholder python manage.py collectstatic --noinput

EXPOSE 8000 8010

# 正式 WSGI server，設定與選型理由見 gunicorn.conf.py
CMD ["gunicorn", "smartchair_backend.wsgi:application", "-c", "gunicorn.conf.py"]
