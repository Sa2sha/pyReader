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




def ocr_tesseract(image):
    """Распознавание через Tesseract"""
    text = pytesseract.image_to_string(image, lang='rus+eng')
    return text


def ocr_easyocr(image):
    """Распознавание через EasyOCR"""
    global easyocr_reader

    if easyocr_reader is None:
        print("Инициализация EasyOCR (займет время)...")
        easyocr_reader = easyocr.Reader(['ru', 'en'], gpu=False)

    img_array = np.array(image)

    result = easyocr_reader.readtext(img_array, detail=0, paragraph=True)
    return '\n'.join(result)





def process_image(image, engine='tesseract'):
    image = find_text_area(image)

    image = preprocess_image(image)

    if engine == 'tesseract':
        text = ocr_tesseract(image)
    elif engine == 'easyocr':
        text = ocr_easyocr(image)
    else:
        text = ocr_tesseract(image)

    return text


def pdf_to_images(pdf_path):
    """Конвертируем PDF в список изображений с помощью PyMuPDF"""
    doc = fitz.open(pdf_path)
    images = []

    for page in doc:
        # Конвертируем страницу в изображение
        # matrix=fitz.Matrix(2, 2) для лучшего качества (2x zoom)
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

        filename = file.filename
        filepath = os.path.join(UPLOAD_FOLDER, filename)
        file.save(filepath)

        all_text = ""

        if ext == 'pdf':
            # Конвертируем PDF в изображения
            images = pdf_to_images(filepath)
            for i, img in enumerate(images):
                page_text = process_image(img, engine)
                all_text += f"=== Страница {i + 1} ===\n{page_text}\n\n"
        else:
            # Обрабатываем обычное изображение
            image = Image.open(filepath)
            all_text = process_image(image, engine)

        # Удаляем временный файл
        os.remove(filepath)

        return jsonify({
            'text': all_text,
            'engine': engine,
            'filename': filename
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500



if __name__ == '__main__':
    app.run(debug=True)