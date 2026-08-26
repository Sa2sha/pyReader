# OCR Сервис - Распознавание текста

Сервис для распознавания текста из изображений (PNG, JPG, JPEG) и PDF файлов.

## Быстрый старт (Docker)

### Предварительные требования:
- Docker

### Шаг 1: Скачайте Docker образ

```bash
docker pull ghcr.io/sa2sha/pyreader:latest
```

### Шаг 2: Создайте папку для загрузок
mkdir -p /opt/ocr-service/uploads

### Шаг 3: Запустите контейнер
```
docker run -d \
  --name ocr-service \
  -p 80:5000 \
  -v /opt/ocr-service/uploads:/app/uploads \
  --restart unless-stopped \
  ghcr.io/sa2sha/pyreader:latest
```

### Шаг 4: Узнайте IP сервера
```
hostname -I
```

### Шаг 5: Откройте в браузере
```
http://IP_СЕРВЕРА
```
  
