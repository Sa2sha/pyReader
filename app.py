import os
import io

# Для веб-сервера
from flask import Flask, request, render_template, jsonify

# Для работы с изображениями
from PIL import Image, ImageEnhance
import numpy as np

# Для OCR
import pytesseract
import easyocr

# Для PDF
import fitz

app = Flask(__name__)

pytesseract.pytesseract.tesseract_cmd = r"D:\Tesseract-OCR\tesseract.exe"

# Папка для временных файлов
UPLOAD_FOLDER = 'uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Разрешенные форматы
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'pdf'}

easyocr_reader = None


def preprocess_image(image):
    """
    Подготовка изображения для лучшего распознавания:
    1. Конвертация в grayscale (черно-белый)
    2. Увеличение контраста
    3. Бинаризация (только черный и белый)
    """
    if image.mode != 'L':
        image = image.convert('L')

    enhancer = ImageEnhance.Contrast(image)
    image = enhancer.enhance(2.0)

    threshold = 128
    image = image.point(lambda x: 255 if x > threshold else 0)

    return image


def find_text_area(image):
    """Определяем область с текстом и обрезаем пустые поля"""
    img_array = np.array(image)

    non_white = np.where(img_array < 250)

    if len(non_white[0]) > 0 and len(non_white[1]) > 0:
        top = non_white[0].min()
        bottom = non_white[0].max()
        left = non_white[1].min()
        right = non_white[1].max()

        padding = 10
        image = image.crop((left - padding, top - padding, right + padding, bottom + padding))

    return image


def ocr_tesseract(image, config=None):
    """
    Распознавание через Tesseract с простыми настройками

    config: dict с ключами:
        - lang: строка языков ('rus' или 'eng')
        - psm: режим разметки страницы
    """
    if config is None:
        config = {}

    # Получаем параметры с значениями по умолчанию
    lang = config.get('lang', 'rus')
    psm = config.get('psm', '3')

    # Формируем строку конфигурации (убираем проблемные параметры)
    tess_config = f'--psm {psm}'

    # Распознаем текст
    text = pytesseract.image_to_string(
        image,
        lang=lang,
        config=tess_config
    )

    return text


def ocr_easyocr(image, config=None):
    """
    Распознавание через EasyOCR с простыми настройками

    config: dict с ключами:
        - detail: насколько детальный результат (0 - просто текст)
    """
    global easyocr_reader

    if easyocr_reader is None:
        print("Инициализация EasyOCR (займет время)...")
        easyocr_reader = easyocr.Reader(['ru', 'en'], gpu=False)

    if config is None:
        config = {}

    img_array = np.array(image)

    # Простое распознавание без сложных параметров
    result = easyocr_reader.readtext(
        img_array,
        detail=0,
        paragraph=True
    )

    return '\n'.join(result)


def process_image(image, engine='tesseract', ocr_config=None):
    """Обработка изображения и распознавание текста"""
    image = find_text_area(image)
    image = preprocess_image(image)

    if engine == 'tesseract':
        text = ocr_tesseract(image, ocr_config)
    elif engine == 'easyocr':
        text = ocr_easyocr(image, ocr_config)
    else:
        text = ocr_tesseract(image, ocr_config)

    return text


def pdf_to_images(pdf_path):
    """Конвертируем PDF в список изображений с помощью PyMuPDF"""
    doc = fitz.open(pdf_path)
    images = []

    for page in doc:
        pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
        img_data = pix.tobytes("png")
        img = Image.open(io.BytesIO(img_data))
        images.append(img)

    doc.close()
    return images


@app.route('/')
def index():
    """Главная страница"""
    return render_template('index.html')


@app.route('/upload', methods=['POST'])
def upload():
    """Обработка загрузки файла"""
    try:
        if 'file' not in request.files:
            return jsonify({'error': 'Файл не найден'}), 400

        file = request.files['file']
        engine = request.form.get('ocr_engine', 'tesseract')

        if file.filename == '':
            return jsonify({'error': 'Файл не выбран'}), 400

        ext = file.filename.rsplit('.', 1)[1].lower() if '.' in file.filename else ''
        if ext not in ALLOWED_EXTENSIONS:
            return jsonify({'error': 'Неверный формат файла'}), 400

        ocr_config = {}

        if engine == 'tesseract':
            ocr_config['lang'] = request.form.get('language', 'rus+eng')
            ocr_config['psm'] = request.form.get('layout', '3')

        filename = file.filename

        file_bytes = file.read()

        all_text = ""

        if ext == 'pdf':
            filepath = os.path.join(UPLOAD_FOLDER, filename)
            with open(filepath, 'wb') as f:
                f.write(file_bytes)

            images = pdf_to_images(filepath)
            for i, img in enumerate(images):
                page_text = process_image(img, engine, ocr_config)
                all_text += page_text

            os.remove(filepath)
        else:
            image = Image.open(io.BytesIO(file_bytes))
            all_text = process_image(image, engine, ocr_config)

        # file_bytes - байты файла (можно сохранить в БД)
        # all_text - распознанный текст
        # filename - имя файла
        # engine - какой OCR использовался

        return jsonify({
            'text': all_text,
            'engine': engine,
            'filename': filename,
            'file_size': len(file_bytes)  # размер файла в байтах
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    app.run(debug=True)