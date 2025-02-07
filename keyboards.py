import os

from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton

# Create a keyboard with "Start Purchase" and "Go Back" buttons
purchase_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text = "🛒 Купить")],
        [KeyboardButton(text = "🆘 Запрос в поддержку")]
    ],
    resize_keyboard=True
)

purchase_inline_keyboard = InlineKeyboardMarkup(
    inline_keyboard=[
        [InlineKeyboardButton(text="🛒 Купить через Kaspi", url=os.getenv("KASPI_QR"))]
    ]
)

support_builder_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="❓ Чек не распознается")],
        [KeyboardButton(text="❓ Я не получил ссылки")],
        [KeyboardButton(text="❓ Другое")],
        [KeyboardButton(text="🚫 Отмена")],
    ],
    resize_keyboard=True
)