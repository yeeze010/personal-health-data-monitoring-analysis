FROM python:3.12-slim

WORKDIR /app
COPY backend ./backend
COPY data ./data

ENV HOST=0.0.0.0
ENV PORT=8206
EXPOSE 8206

CMD ["python", "backend/app.py"]
