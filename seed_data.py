import asyncio
import logging
from sqlalchemy import delete, select
from database import async_session, init_db
from models import BellSchedule, Lesson, Profile, SchoolClass

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("SeedData")

# Official Bell Schedule from Gymnasium 16 timetable sheet (synchronized with Google Calendar)
OFFICIAL_BELLS = [
    {"lesson_number": 1, "start_time": "08:15", "end_time": "08:55"},
    {"lesson_number": 2, "start_time": "09:10", "end_time": "09:50"},
    {"lesson_number": 3, "start_time": "10:10", "end_time": "10:50"},
    {"lesson_number": 4, "start_time": "11:10", "end_time": "11:50"},
    {"lesson_number": 5, "start_time": "12:10", "end_time": "12:50"},
    {"lesson_number": 6, "start_time": "13:00", "end_time": "13:40"},
    {"lesson_number": 7, "start_time": "13:50", "end_time": "14:30"},
    {"lesson_number": 8, "start_time": "14:40", "end_time": "15:20"},
]

PROFILES_11A = [
    {"name": "Соц-гум", "description": "Социально-гуманитарный профиль (углубленные история, обществознание)"},
    {"name": "Филологический", "description": "Филологический профиль (углубленные литература, иностранные языки)"}
]

# Lessons for 11A fully synchronized with Google Calendar schedule
LESSONS_11A = [
    # =========================================================
    # ПОНЕДЕЛЬНИК (day_of_week = 0)
    # =========================================================
    {
        "day_of_week": 0, "lesson_number": 1, "class_name": "11А",
        "subject": "Разговоры о важном", "cabinet": "3/109", "teacher_name": "Иванова Е.В.",
        "profile_name": None, "subgroup": None, "note": "Классный час (08:00 - 08:30)"
    },
    {
        "day_of_week": 0, "lesson_number": 2, "class_name": "11А",
        "subject": "Русский язык", "cabinet": "3/109", "teacher_name": "Иванова Е.В.",
        "profile_name": None, "subgroup": None, "note": "Пара (1/2)"
    },
    {
        "day_of_week": 0, "lesson_number": 3, "class_name": "11А",
        "subject": "Русский язык", "cabinet": "3/109", "teacher_name": "Иванова Е.В.",
        "profile_name": None, "subgroup": None, "note": "Пара (2/2)"
    },
    {
        "day_of_week": 0, "lesson_number": 4, "class_name": "11А",
        "subject": "История", "cabinet": "1/226", "teacher_name": "Подкорытова Р.З.",
        "profile_name": "Соц-гум", "subgroup": None, "note": "Углубленный курс"
    },
    {
        "day_of_week": 0, "lesson_number": 4, "class_name": "11А",
        "subject": "Обществознание", "cabinet": "1/225", "teacher_name": "Васильева А.С.",
        "profile_name": "Филологический", "subgroup": None, "note": None
    },
    {
        "day_of_week": 0, "lesson_number": 5, "class_name": "11А",
        "subject": "История", "cabinet": "1/226", "teacher_name": "Подкорытова Р.З.",
        "profile_name": "Соц-гум", "subgroup": None, "note": "Углубленный курс"
    },
    {
        "day_of_week": 0, "lesson_number": 5, "class_name": "11А",
        "subject": "Физика", "cabinet": "1/416", "teacher_name": "Трухина Ю.В.",
        "profile_name": "Филологический", "subgroup": None, "note": None
    },
    {
        "day_of_week": 0, "lesson_number": 6, "class_name": "11А",
        "subject": "Физика", "cabinet": "1/416", "teacher_name": "Трухина Ю.В.",
        "profile_name": None, "subgroup": None, "note": None
    },
    {
        "day_of_week": 0, "lesson_number": 7, "class_name": "11А",
        "subject": "Информатика и ИКТ", "cabinet": "3/314", "teacher_name": "Тольянская В.В.",
        "profile_name": "Соц-гум", "subgroup": None, "note": "IT Lab"
    },
    {
        "day_of_week": 0, "lesson_number": 7, "class_name": "11А",
        "subject": "Литература", "cabinet": "3/109", "teacher_name": "Иванова Е.В.",
        "profile_name": "Филологический", "subgroup": None, "note": None
    },

    # =========================================================
    # ВТОРНИК (day_of_week = 1)
    # =========================================================
    {
        "day_of_week": 1, "lesson_number": 1, "class_name": "11А",
        "subject": "Английский язык", "cabinet": "1/406", "teacher_name": "Бурейкевич Ю.Ю.",
        "profile_name": "Соц-гум", "subgroup": None, "note": None
    },
    {
        "day_of_week": 1, "lesson_number": 1, "class_name": "11А",
        "subject": "Английский язык", "cabinet": "3/305", "teacher_name": "Першина С.Н.",
        "profile_name": "Филологический", "subgroup": None, "note": None
    },
    {
        "day_of_week": 1, "lesson_number": 2, "class_name": "11А",
        "subject": "Английский язык", "cabinet": "1/406", "teacher_name": "Бурейкевич Ю.Ю.",
        "profile_name": "Соц-гум", "subgroup": None, "note": None
    },
    {
        "day_of_week": 1, "lesson_number": 3, "class_name": "11А",
        "subject": "География", "cabinet": "1/222", "teacher_name": "Ушакова И.Н.",
        "profile_name": None, "subgroup": None, "note": "Пара (1/2)"
    },
    {
        "day_of_week": 1, "lesson_number": 4, "class_name": "11А",
        "subject": "География", "cabinet": "1/222", "teacher_name": "Ушакова И.Н.",
        "profile_name": None, "subgroup": None, "note": "Пара (2/2)"
    },
    {
        "day_of_week": 1, "lesson_number": 5, "class_name": "11А",
        "subject": "Вероятность и статистика", "cabinet": "3/306", "teacher_name": "Ермакова М.В.",
        "profile_name": None, "subgroup": None, "note": None
    },
    {
        "day_of_week": 1, "lesson_number": 6, "class_name": "11А",
        "subject": "Алгебра и начала математического анализа", "cabinet": "3/306", "teacher_name": "Ермакова М.В.",
        "profile_name": None, "subgroup": None, "note": None
    },
    {
        "day_of_week": 1, "lesson_number": 7, "class_name": "11А",
        "subject": "ЭК История политической и правовой мысли в России в 2-19 веках", "cabinet": "1/226", "teacher_name": "Подкорытова Р.З.",
        "profile_name": "Соц-гум", "subgroup": None, "note": "Элективный курс"
    },
    {
        "day_of_week": 1, "lesson_number": 7, "class_name": "11А",
        "subject": "ЭК Родная литература 19-20 веков", "cabinet": "3/109", "teacher_name": "Иванова Е.В.",
        "profile_name": "Филологический", "subgroup": None, "note": "Элективный курс"
    },
    {
        "day_of_week": 1, "lesson_number": 8, "class_name": "11А",
        "subject": "Консультация: Русский язык", "cabinet": "3/109", "teacher_name": "Иванова Е.В.",
        "profile_name": None, "subgroup": None, "note": "Консультация 11 А"
    },

    # =========================================================
    # СРЕДА (day_of_week = 2)
    # =========================================================
    {
        "day_of_week": 2, "lesson_number": 1, "class_name": "11А",
        "subject": "Обществознание", "cabinet": "1/226", "teacher_name": "Подкорытова Р.З.",
        "profile_name": "Соц-гум", "subgroup": None, "note": "Пара (1/2)"
    },
    {
        "day_of_week": 2, "lesson_number": 1, "class_name": "11А",
        "subject": "Литература", "cabinet": "3/109", "teacher_name": "Иванова Е.В.",
        "profile_name": "Филологический", "subgroup": None, "note": None
    },
    {
        "day_of_week": 2, "lesson_number": 2, "class_name": "11А",
        "subject": "Обществознание", "cabinet": "1/226", "teacher_name": "Подкорытова Р.З.",
        "profile_name": "Соц-гум", "subgroup": None, "note": "Пара (2/2)"
    },
    {
        "day_of_week": 2, "lesson_number": 3, "class_name": "11А",
        "subject": "Физическая культура", "cabinet": "сп.зал 3", "teacher_name": "Стародубцев Н.Л.",
        "profile_name": None, "subgroup": None, "note": "Пара (1/2)"
    },
    {
        "day_of_week": 2, "lesson_number": 4, "class_name": "11А",
        "subject": "Физическая культура", "cabinet": "сп.зал 3", "teacher_name": "Стародубцев Н.Л.",
        "profile_name": None, "subgroup": None, "note": "Пара (2/2)"
    },
    {
        "day_of_week": 2, "lesson_number": 5, "class_name": "11А",
        "subject": "Геометрия", "cabinet": "3/306", "teacher_name": "Ермакова М.В.",
        "profile_name": None, "subgroup": None, "note": None
    },
    {
        "day_of_week": 2, "lesson_number": 6, "class_name": "11А",
        "subject": "Литература", "cabinet": "3/109", "teacher_name": "Иванова Е.В.",
        "profile_name": "Соц-гум", "subgroup": None, "note": None
    },
    {
        "day_of_week": 2, "lesson_number": 6, "class_name": "11А",
        "subject": "Английский язык", "cabinet": "3/305", "teacher_name": "Першина С.Н.",
        "profile_name": "Филологический", "subgroup": None, "note": None
    },

    # =========================================================
    # ЧЕТВЕРГ (day_of_week = 3)
    # =========================================================
    {
        "day_of_week": 3, "lesson_number": 1, "class_name": "11А",
        "subject": "Английский язык", "cabinet": "1/406", "teacher_name": "Бурейкевич Ю.Ю.",
        "profile_name": "Соц-гум", "subgroup": None, "note": None
    },
    {
        "day_of_week": 3, "lesson_number": 1, "class_name": "11А",
        "subject": "Информатика и ИКТ", "cabinet": "3/314", "teacher_name": "Тольянская В.В.",
        "profile_name": "Филологический", "subgroup": None, "note": None
    },
    {
        "day_of_week": 3, "lesson_number": 2, "class_name": "11А",
        "subject": "ЭК Родной язык в жизни общества", "cabinet": "3/109", "teacher_name": "Иванова Е.В.",
        "profile_name": None, "subgroup": None, "note": "Элективный курс"
    },
    {
        "day_of_week": 3, "lesson_number": 3, "class_name": "11А",
        "subject": "Алгебра и начала математического анализа", "cabinet": "3/306", "teacher_name": "Ермакова М.В.",
        "profile_name": None, "subgroup": None, "note": "Пара (1/2)"
    },
    {
        "day_of_week": 3, "lesson_number": 4, "class_name": "11А",
        "subject": "Алгебра и начала математического анализа", "cabinet": "3/306", "teacher_name": "Ермакова М.В.",
        "profile_name": None, "subgroup": None, "note": "Пара (2/2)"
    },
    {
        "day_of_week": 3, "lesson_number": 5, "class_name": "11А",
        "subject": "История", "cabinet": "1/226", "teacher_name": "Подкорытова Р.З.",
        "profile_name": "Соц-гум", "subgroup": None, "note": None
    },
    {
        "day_of_week": 3, "lesson_number": 5, "class_name": "11А",
        "subject": "История", "cabinet": "1/225", "teacher_name": "Васильева А.С.",
        "profile_name": "Филологический", "subgroup": None, "note": None
    },
    {
        "day_of_week": 3, "lesson_number": 6, "class_name": "11А",
        "subject": "Обществознание", "cabinet": "1/226", "teacher_name": "Подкорытова Р.З.",
        "profile_name": "Соц-гум", "subgroup": None, "note": None
    },
    {
        "day_of_week": 3, "lesson_number": 7, "class_name": "11А",
        "subject": "ЭК Основы маркетинга", "cabinet": "1/226", "teacher_name": "Подкорытова Р.З.",
        "profile_name": "Соц-гум", "subgroup": None, "note": "Элективный курс"
    },
    {
        "day_of_week": 3, "lesson_number": 7, "class_name": "11А",
        "subject": "ЭК Разговорный английский язык", "cabinet": "3/305", "teacher_name": "Першина С.Н.",
        "profile_name": "Филологический", "subgroup": None, "note": "Элективный курс"
    },

    # =========================================================
    # ПЯТНИЦА (day_of_week = 4)
    # =========================================================
    {
        "day_of_week": 4, "lesson_number": 1, "class_name": "11А",
        "subject": "Литература", "cabinet": "3/109", "teacher_name": "Иванова Е.В.",
        "profile_name": "Соц-гум", "subgroup": None, "note": "Пара (1/2)"
    },
    {
        "day_of_week": 4, "lesson_number": 1, "class_name": "11А",
        "subject": "Английский язык", "cabinet": "3/305", "teacher_name": "Першина С.Н.",
        "profile_name": "Филологический", "subgroup": None, "note": None
    },
    {
        "day_of_week": 4, "lesson_number": 2, "class_name": "11А",
        "subject": "Литература", "cabinet": "3/109", "teacher_name": "Иванова Е.В.",
        "profile_name": None, "subgroup": None, "note": "Пара (2/2)"
    },
    {
        "day_of_week": 4, "lesson_number": 3, "class_name": "11А",
        "subject": "Обществознание", "cabinet": "1/226", "teacher_name": "Подкорытова Р.З.",
        "profile_name": "Соц-гум", "subgroup": None, "note": "Пара (1/2)"
    },
    {
        "day_of_week": 4, "lesson_number": 4, "class_name": "11А",
        "subject": "Обществознание", "cabinet": "1/226", "teacher_name": "Подкорытова Р.З.",
        "profile_name": "Соц-гум", "subgroup": None, "note": "Пара (2/2)"
    },
    {
        "day_of_week": 4, "lesson_number": 5, "class_name": "11А",
        "subject": "Химия", "cabinet": "1/411", "teacher_name": "Юрина Т.Ю.",
        "profile_name": None, "subgroup": None, "note": None
    },
    {
        "day_of_week": 4, "lesson_number": 6, "class_name": "11А",
        "subject": "Консультация: Литература", "cabinet": "3/109", "teacher_name": "Иванова Е.В.",
        "profile_name": None, "subgroup": None, "note": "Консультация 11 А"
    },

    # =========================================================
    # СУББОТА (day_of_week = 5)
    # =========================================================
    {
        "day_of_week": 5, "lesson_number": 1, "class_name": "11А",
        "subject": "Консультация по профильной математике", "cabinet": "3/306", "teacher_name": "Ермакова М.В.",
        "profile_name": None, "subgroup": None, "note": "10:00 — 12:00"
    },
    {
        "day_of_week": 5, "lesson_number": 2, "class_name": "11А",
        "subject": "Подготовка к ЕГЭ по информатике", "cabinet": "3/314", "teacher_name": "Тольянская В.В.",
        "profile_name": None, "subgroup": None, "note": "13:00 — 15:00"
    }
]

