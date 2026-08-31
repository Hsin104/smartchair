FROM python:3.12-slim

WORKDIR /app

# psycopg2-binary、faiss-cpu、tensorflow 都有現成 wheel，不需要額外編譯工具鏈
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# print() 在容器裡預設會緩衝、log 延遲才出現，設成非緩衝模式即時看到輸出
ENV PYTHONUNBUFFERED=1

COPY . .

EXPOSE 8000 8010

CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]
