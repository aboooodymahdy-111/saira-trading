# يبني ويشغّل app/main.py على Render أو Fly.io — الجذر عند البناء هو جذر
# المستودع (Saira-Trading/) وليس saira-api/، لأن app/config.py يحتاج src/
# وdata/ بجانب saira-api/ كما في التخطيط المحلي (SAIRA_ROOT = API_ROOT.parent / "src").
FROM python:3.11-slim

# build-essential احتياطي لـ pyswisseph: يوفّر PyPI عجلات (wheels) جاهزة لمعظم
# بيئات Linux فلا حاجة تُبنى من المصدر عادةً، لكن تركه هنا يمنع فشل أول نشر
# صامتًا لو Fly.io استخدم بنية/إصدار بايثون بلا عجلة جاهزة.
RUN apt-get update && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /repo

COPY src/ ./src/
COPY data/ ./data/
COPY saira-api/requirements.txt ./saira-api/requirements.txt
COPY saira-api/app/ ./saira-api/app/

RUN pip install --no-cache-dir -r saira-api/requirements.txt

WORKDIR /repo/saira-api

ENV SAIRA_ROOT=/repo/src
ENV SAIRA_ALLOWLIST=/repo/data/ticker_universe.csv
ENV SAIRA_DB=/repo/saira-api/saira.duckdb
ENV SAIRA_HOST=0.0.0.0
ENV SAIRA_PORT=8080

EXPOSE 8080

# $PORT: Render يحقن منفذًا ديناميكيًا وقت التشغيل (يتجاوز 8080)؛ Fly.io لا
# يعرّفه فيبقى الافتراضي 8080 كما في fly.toml's internal_port. shell form
# (بلا أقواس []) ضروري هنا كي ${PORT:-8080} يتوسّع فعليًا قبل تشغيل uvicorn.
CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080}
