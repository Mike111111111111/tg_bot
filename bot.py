from aiogram import Bot, Dispatcher, F, types
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.filters import Command
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import asyncio
import sqlite3
from datetime import datetime

# Конфигурация бота
TOKEN = "7743229312:AAGJpIz6j8YP3n5Rd9x7OkD-Iz9BPZyj6zI"
bot = Bot(token=TOKEN)
dp = Dispatcher()
scheduler = AsyncIOScheduler()

# Подключение к базе данных
db = sqlite3.connect("reminders.db", check_same_thread=False)
cursor = db.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS reminders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    category TEXT,
    title TEXT,
    description TEXT,
    date TEXT
)
""")
db.commit()


# Состояния
class ReminderStates(StatesGroup):
    choosing_category = State()
    adding_title = State()
    adding_description = State()
    adding_date = State()


# Клавиатуры
main_menu = ReplyKeyboardBuilder()
main_menu.button(text="Напоминания")
main_menu.button(text="Планы")
main_menu.button(text="Встречи")
main_menu = main_menu.as_markup(resize_keyboard=True)

add_delete_menu = InlineKeyboardBuilder()
add_delete_menu.button(text="Добавить", callback_data="add")
add_delete_menu.button(text="Удалить все", callback_data="delete_all")
add_delete_menu = add_delete_menu.as_markup()


# Хендлеры
@dp.message(Command("start"))
async def start(message: types.Message):
    await message.answer("Привет! Выбери раздел:", reply_markup=main_menu)


@dp.message(F.text.in_({"Напоминания", "Планы", "Встречи"}))
async def choose_category(message: types.Message, state: FSMContext):
    category = message.text
    await state.update_data(category=category)
    await message.answer(f"Раздел {category}. Что будем делать?", reply_markup=add_delete_menu)
    await state.set_state(ReminderStates.choosing_category)


@dp.callback_query(F.data == "add")
async def add_reminder(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("Введите название:")
    await state.set_state(ReminderStates.adding_title)


@dp.message(ReminderStates.adding_title)
async def set_title(message: types.Message, state: FSMContext):
    await state.update_data(title=message.text)
    await message.answer("Введите описание:")
    await state.set_state(ReminderStates.adding_description)


@dp.message(ReminderStates.adding_description)
async def set_description(message: types.Message, state: FSMContext):
    await state.update_data(description=message.text)
    await message.answer("Введите дату в формате ГГГГ-ММ-ДД ЧЧ:ММ:")
    await state.set_state(ReminderStates.adding_date)


@dp.message(ReminderStates.adding_date)
async def set_date(message: types.Message, state: FSMContext):
    try:
        reminder_date = datetime.strptime(message.text, "%Y-%m-%d %H:%M")
        if reminder_date <= datetime.now():
            await message.answer("Дата и время должны быть в будущем. Попробуйте снова.")
            return

        data = await state.get_data()
        cursor.execute("""
        INSERT INTO reminders (user_id, category, title, description, date) 
        VALUES (?, ?, ?, ?, ?)
        """, (message.from_user.id, data["category"], data["title"], data["description"], reminder_date))
        db.commit()

        # Добавляем напоминание в шедулер
        scheduler.add_job(
            send_reminder,
            trigger="date",
            run_date=reminder_date,
            args=[message.from_user.id, data["title"], data["description"], cursor.lastrowid]
        )

        await message.answer("Успешно добавлено!", reply_markup=main_menu)
        await state.clear()
    except ValueError:
        await message.answer("Неверный формат даты. Используйте формат ГГГГ-ММ-ДД ЧЧ:ММ.")


async def send_reminder(user_id: int, title: str, description: str, reminder_id: int):
    try:
        await bot.send_message(user_id, f"🔔 Напоминание:\n\n*{title}*\n{description}", parse_mode="Markdown")
        # Удаляем напоминание из базы данных после отправки
        cursor.execute("DELETE FROM reminders WHERE id = ?", (reminder_id,))
        db.commit()
    except Exception as e:
        print(f"Ошибка при отправке напоминания: {e}")


@dp.callback_query(F.data == "delete_all")
async def delete_all_reminders(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    category = data["category"]
    cursor.execute("DELETE FROM reminders WHERE user_id = ? AND category = ?", (callback.from_user.id, category))
    db.commit()
    scheduler.remove_all_jobs()
    await load_reminders()
    await callback.message.answer(f"Все напоминания из раздела {category} удалены!", reply_markup=main_menu)
    await state.clear()


# Загрузка напоминаний из базы данных в шедулер при запуске
async def load_reminders():
    cursor.execute("SELECT id, user_id, title, description, date FROM reminders")
    rows = cursor.fetchall()
    for row in rows:
        reminder_id, user_id, title, description, date_str = row
        reminder_date = datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S")
        if reminder_date > datetime.now():
            scheduler.add_job(
                send_reminder,
                trigger="date",
                run_date=reminder_date,
                args=[user_id, title, description, reminder_id]
            )
        else:
            # Удаляем просроченные напоминания из базы
            cursor.execute("DELETE FROM reminders WHERE id = ?", (reminder_id,))
            db.commit()


# Запуск бота
async def main():
    await load_reminders()
    scheduler.start()
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
