FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PORT=8080
ENV MODO_INICIAL=exterior
ENV AUTO_START=true

EXPOSE 8080

CMD ["python", "servidor_remoto_2turno.py"]
