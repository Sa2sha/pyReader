import os
import io
import base64

# Для веб-сервера
from flask import Flask, request, render_template, jsonify

# Для работы с изображениями
from PIL import Image, ImageEnhance, ImageFilter
import numpy as np

# Для OCR
import pytesseract
import easyocr

# Для PDF
import fitz

# Для БД
import psycopg2

app = Flask(__name__)

# БД
DB_CONFIG = {
    'host': 'localhost',
    'port': 5432,
    'database': 'ocr_database', # Название БД
    'user': 'postgres',
    'password': '5503' # Пароль, который указывали при создании БД
}


def save_to_database(text, photo):
    conn = None
    cursor = None

    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cursor = conn.cursor()

        cursor.execute(
            """
            INSERT INTO documents (text, photo)
            VALUES (%s, %s)
            RETURNING id
            """,
            (text, psycopg2.Binary(photo))
        )

        document_id = cursor.fetchone()[0]
        conn.commit()

        return document_id

    except Exception as e:
        print(f"БД недоступна, результат не сохранён: {e}")
        return None

    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

# История
def get_history():
    conn = None
    cursor = None

    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT id, text
            FROM documents
            ORDER BY id DESC
        """)

        rows = cursor.fetchall()

        history = []

        for row in rows:
            history.append({
                'id': row[0],
                'text': row[1]
            })

        return history

    except Exception as e:
        print(f"БД недоступна, история недоступна: {e}")
        return []

    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

pytesseract.pytesseract.tesseract_cmd = r"D:\Tesseract-OCR\tesseract.exe"

# Папка для временных файлов
UPLOAD_FOLDER = 'uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Разрешенные форматы
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'pdf'}

easyocr_reader = None
easyocr_languages = None

# Глобальная переменная для хранения загруженного изображения
current_image = None


def preprocess_image(image, contrast=2.0, brightness=1.0, threshold=128,
                     apply_denoise=False, apply_sharpen=False, apply_binarization=False):
    """
    Подготовка изображения для лучшего распознавания
    """
    # Конвертируем в оттенки серого
    if image.mode != 'L':
        image = image.convert('L')

    # Яркость
    enhancer = ImageEnhance.Brightness(image)
    image = enhancer.enhance(float(brightness))

    # Контраст
    enhancer = ImageEnhance.Contrast(image)
    image = enhancer.enhance(float(contrast))

    # Увеличение изображения
    width, height = image.size
    if width < 1500:
        scale = 2
        image = image.resize((width * scale, height * scale), Image.LANCZOS)

    # Удаление шума
    if apply_denoise:
        image = image.filter(ImageFilter.MedianFilter(size=5))

    # Повышение резкости
    if apply_sharpen:
        image = image.filter(ImageFilter.UnsharpMask(radius=2, percent=200, threshold=3))

    # Бинаризация
    if apply_binarization:
        image = image.point(lambda x: 255 if x > int(threshold) else 0)

    return image


def find_text_area(image, padding=10, threshold_white=250):
    """
    Определяем область с текстом и обрезаем пустые поля
    """
    img_array = np.array(image)

    non_white = np.where(img_array < int(threshold_white))

    if len(non_white[0]) > 0 and len(non_white[1]) > 0:
        top = non_white[0].min()
        bottom = non_white[0].max()
        left = non_white[1].min()
        right = non_white[1].max()

        image = image.crop((
            max(0, left - int(padding)),
            max(0, top - int(padding)),
            right + int(padding),
            bottom + int(padding)
        ))

    return image


def clean_text(text, chars_to_remove='~][|'):
    """
    Очистка текста от артефактов
    """
    artifact_map = str.maketrans('', '', chars_to_remove)
    return text.translate(artifact_map).strip()


def ocr_tesseract(image, config=None):
    """
    Распознавание через Tesseract с настройками
    """
    if config is None:
        config = {}

    lang = config.get('lang', 'rus+eng')
    psm = config.get('psm', '3')
    oem = config.get('oem', '3')

    tess_config = f'--psm {psm} --oem {oem}'

    text = pytesseract.image_to_string(
        image,
        lang=lang,
        config=tess_config
    )

    return text


def ocr_easyocr(image, config=None):
    """
    Распознавание через EasyOCR с настройками
    """
    global easyocr_reader
    global easyocr_languages

    if config is None:
        config = {}

    # Настройки EasyOCR
    lang = config.get('lang', 'rus+eng')
    text_threshold = float(config.get('text_threshold', 0.4))
    low_text = float(config.get('low_text', 0.2))
    add_margin = float(config.get('add_margin', 0.2))
    width_ths = float(config.get('width_ths', 0.5))
    contrast_ths = float(config.get('contrast_ths', 0.05))
    adjust_contrast = float(config.get('adjust_contrast', 0.8))
    detail = int(config.get('detail', 0))
    paragraph = config.get('paragraph', True)

    # Определяем языки для EasyOCR
    if lang == 'rus+eng':
        languages = ['ru', 'en']
    elif lang == 'rus':
        languages = ['ru']
    elif lang == 'eng':
        languages = ['en']
    else:
        languages = ['ru', 'en']

    # Пересоздаем reader если языки изменились
    if easyocr_reader is None or easyocr_languages != tuple(languages):
        easyocr_reader = easyocr.Reader(languages, gpu=False)
        easyocr_languages = tuple(languages)

    img_array = np.array(image)

    result = easyocr_reader.readtext(
        img_array,
        decoder='beamsearch',
        beamWidth=10,
        detail=detail,
        paragraph=paragraph,
        text_threshold=text_threshold,
        low_text=low_text,
        add_margin=add_margin,
        width_ths=width_ths,
        contrast_ths = contrast_ths,
        adjust_contrast = adjust_contrast
    )


    return '\n'.join(result)


def process_image(image, engine='tesseract', ocr_config=None, preprocess_config=None):
    """
    Обработка изображения и распознавание текста
    """
    if preprocess_config is None:
        preprocess_config = {}

    # Настройки предобработки
    contrast = preprocess_config.get('contrast', 2.0)
    brightness = preprocess_config.get('brightness', 1.0)
    threshold = preprocess_config.get('threshold', 128)
    padding = preprocess_config.get('padding', 10)
    white_threshold = preprocess_config.get('white_threshold', 250)
    apply_denoise = preprocess_config.get('apply_denoise', False)
    apply_sharpen = preprocess_config.get('apply_sharpen', False)

    # Настройки очистки
    chars_to_remove = preprocess_config.get('chars_to_remove', '~][|')

    # Обработка
    image = find_text_area(image, padding, white_threshold)

    # Распознавание
    if engine == 'easyocr':
        image = preprocess_image(image, contrast, brightness, threshold, apply_denoise, apply_sharpen, False)
        text = ocr_easyocr(image, ocr_config)
    else:
        image = preprocess_image(image, contrast, brightness, threshold, apply_denoise, apply_sharpen, True)
        text = ocr_tesseract(image, ocr_config)

    # Очистка текста
    text = clean_text(text, chars_to_remove)

    return text


def pdf_to_images(pdf_path):
    """Конвертируем PDF в список изображений"""
    doc = fitz.open(pdf_path)
    images = []

    for page in doc:
        pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
        img_data = pix.tobytes("png")
        img = Image.open(io.BytesIO(img_data))
        images.append(img)

    doc.close()
    return images


def image_to_base64(image):
    """Конвертируем PIL Image в base64 для отображения в HTML"""
    buffered = io.BytesIO()
    image.save(buffered, format="PNG")
    img_str = base64.b64encode(buffered.getvalue()).decode()
    return f"data:image/png;base64,{img_str}"


@app.route('/')
def index():
    """Главная страница"""
    return render_template('index.html')


@app.route('/upload_image', methods=['POST'])
def upload_image():
    """Загрузка изображения на сервер (для предпросмотра)"""
    global current_image

    try:
        if 'file' not in request.files:
            return jsonify({'error': 'Файл не найден'}), 400

        file = request.files['file']

        if file.filename == '':
            return jsonify({'error': 'Файл не выбран'}), 400

        ext = file.filename.rsplit('.', 1)[1].lower() if '.' in file.filename else ''
        if ext not in ALLOWED_EXTENSIONS:
            return jsonify({'error': 'Неверный формат файла'}), 400

        file_bytes = file.read()

        if ext == 'pdf':
            filepath = os.path.join(UPLOAD_FOLDER, file.filename)
            with open(filepath, 'wb') as f:
                f.write(file_bytes)

            images = pdf_to_images(filepath)
            if images:
                current_image = images[0]
            os.remove(filepath)
        else:
            current_image = Image.open(io.BytesIO(file_bytes))

        return jsonify({
            'preview': image_to_base64(current_image)
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/preview', methods=['POST'])
def preview():
    """Предпросмотр обработанного изображения"""
    global current_image

    try:
        if current_image is None:
            return jsonify({'error': 'Изображение не загружено'}), 400

        # Получаем настройки предобработки
        contrast = float(request.form.get('contrast', '2.0'))
        brightness = float(request.form.get('brightness', '1.0'))
        threshold = int(request.form.get('threshold', '128'))
        padding = int(request.form.get('padding', '10'))
        white_threshold = int(request.form.get('white_threshold', '250'))
        apply_denoise = request.form.get('apply_denoise', 'false').lower() == 'true'
        apply_sharpen = request.form.get('apply_sharpen', 'false').lower() == 'true'
        engine = request.form.get('engine', 'tesseract')

        # Копируем изображение
        img = current_image.copy()

        # Находим область текста
        img = find_text_area(img, padding, white_threshold)

        if engine == 'easyocr':
            apply_binarization = False
        else:
            apply_binarization = True

        # Применяем обработку
        img = preprocess_image(img, contrast, brightness, threshold, apply_denoise, apply_sharpen, apply_binarization)

        return jsonify({
            'preview': image_to_base64(img)
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/upload', methods=['POST'])
def upload():
    """Обработка загрузки файла и распознавание"""
    global current_image

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

        # Настройки OCR
        ocr_config = {
            'lang': request.form.get('language', 'rus+eng')
        }

        # Добавляем специфичные настройки для движков
        if engine == 'tesseract':
            ocr_config['psm'] = request.form.get('layout', '3')
            ocr_config['oem'] = request.form.get('oem', '3')
        elif engine == 'easyocr':
            ocr_config['text_threshold'] = request.form.get('text_threshold', '0.4')
            ocr_config['low_text'] = request.form.get('low_text', '0.2')
            ocr_config['add_margin'] = request.form.get('add_margin', '0.2')
            ocr_config['width_ths'] = request.form.get('width_ths', '0.5')
            ocr_config['paragraph'] = request.form.get('paragraph', 'true').lower() == 'true'
            ocr_config['contrast_ths'] = request.form.get('contrast_ths', '0.05')
            ocr_config['adjust_contrast'] = request.form.get('adjust_contrast', '0.8')

        # Настройки предобработки
        preprocess_config = {
            'contrast': float(request.form.get('contrast', '2.0')),
            'brightness': float(request.form.get('brightness', '1.0')),
            'threshold': int(request.form.get('threshold', '128')),
            'padding': int(request.form.get('padding', '10')),
            'white_threshold': int(request.form.get('white_threshold', '250')),
            'apply_denoise': request.form.get('apply_denoise', 'false').lower() == 'true',
            'apply_sharpen': request.form.get('apply_sharpen', 'false').lower() == 'true',
            'chars_to_remove': request.form.get('chars_to_remove', '~][|')
        }

        filename = file.filename
        file_bytes = file.read()

        all_text = ""

        if ext == 'pdf':
            filepath = os.path.join(UPLOAD_FOLDER, filename)
            with open(filepath, 'wb') as f:
                f.write(file_bytes)

            images = pdf_to_images(filepath)
            for i, img in enumerate(images):
                page_text = process_image(img, engine, ocr_config, preprocess_config)
                all_text += page_text

                if i == 0:
                    current_image = img

            os.remove(filepath)
        else:
            image = Image.open(io.BytesIO(file_bytes))
            current_image = image
            all_text = process_image(image, engine, ocr_config, preprocess_config)

        # file_bytes - байты файла (можно сохранить в БД)
        # all_text - распознанный текст
        # filename - имя файла
        # engine - какой OCR использовался

        # Пытаемся сохранить результат в PostgreSQL
        document_id = save_to_database(all_text, file_bytes)

        return jsonify({
            'id': document_id,
            'text': all_text,
            'engine': engine,
            'filename': filename,
            'file_size': len(file_bytes),
            'saved_to_database': document_id is not None
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/history', methods=['GET'])
def history():
    try:
        history_data = get_history()

        return jsonify({
            'history': history_data
        })

    except Exception as e:
        return jsonify({
            'error': str(e)
        }), 500


if __name__ == '__main__':
    app.run(debug=True)


