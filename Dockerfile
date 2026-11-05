FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt requirements.lock.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY *.py alembic.ini profiles.json ./
COPY migrations/ migrations/
COPY data/ data/
COPY static/ static/
CMD ["python", "run.py"]