async def seed():
    logger.info("Initializing database schema...")
    await init_db()

    async with async_session() as session:
        # 1. Update bell schedule with official timings
        logger.info("Seeding official Bell Schedule...")
        await session.execute(delete(BellSchedule))
        for bell in OFFICIAL_BELLS:
            session.add(BellSchedule(
                lesson_number=bell["lesson_number"],
                start_time=bell["start_time"],
                end_time=bell["end_time"],
                is_saturday=False
            ))

        # 2. Seed Classes and Profiles
        logger.info("Seeding Classes (11А..11Ж) and Profiles...")
        from config import DEFAULT_CLASSES, ALL_PROFILES
        await session.execute(delete(SchoolClass))
        for c_name in DEFAULT_CLASSES:
            session.add(SchoolClass(name=c_name))

        await session.execute(delete(Profile))
        for p_name in ALL_PROFILES:
            session.add(Profile(name=p_name))

        # 3. Seed Lessons for 11A
        logger.info(f"Seeding {len(LESSONS_11A)} lessons for 11А...")
        await session.execute(delete(Lesson).where(Lesson.class_name == "11А"))

        for item in LESSONS_11A:
            session.add(Lesson(
                day_of_week=item["day_of_week"],
                lesson_number=item["lesson_number"],
                class_name=item["class_name"],
                subject=item["subject"],
                teacher_name=item["teacher_name"],
                cabinet=item["cabinet"],
                profile_name=item["profile_name"],
                subgroup=item["subgroup"],
                note=item["note"]
            ))

        await session.commit()
        logger.info("✅ Database successfully populated with synchronized 11А schedule, bells, and profiles!")

if __name__ == "__main__":
    asyncio.run(seed())
