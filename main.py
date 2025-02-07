import asyncio
import io
import logging

import aiofiles
import pytesseract
import os
import PyPDF2
import aiosqlite
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery
from pdf2image import convert_from_path
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web
import hashlib

from database import init_db
from keyboards import purchase_keyboard, purchase_inline_keyboard, support_builder_keyboard

TOKEN = os.getenv("TOKEN")

HEROKU_APP_NAME = os.getenv('telepay-production-app')

# webhook settings
WEBHOOK_HOST = f'https://{HEROKU_APP_NAME}.herokuapp.com'
WEBHOOK_PATH = f'/webhook/{TOKEN}'
WEBHOOK_URL = f'{WEBHOOK_HOST}{WEBHOOK_PATH}'

# webserver settings
WEBAPP_HOST = '0.0.0.0'
WEBAPP_PORT = int(os.getenv('PORT', default=8000))

PAYMENT_AMOUNT = os.getenv("PAYMENT_AMOUNT") # Цена товара
STORE_NAME = os.getenv("STORE_NAME") # Название магазина
SELLER_BIN = os.getenv("SELLER_BIN") # БИН/ИИН Продавца
ADMIN_ID = os.getenv("ADMIN_ID") # USER_ID Админа в телеграм (бот отправляет подозрительную активность)
KASPI_QR = os.getenv("KASPI_QR") # ссылка для оплаты
os.environ["TESSDATA_PREFIX"] = os.getenv("TESSDATA_PREFIX", "/app/.apt/usr/share/tesseract-ocr/4.00/tessdata")
os.makedirs("downloads", exist_ok=True)
bot = Bot(token=TOKEN)
dp = Dispatcher()

class SupportStates(StatesGroup):
    support_message = State()

# --- Логирование ---
logging.basicConfig(level=logging.INFO)

@dp.message(Command("start"))
async def send_welcome(message: Message):
    """Приветственное сообщение"""
    await message.answer("Приветствие!", reply_markup=purchase_keyboard)

@dp.message(lambda message: message.text == "🛒 Купить")
async def start_purchase(message: Message):
    await message.answer(
        f"🔹 Оплатите *{PAYMENT_AMOUNT} KZT* через Kaspi QR\n\n"
        f"📎 {KASPI_QR}\n\n"
        "После оплаты PDF-файл чека 📎",
        reply_markup=purchase_inline_keyboard,
        parse_mode="Markdown"
    )

@dp.message(lambda message: message.document and message.document.mime_type == "application/pdf")
async def check_receipt(message: Message):
    """Проверка PDF-чека"""
    user_id = message.from_user.id
    username = message.from_user.username

    # --- Скачивание PDF-файла ---
    file_id = message.document.file_id
    file = await bot.get_file(file_id)

    pdf_path = f"downloads/receipt_{user_id}.pdf"

    try:
        # --- Скачивание PDF-файла в память ---
        file_bytes = io.BytesIO()
        await bot.download_file(file.file_path, file_bytes)
        file_bytes.seek(0)  # Вернуть курсор в начало файла

        # --- Асинхронная запись в файл ---
        async with aiofiles.open(pdf_path, "wb") as f:
            await f.write(file_bytes.read())
    except Exception as e:
        await message.answer("❌ Ошибка! Не удалось скачать PDF-файл.", reply_markup=purchase_keyboard)
        return

    # --- Конвертация PDF в изображение ---
    try:
        images = convert_from_path(pdf_path)
        if not images:
            await message.answer("❌ Ошибка! Не удалось обработать PDF-файл.", reply_markup=purchase_keyboard)
            return

        img_path = f"downloads/receipt_{user_id}.png"
        images[0].save(img_path, "PNG")

        # --- Распознавание текста ---
        text = pytesseract.image_to_string(img_path, lang="rus+eng").lower()
        logging.info(f"📜 Распознанный текст: {text}")

        # --- Хеширование текста ---
        text_hash = hashlib.sha256(text.encode()).hexdigest()

        # --- Проверка на дубликат ---
        async with aiosqlite.connect('receipts.db') as db:
            async with db.execute('SELECT 1 FROM receipts WHERE text_hash = ?', (text_hash,)) as cursor:
                if await cursor.fetchone():
                    await message.answer("❌ Ошибка! Дубликат чека.", reply_markup=purchase_keyboard)
                    return

        # --- Проверка данных в чеке ---
        if (
                STORE_NAME.lower() in text and
                SELLER_BIN in text and
                str(PAYMENT_AMOUNT) in text and
                await check_pdf_metadata(pdf_path)
        ):
            await message.answer("✅ Оплата подтверждена!")
            await message.answer("🎉 Спасибо за покупку!")
            await message.answer("LINK")
            # --- Сохранение данных в базу данных ---
            async with aiosqlite.connect('receipts.db') as db:
                await db.execute('''
                    INSERT INTO receipts (user_id, username, text_hash)
                    VALUES (?, ?, ?)
                ''', (user_id, username, text_hash))
                await db.commit()
        else:
            await message.answer("❌ Ошибка! Чек не распознан или содержит неверные данные.")
            await bot.send_document(
                ADMIN_ID,
                document=message.document.file_id,
                caption=f"⚠ Подозрительный чек от @{username}!"
            )

    except Exception as e:
        logging.error(f"Ошибка обработки PDF: {e}")
        await message.answer("🚨 Произошла ошибка при проверке чека.", reply_markup=purchase_keyboard)

    finally:
        # Чистим файлы после обработки
        os.remove(pdf_path)
        if os.path.exists(img_path):
            os.remove(img_path)

async def check_pdf_metadata(pdf_path: str):
    """Проверяет метаданные PDF-файла"""
    try:
        async with aiofiles.open(pdf_path, "rb") as f:
            content = await f.read()

        reader = PyPDF2.PdfReader(pdf_path)
        metadata = reader.metadata

        # П��оверяем, совпадает ли Producer (Kaspi или WeasyPrint)
        if metadata and metadata.get('/Producer', '') == "WeasyPrint 62.3" and metadata.get('/Title', '') == "Чек":
            logging.info("✅ Producer check passed.")
            return True
        else:
            logging.warning(f"⚠ Producer check failed: {metadata}")
            return False

    except Exception as e:
        logging.error(f"Ошибка при проверке PDF-метаданных: {e}")
        return False

@dp.message(F.text == "🆘 Запрос в поддержку")
async def handle_support_callback(message: Message):
    await message.answer("🆘 Как мы можем вам помочь?", reply_markup=support_builder_keyboard)

@dp.message(F.text.in_({"❓ Чек не распознается", "❓ Я не получил ссылки", "❓ Другое"}))
async def handle_support_builder_callback(message: Message, state: FSMContext):
    """Обработка выбора в поддержке"""
    if message.text == "🚫 Отмена":
        await state.clear()
        await message.answer("✅ Операция отменена", reply_markup=purchase_keyboard)
        return
    button_text = message.text
    await state.update_data(support_title=button_text)
    await message.answer("Пожалуйста, напишите дополн��тельный текст для сообщения в поддержку.")
    await state.set_state(SupportStates.support_message)

@dp.message(SupportStates.support_message)
async def handle_additional_text(message: Message, state: FSMContext):
    """Обработка дополнительного текста для сообщения в поддержку"""
    if message.text == "🚫 Отмена":
        await state.clear()
        await message.answer("✅ Операция отменена", reply_markup=purchase_keyboard)
        return
    user_data = await state.get_data()
    support_title = user_data.get('support_title')
    additional_text = message.text

    support_message = f"📢 Запрос в поддержку\n\n" \
                      f"🔹 Заголовок: {support_title}\n" \
                      f"🔹 Пользователь: @{message.from_user.username}\n" \
                      f"🔹 Сообщение: {additional_text}"

    await bot.send_message(ADMIN_ID, support_message)
    await message.answer("Ваше сообщение в поддержку отправлено.", reply_markup=purchase_keyboard)
    await state.clear()

async def on_startup(dispatcher):
    await bot.set_webhook(WEBHOOK_URL, drop_pending_updates=True)
    await init_db()

async def on_shutdown(dispatcher):
    await bot.delete_webhook()

async def main():
    app = web.Application()
    SimpleRequestHandler(dispatcher=dp, bot=bot).register(app, path=WEBHOOK_PATH)
    setup_application(app, dp, bot=bot)
    app.on_startup.append(on_startup)
    app.on_shutdown.append(on_shutdown)
    return app

if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    web.run_app(main(), host=WEBAPP_HOST, port=WEBAPP_PORT)