import asyncio
import logging
from sqlalchemy import select
from config import settings
from database import async_session, init_db
from models import BellSchedule, Lesson, Profile, SchoolClass, User

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

# Legacy class sheet. The reviewed 11А Soc-gum calendar snapshot is applied below.
LESSONS_11A = [
    # =========================================================
    # ПОНЕДЕЛЬНИК (day_of_week = 0) 1–8 УРОКИ
    # =========================================================
    {
        "day_of_week": 0, "lesson_number": 1, "class_name": "11А",
        "subject": "Разговоры о важном", "cabinet": "3/109", "teacher_name": "Иванова Е. В.",
        "profile_name": None, "subgroup": None, "note": "08:15 – 08:55"
    },
    {
        "day_of_week": 0, "lesson_number": 2, "class_name": "11А",
        "subject": "Русский язык", "cabinet": "3/109", "teacher_name": "Иванова Е. В.",
        "profile_name": None, "subgroup": None, "note": "09:10 – 09:50"
    },
    {
        "day_of_week": 0, "lesson_number": 3, "class_name": "11А",
        "subject": "Русский язык", "cabinet": "3/109", "teacher_name": "Иванова Е. В.",
        "profile_name": None, "subgroup": None, "note": "10:10 – 10:50"
    },
    {
        "day_of_week": 0, "lesson_number": 4, "class_name": "11А",
        "subject": "Обществознание", "cabinet": "1/225", "teacher_name": "Васильева А. С.",
        "profile_name": "Филологический", "subgroup": None, "note": "11:10 – 11:50"
    },
    {
        "day_of_week": 0, "lesson_number": 4, "class_name": "11А",
        "subject": "История", "cabinet": "1/226", "teacher_name": "Подкорытова Р. З.",
        "profile_name": "Соц-гум", "subgroup": None, "note": "11:10 – 11:50"
    },
    {
        "day_of_week": 0, "lesson_number": 5, "class_name": "11А",
        "subject": "Обществознание", "cabinet": "1/225", "teacher_name": "Васильева А. С.",
        "profile_name": "Филологический", "subgroup": None, "note": "12:10 – 12:50"
    },
    {
        "day_of_week": 0, "lesson_number": 5, "class_name": "11А",
        "subject": "История", "cabinet": "1/226", "teacher_name": "Подкорытова Р. З.",
        "profile_name": "Соц-гум", "subgroup": None, "note": "12:10 – 12:50"
    },
    {
        "day_of_week": 0, "lesson_number": 6, "class_name": "11А",
        "subject": "Физика", "cabinet": "1/416", "teacher_name": "Трухина Ю. В.",
        "profile_name": None, "subgroup": None, "note": "13:00 – 13:40"
    },
    {
        "day_of_week": 0, "lesson_number": 7, "class_name": "11А",
        "subject": "Физика", "cabinet": "1/416", "teacher_name": "Трухина Ю. В.",
        "profile_name": None, "subgroup": None, "note": "13:50 – 14:30"
    },
    {
        "day_of_week": 0, "lesson_number": 8, "class_name": "11А",
        "subject": "Литература", "cabinet": "3/109", "teacher_name": "Иванова Е. В.",
        "profile_name": "Филологический", "subgroup": None, "note": "14:40 – 15:20"
    },
    {
        "day_of_week": 0, "lesson_number": 8, "class_name": "11А",
        "subject": "Информатика и ИКТ", "cabinet": "3/314", "teacher_name": "Тольянская В. В.",
        "profile_name": "Соц-гум", "subgroup": None, "note": "14:40 – 15:20"
    },

    # =========================================================
    # ВТОРНИК (day_of_week = 1) 1–8 УРОКИ
    # =========================================================
    {
        "day_of_week": 1, "lesson_number": 1, "class_name": "11А",
        "subject": "Английский язык", "cabinet": "3/105", "teacher_name": "Першина С. Н.",
        "profile_name": "Филологический", "subgroup": None, "note": "08:15 – 08:55"
    },
    {
        "day_of_week": 1, "lesson_number": 1, "class_name": "11А",
        "subject": "Английский язык", "cabinet": "1/406", "teacher_name": "Буракевич Ю. Ю.",
        "profile_name": "Соц-гум", "subgroup": None, "note": "08:15 – 08:55"
    },
    {
        "day_of_week": 1, "lesson_number": 2, "class_name": "11А",
        "subject": "Английский язык", "cabinet": "3/105", "teacher_name": "Першина С. Н.",
        "profile_name": "Филологический", "subgroup": None, "note": "09:10 – 09:50"
    },
    {
        "day_of_week": 1, "lesson_number": 2, "class_name": "11А",
        "subject": "Английский язык", "cabinet": "1/406", "teacher_name": "Буракевич Ю. Ю.",
        "profile_name": "Соц-гум", "subgroup": None, "note": "09:10 – 09:50"
    },
    {
        "day_of_week": 1, "lesson_number": 3, "class_name": "11А",
        "subject": "География", "cabinet": "1/222", "teacher_name": "Ушакова И. Н.",
        "profile_name": None, "subgroup": None, "note": "10:10 – 10:50"
    },
    {
        "day_of_week": 1, "lesson_number": 4, "class_name": "11А",
        "subject": "География", "cabinet": "1/222", "teacher_name": "Ушакова И. Н.",
        "profile_name": None, "subgroup": None, "note": "11:10 – 11:50"
    },
    {
        "day_of_week": 1, "lesson_number": 5, "class_name": "11А",
        "subject": "Вероятность и статистика", "cabinet": "3/306", "teacher_name": "Ермакова М. В.",
        "profile_name": None, "subgroup": None, "note": "12:10 – 12:50"
    },
    {
        "day_of_week": 1, "lesson_number": 6, "class_name": "11А",
        "subject": "Алгебра и начала мат. анализа", "cabinet": "3/306", "teacher_name": "Ермакова М. В.",
        "profile_name": None, "subgroup": None, "note": "13:00 – 13:40"
    },
    {
        "day_of_week": 1, "lesson_number": 7, "class_name": "11А",
        "subject": "ЭК Родная лит. 19-20 вв.", "cabinet": "3/109", "teacher_name": "Иванова Е. В.",
        "profile_name": "Филологический", "subgroup": None, "note": "13:50 – 14:30"
    },
    {
        "day_of_week": 1, "lesson_number": 7, "class_name": "11А",
        "subject": "ЭК Ист. пол. мысли", "cabinet": "1/226", "teacher_name": "Подкорытова Р. З.",
        "profile_name": "Соц-гум", "subgroup": None, "note": "13:50 – 14:30"
    },
    {
        "day_of_week": 1, "lesson_number": 8, "class_name": "11А",
        "subject": "Консультация по русскому языку (11 «А»)", "cabinet": "3/109", "teacher_name": "Иванова Е. В.",
        "profile_name": None, "subgroup": None, "note": "14:40 – 15:20"
    },

    # =========================================================
    # СРЕДА (day_of_week = 2) 1–7 УРОКИ
    # =========================================================
    {
        "day_of_week": 2, "lesson_number": 1, "class_name": "11А",
        "subject": "Литература", "cabinet": "3/109", "teacher_name": "Иванова Е. В.",
        "profile_name": "Филологический", "subgroup": None, "note": "08:15 – 08:55"
    },
    {
        "day_of_week": 2, "lesson_number": 1, "class_name": "11А",
        "subject": "Обществознание", "cabinet": "1/226", "teacher_name": "Подкорытова Р. З.",
        "profile_name": "Соц-гум", "subgroup": None, "note": "08:15 – 08:55"
    },
    {
        "day_of_week": 2, "lesson_number": 2, "class_name": "11А",
        "subject": "Литература", "cabinet": "3/109", "teacher_name": "Иванова Е. В.",
        "profile_name": "Филологический", "subgroup": None, "note": "09:10 – 09:50"
    },
    {
        "day_of_week": 2, "lesson_number": 2, "class_name": "11А",
        "subject": "Обществознание", "cabinet": "1/226", "teacher_name": "Подкорытова Р. З.",
        "profile_name": "Соц-гум", "subgroup": None, "note": "09:10 – 09:50"
    },
    {
        "day_of_week": 2, "lesson_number": 3, "class_name": "11А",
        "subject": "Физическая культура", "cabinet": "спортзал 3", "teacher_name": "Стародубцев Н. Л.",
        "profile_name": None, "subgroup": None, "note": "10:10 – 10:50"
    },
    {
        "day_of_week": 2, "lesson_number": 4, "class_name": "11А",
        "subject": "Физическая культура", "cabinet": "спортзал 3", "teacher_name": "Стародубцев Н. Л.",
        "profile_name": None, "subgroup": None, "note": "11:10 – 11:50"
    },
    {
        "day_of_week": 2, "lesson_number": 5, "class_name": "11А",
        "subject": "Алгебра и начала мат. анализа", "cabinet": "3/306", "teacher_name": "Ермакова М. В.",
        "profile_name": None, "subgroup": None, "note": "12:10 – 12:50"
    },
    {
        "day_of_week": 2, "lesson_number": 6, "class_name": "11А",
        "subject": "Алгебра и начала мат. анализа", "cabinet": "3/306", "teacher_name": "Ермакова М. В.",
        "profile_name": None, "subgroup": None, "note": "13:00 – 13:40"
    },
    {
        "day_of_week": 2, "lesson_number": 7, "class_name": "11А",
        "subject": "Английский язык", "cabinet": "3/305", "teacher_name": "Першина С. Н.",
        "profile_name": "Филологический", "subgroup": None, "note": "13:50 – 14:30"
    },
    {
        "day_of_week": 2, "lesson_number": 7, "class_name": "11А",
        "subject": "Литература", "cabinet": "3/109", "teacher_name": "Иванова Е. В.",
        "profile_name": "Соц-гум", "subgroup": None, "note": "13:50 – 14:30"
    },

    # =========================================================
    # ЧЕТВЕРГ (day_of_week = 3) 1–6 УРОКИ
    # =========================================================
    {
        "day_of_week": 3, "lesson_number": 1, "class_name": "11А",
        "subject": "Информатика и ИКТ", "cabinet": "3/314", "teacher_name": "Тольянская В. В.",
        "profile_name": "Филологический", "subgroup": None, "note": "08:15 – 08:55"
    },
    {
        "day_of_week": 3, "lesson_number": 1, "class_name": "11А",
        "subject": "Английский язык", "cabinet": "1/406", "teacher_name": "Буракевич Ю. Ю.",
        "profile_name": "Соц-гум", "subgroup": None, "note": "08:15 – 08:55"
    },
    {
        "day_of_week": 3, "lesson_number": 2, "class_name": "11А",
        "subject": "ЭК Родной язык в жизни общества", "cabinet": "3/109", "teacher_name": "Иванова Е. В.",
        "profile_name": None, "subgroup": None, "note": "09:10 – 09:50"
    },
    {
        "day_of_week": 3, "lesson_number": 3, "class_name": "11А",
        "subject": "Геометрия", "cabinet": "3/306", "teacher_name": "Ермакова М. В.",
        "profile_name": None, "subgroup": None, "note": "10:10 – 10:50"
    },
    {
        "day_of_week": 3, "lesson_number": 4, "class_name": "11А",
        "subject": "Геометрия", "cabinet": "3/306", "teacher_name": "Ермакова М. В.",
        "profile_name": None, "subgroup": None, "note": "11:10 – 11:50"
    },
    {
        "day_of_week": 3, "lesson_number": 5, "class_name": "11А",
        "subject": "История", "cabinet": "1/225", "teacher_name": "Васильева А. С.",
        "profile_name": "Филологический", "subgroup": None, "note": "12:10 – 12:50"
    },
    {
        "day_of_week": 3, "lesson_number": 5, "class_name": "11А",
        "subject": "История", "cabinet": "1/226", "teacher_name": "Подкорытова Р. З.",
        "profile_name": "Соц-гум", "subgroup": None, "note": "12:10 – 12:50"
    },
    {
        "day_of_week": 3, "lesson_number": 6, "class_name": "11А",
        "subject": "ЭК Разговорный англ. яз.", "cabinet": "3/305", "teacher_name": "Першина С. Н.",
        "profile_name": "Филологический", "subgroup": None, "note": "13:00 – 13:40"
    },
    {
        "day_of_week": 3, "lesson_number": 6, "class_name": "11А",
        "subject": "ЭК Основы маркетинга", "cabinet": "1/226", "teacher_name": "Подкорытова Р. З.",
        "profile_name": "Соц-гум", "subgroup": None, "note": "13:00 – 13:40"
    },

    # =========================================================
    # ПЯТНИЦА (day_of_week = 4) 1–6 УРОКИ (ВСЕ ПАРАМИ)
    # =========================================================
    {
        "day_of_week": 4, "lesson_number": 1, "class_name": "11А",
        "subject": "Английский язык", "cabinet": "3/105", "teacher_name": "Першина С. Н.",
        "profile_name": "Филологический", "subgroup": None, "note": "08:15 – 08:55"
    },
    {
        "day_of_week": 4, "lesson_number": 1, "class_name": "11А",
        "subject": "Литература", "cabinet": "3/109", "teacher_name": "Иванова Е. В.",
        "profile_name": "Соц-гум", "subgroup": None, "note": "08:15 – 08:55"
    },
    {
        "day_of_week": 4, "lesson_number": 2, "class_name": "11А",
        "subject": "Английский язык", "cabinet": "3/105", "teacher_name": "Першина С. Н.",
        "profile_name": "Филологический", "subgroup": None, "note": "09:10 – 09:50"
    },
    {
        "day_of_week": 4, "lesson_number": 2, "class_name": "11А",
        "subject": "Литература", "cabinet": "3/109", "teacher_name": "Иванова Е. В.",
        "profile_name": "Соц-гум", "subgroup": None, "note": "09:10 – 09:50"
    },
    {
        "day_of_week": 4, "lesson_number": 3, "class_name": "11А",
        "subject": "Литература", "cabinet": "3/109", "teacher_name": "Иванова Е. В.",
        "profile_name": "Филологический", "subgroup": None, "note": "10:10 – 10:50"
    },
    {
        "day_of_week": 4, "lesson_number": 3, "class_name": "11А",
        "subject": "Обществознание", "cabinet": "1/226", "teacher_name": "Подкорытова Р. З.",
        "profile_name": "Соц-гум", "subgroup": None, "note": "10:10 – 10:50"
    },
    {
        "day_of_week": 4, "lesson_number": 4, "class_name": "11А",
        "subject": "Литература", "cabinet": "3/109", "teacher_name": "Иванова Е. В.",
        "profile_name": "Филологический", "subgroup": None, "note": "11:10 – 11:50"
    },
    {
        "day_of_week": 4, "lesson_number": 4, "class_name": "11А",
        "subject": "Обществознание", "cabinet": "1/226", "teacher_name": "Подкорытова Р. З.",
        "profile_name": "Соц-гум", "subgroup": None, "note": "11:10 – 11:50"
    },
    {
        "day_of_week": 4, "lesson_number": 5, "class_name": "11А",
        "subject": "Химия", "cabinet": "1/411", "teacher_name": "Юрина Т. Ю.",
        "profile_name": None, "subgroup": None, "note": "12:10 – 12:50"
    },
    {
        "day_of_week": 4, "lesson_number": 6, "class_name": "11А",
        "subject": "Химия", "cabinet": "1/411", "teacher_name": "Юрина Т. Ю.",
        "profile_name": None, "subgroup": None, "note": "13:00 – 13:40"
    },
]

LESSONS_11V = [
    # -------------------------------------------------------------
    # 11В - ПОНЕДЕЛЬНИК (day_of_week = 0)
    # -------------------------------------------------------------
    {"day_of_week": 0, "lesson_number": 1, "class_name": "11В", "subject": "Разговоры о важном", "cabinet": "1/322", "teacher_name": "Левин В.В.", "profile_name": None, "subgroup": None, "note": "Классный час"},
    {"day_of_week": 0, "lesson_number": 2, "class_name": "11В", "subject": "Алгебра и начала математического анализа", "cabinet": "1/322", "teacher_name": "Левин В.В.", "profile_name": None, "subgroup": None, "note": "Пара (1/2)"},
    {"day_of_week": 0, "lesson_number": 3, "class_name": "11В", "subject": "Алгебра и начала математического анализа", "cabinet": "1/322", "teacher_name": "Левин В.В.", "profile_name": None, "subgroup": None, "note": "Пара (2/2)"},
    {"day_of_week": 0, "lesson_number": 4, "class_name": "11В", "subject": "Физическая культура", "cabinet": "сп.зал 3", "teacher_name": "Стародубцев Н.Л.", "profile_name": None, "subgroup": None, "note": "Пара (1/2)"},
    {"day_of_week": 0, "lesson_number": 5, "class_name": "11В", "subject": "Физическая культура", "cabinet": "сп.зал 3", "teacher_name": "Стародубцев Н.Л.", "profile_name": None, "subgroup": None, "note": "Пара (2/2)"},
    {"day_of_week": 0, "lesson_number": 6, "class_name": "11В", "subject": "Литература", "cabinet": "3/109", "teacher_name": "Иванова Е.В.", "profile_name": None, "subgroup": None, "note": "Пара (1/2)"},
    {"day_of_week": 0, "lesson_number": 7, "class_name": "11В", "subject": "Литература", "cabinet": "3/109", "teacher_name": "Иванова Е.В.", "profile_name": None, "subgroup": None, "note": "Пара (2/2)"},
    {"day_of_week": 0, "lesson_number": 8, "class_name": "11В", "subject": "ЭК Информатика", "cabinet": "1/205", "teacher_name": "Мышко Ю.Ю.", "profile_name": "Инфотех", "subgroup": None, "note": "Элективный курс"},
    {"day_of_week": 0, "lesson_number": 8, "class_name": "11В", "subject": "Английский язык", "cabinet": "3/111", "teacher_name": "Елагина М.В.", "profile_name": "Инженерный", "subgroup": None, "note": None},

    # -------------------------------------------------------------
    # 11В - ВТОРНИК (day_of_week = 1)
    # -------------------------------------------------------------
    {"day_of_week": 1, "lesson_number": 1, "class_name": "11В", "subject": "Информатика и ИКТ", "cabinet": "3/314", "teacher_name": "Тольянская В.В.", "profile_name": "Инфотех", "subgroup": None, "note": "Пара (1/2)"},
    {"day_of_week": 1, "lesson_number": 1, "class_name": "11В", "subject": "Физика", "cabinet": "1/404", "teacher_name": "Кукарская Т.Н.", "profile_name": "Инженерный", "subgroup": None, "note": "Пара (1/2)"},
    {"day_of_week": 1, "lesson_number": 2, "class_name": "11В", "subject": "Информатика и ИКТ", "cabinet": "1/205", "teacher_name": "Мышко Ю.Ю.", "profile_name": "Инфотех", "subgroup": None, "note": "Пара (2/2)"},
    {"day_of_week": 1, "lesson_number": 2, "class_name": "11В", "subject": "Физика", "cabinet": "1/404", "teacher_name": "Кукарская Т.Н.", "profile_name": "Инженерный", "subgroup": None, "note": "Пара (2/2)"},
    {"day_of_week": 1, "lesson_number": 3, "class_name": "11В", "subject": "Русский язык", "cabinet": "3/109", "teacher_name": "Иванова Е.В.", "profile_name": None, "subgroup": None, "note": "Пара (1/2)"},
    {"day_of_week": 1, "lesson_number": 4, "class_name": "11В", "subject": "Русский язык", "cabinet": "3/109", "teacher_name": "Иванова Е.В.", "profile_name": None, "subgroup": None, "note": "Пара (2/2)"},
    {"day_of_week": 1, "lesson_number": 5, "class_name": "11В", "subject": "Геометрия", "cabinet": "1/322", "teacher_name": "Левин В.В.", "profile_name": None, "subgroup": None, "note": "Пара (1/2)"},
    {"day_of_week": 1, "lesson_number": 6, "class_name": "11В", "subject": "Геометрия", "cabinet": "1/322", "teacher_name": "Левин В.В.", "profile_name": None, "subgroup": None, "note": "Пара (2/2)"},
    {"day_of_week": 1, "lesson_number": 7, "class_name": "11В", "subject": "Английский язык", "cabinet": "1/304", "teacher_name": "Мажникова В.Д.", "profile_name": "Инфотех", "subgroup": None, "note": None},
    {"day_of_week": 1, "lesson_number": 7, "class_name": "11В", "subject": "ЭК Физика", "cabinet": "1/404", "teacher_name": "Кукарская Т.Н.", "profile_name": "Инженерный", "subgroup": None, "note": "Элективный курс"},

    # -------------------------------------------------------------
    # 11В - СРЕДА (day_of_week = 2)
    # -------------------------------------------------------------
    {"day_of_week": 2, "lesson_number": 1, "class_name": "11В", "subject": "История", "cabinet": "1/123", "teacher_name": "Романюк Э.В.", "profile_name": None, "subgroup": None, "note": "Пара (1/2)"},
    {"day_of_week": 2, "lesson_number": 2, "class_name": "11В", "subject": "История", "cabinet": "1/123", "teacher_name": "Романюк Э.В.", "profile_name": None, "subgroup": None, "note": "Пара (2/2)"},
    {"day_of_week": 2, "lesson_number": 3, "class_name": "11В", "subject": "Алгебра и начала математического анализа", "cabinet": "1/322", "teacher_name": "Левин В.В.", "profile_name": None, "subgroup": None, "note": "Пара (1/2)"},
    {"day_of_week": 2, "lesson_number": 4, "class_name": "11В", "subject": "Алгебра и начала математического анализа", "cabinet": "1/322", "teacher_name": "Левин В.В.", "profile_name": None, "subgroup": None, "note": "Пара (2/2)"},
    {"day_of_week": 2, "lesson_number": 5, "class_name": "11В", "subject": "Основы безопасности и защиты Родины", "cabinet": "1/216", "teacher_name": "Климов Е.Н.", "profile_name": None, "subgroup": None, "note": "Пара (1/2)"},
    {"day_of_week": 2, "lesson_number": 6, "class_name": "11В", "subject": "Основы безопасности и защиты Родины", "cabinet": "1/216", "teacher_name": "Климов Е.Н.", "profile_name": None, "subgroup": None, "note": "Пара (2/2)"},

    # -------------------------------------------------------------
    # 11В - ЧЕТВЕРГ (day_of_week = 3)
    # -------------------------------------------------------------
    {"day_of_week": 3, "lesson_number": 1, "class_name": "11В", "subject": "Обществознание", "cabinet": "1/225", "teacher_name": "Васильева А.С.", "profile_name": None, "subgroup": None, "note": "Пара (1/2)"},
    {"day_of_week": 3, "lesson_number": 2, "class_name": "11В", "subject": "Обществознание", "cabinet": "1/225", "teacher_name": "Васильева А.С.", "profile_name": None, "subgroup": None, "note": "Пара (2/2)"},
    {"day_of_week": 3, "lesson_number": 3, "class_name": "11В", "subject": "Информатика и ИКТ", "cabinet": "1/205", "teacher_name": "Мышко Ю.Ю.", "profile_name": "Инфотех", "subgroup": None, "note": "Пара (1/2)"},
    {"day_of_week": 3, "lesson_number": 3, "class_name": "11В", "subject": "Физика", "cabinet": "1/404", "teacher_name": "Кукарская Т.Н.", "profile_name": "Инженерный", "subgroup": None, "note": "Пара (1/2)"},
    {"day_of_week": 3, "lesson_number": 4, "class_name": "11В", "subject": "Информатика и ИКТ", "cabinet": "1/205", "teacher_name": "Мышко Ю.Ю.", "profile_name": "Инфотех", "subgroup": None, "note": "Пара (2/2)"},
    {"day_of_week": 3, "lesson_number": 4, "class_name": "11В", "subject": "Физика", "cabinet": "1/404", "teacher_name": "Кукарская Т.Н.", "profile_name": "Инженерный", "subgroup": None, "note": "Пара (2/2)"},
    {"day_of_week": 3, "lesson_number": 5, "class_name": "11В", "subject": "Литература", "cabinet": "3/109", "teacher_name": "Иванова Е.В.", "profile_name": None, "subgroup": None, "note": None},
    {"day_of_week": 3, "lesson_number": 6, "class_name": "11В", "subject": "ЭК Родной язык в жизни общества", "cabinet": "3/109", "teacher_name": "Иванова Е.В.", "profile_name": None, "subgroup": None, "note": "Элективный курс"},
    {"day_of_week": 3, "lesson_number": 7, "class_name": "11В", "subject": "Геометрия", "cabinet": "1/322", "teacher_name": "Левин В.В.", "profile_name": None, "subgroup": None, "note": None},

    # -------------------------------------------------------------
    # 11В - ПЯТНИЦА (day_of_week = 4)
    # -------------------------------------------------------------
    {"day_of_week": 4, "lesson_number": 1, "class_name": "11В", "subject": "Английский язык", "cabinet": "1/304", "teacher_name": "Мажникова В.Д.", "profile_name": "Инфотех", "subgroup": None, "note": "Пара (1/2)"},
    {"day_of_week": 4, "lesson_number": 1, "class_name": "11В", "subject": "Физика", "cabinet": "1/416", "teacher_name": "Кукарская Т.Н.", "profile_name": "Инженерный", "subgroup": None, "note": "Пара (1/2)"},
    {"day_of_week": 4, "lesson_number": 2, "class_name": "11В", "subject": "Английский язык", "cabinet": "1/304", "teacher_name": "Мажникова В.Д.", "profile_name": "Инфотех", "subgroup": None, "note": "Пара (2/2)"},
    {"day_of_week": 4, "lesson_number": 2, "class_name": "11В", "subject": "Физика", "cabinet": "1/416", "teacher_name": "Кукарская Т.Н.", "profile_name": "Инженерный", "subgroup": None, "note": "Пара (2/2)"},
    {"day_of_week": 4, "lesson_number": 3, "class_name": "11В", "subject": "Английский язык", "cabinet": "1/318", "teacher_name": "Зворыгин Я.П.", "profile_name": "Инфотех", "subgroup": None, "note": None},
    {"day_of_week": 4, "lesson_number": 3, "class_name": "11В", "subject": "Английский язык", "cabinet": "3/111", "teacher_name": "Елагина М.В.", "profile_name": "Инженерный", "subgroup": None, "note": None},
    {"day_of_week": 4, "lesson_number": 5, "class_name": "11В", "subject": "Биология", "cabinet": "1/311", "teacher_name": "Андронова Е.В.", "profile_name": None, "subgroup": None, "note": "Пара (1/2)"},
    {"day_of_week": 4, "lesson_number": 6, "class_name": "11В", "subject": "Биология", "cabinet": "1/311", "teacher_name": "Андронова Е.В.", "profile_name": None, "subgroup": None, "note": "Пара (2/2)"},
    {"day_of_week": 4, "lesson_number": 7, "class_name": "11В", "subject": "Вероятность и статистика", "cabinet": "1/322", "teacher_name": "Левин В.В.", "profile_name": None, "subgroup": None, "note": None},
]

LESSONS_11G = [
    # -------------------------------------------------------------
    # 11Г - ПОНЕДЕЛЬНИК (day_of_week = 0)
    # -------------------------------------------------------------
    {"day_of_week": 0, "lesson_number": 1, "class_name": "11Г", "subject": "Разговоры о важном", "cabinet": "1/307", "teacher_name": "Минина О.А.", "profile_name": None, "subgroup": None, "note": "Классный час"},
    {"day_of_week": 0, "lesson_number": 2, "class_name": "11Г", "subject": "Информатика и ИКТ", "cabinet": "3/314", "teacher_name": "Тольянская В.В.", "profile_name": None, "subgroup": 1, "note": None},
    {"day_of_week": 0, "lesson_number": 2, "class_name": "11Г", "subject": "Английский язык", "cabinet": "1/304", "teacher_name": "Мажникова В.Д.", "profile_name": None, "subgroup": 2, "note": None},
    {"day_of_week": 0, "lesson_number": 3, "class_name": "11Г", "subject": "Английский язык", "cabinet": "3/111", "teacher_name": "Елагина М.В.", "profile_name": None, "subgroup": 1, "note": None},
    {"day_of_week": 0, "lesson_number": 3, "class_name": "11Г", "subject": "Информатика и ИКТ", "cabinet": "3/314", "teacher_name": "Тольянская В.В.", "profile_name": None, "subgroup": 2, "note": None},
    {"day_of_week": 0, "lesson_number": 5, "class_name": "11Г", "subject": "Литература", "cabinet": "1/423", "teacher_name": "Шабалина Е.В.", "profile_name": None, "subgroup": None, "note": None},
    {"day_of_week": 0, "lesson_number": 6, "class_name": "11Г", "subject": "Геометрия", "cabinet": "3/311", "teacher_name": "Захарова Н.А.", "profile_name": None, "subgroup": None, "note": "Пара (1/2)"},
    {"day_of_week": 0, "lesson_number": 7, "class_name": "11Г", "subject": "Геометрия", "cabinet": "3/311", "teacher_name": "Захарова Н.А.", "profile_name": None, "subgroup": None, "note": "Пара (2/2)"},
    {"day_of_week": 0, "lesson_number": 8, "class_name": "11Г", "subject": "Химия", "cabinet": "1/411", "teacher_name": "Юрина Т.Ю.", "profile_name": None, "subgroup": None, "note": "Углубленный курс"},

    # -------------------------------------------------------------
    # 11Г - ВТОРНИК (day_of_week = 1)
    # -------------------------------------------------------------
    {"day_of_week": 1, "lesson_number": 1, "class_name": "11Г", "subject": "История", "cabinet": "1/123", "teacher_name": "Романюк Э.В.", "profile_name": None, "subgroup": None, "note": None},
    {"day_of_week": 1, "lesson_number": 2, "class_name": "11Г", "subject": "Обществознание", "cabinet": "1/307", "teacher_name": "Романюк Э.В.", "profile_name": None, "subgroup": None, "note": None},
    {"day_of_week": 1, "lesson_number": 3, "class_name": "11Г", "subject": "Биология", "cabinet": "1/307", "teacher_name": "Минина О.А.", "profile_name": None, "subgroup": None, "note": "Углубленный курс"},
    {"day_of_week": 1, "lesson_number": 4, "class_name": "11Г", "subject": "Основы безопасности и защиты Родины", "cabinet": "1/216", "teacher_name": "Климов Е.Н.", "profile_name": None, "subgroup": None, "note": "Пара (1/2)"},
    {"day_of_week": 1, "lesson_number": 5, "class_name": "11Г", "subject": "Основы безопасности и защиты Родины", "cabinet": "1/216", "teacher_name": "Климов Е.Н.", "profile_name": None, "subgroup": None, "note": "Пара (2/2)"},
    {"day_of_week": 1, "lesson_number": 6, "class_name": "11Г", "subject": "ЭК Родной язык в жизни общества", "cabinet": "1/423", "teacher_name": "Шабалина Е.В.", "profile_name": None, "subgroup": None, "note": "Элективный курс"},

    # -------------------------------------------------------------
    # 11Г - СРЕДА (day_of_week = 2)
    # -------------------------------------------------------------
    {"day_of_week": 2, "lesson_number": 1, "class_name": "11Г", "subject": "Алгебра и начала математического анализа", "cabinet": "3/311", "teacher_name": "Захарова Н.А.", "profile_name": None, "subgroup": None, "note": "Пара (1/2)"},
    {"day_of_week": 2, "lesson_number": 2, "class_name": "11Г", "subject": "Алгебра и начала математического анализа", "cabinet": "3/311", "teacher_name": "Захарова Н.А.", "profile_name": None, "subgroup": None, "note": "Пара (2/2)"},
    {"day_of_week": 2, "lesson_number": 3, "class_name": "11Г", "subject": "Английский язык", "cabinet": "3/111", "teacher_name": "Елагина М.В.", "profile_name": None, "subgroup": 1, "note": None},
    {"day_of_week": 2, "lesson_number": 3, "class_name": "11Г", "subject": "Английский язык", "cabinet": "1/304", "teacher_name": "Мажникова В.Д.", "profile_name": None, "subgroup": 2, "note": None},
    {"day_of_week": 2, "lesson_number": 4, "class_name": "11Г", "subject": "Физика", "cabinet": "1/416", "teacher_name": "Трухина Ю.В.", "profile_name": None, "subgroup": None, "note": "Пара (1/2)"},
    {"day_of_week": 2, "lesson_number": 5, "class_name": "11Г", "subject": "Физика", "cabinet": "1/416", "teacher_name": "Трухина Ю.В.", "profile_name": None, "subgroup": None, "note": "Пара (2/2)"},
    {"day_of_week": 2, "lesson_number": 6, "class_name": "11Г", "subject": "Алгебра и начала математического анализа", "cabinet": "3/311", "teacher_name": "Захарова Н.А.", "profile_name": None, "subgroup": None, "note": None},
    {"day_of_week": 2, "lesson_number": 7, "class_name": "11Г", "subject": "ЭК Основы теории химических процессов", "cabinet": "1/411", "teacher_name": "Юрина Т.Ю.", "profile_name": None, "subgroup": None, "note": "Элективный курс"},

    # -------------------------------------------------------------
    # 11Г - ЧЕТВЕРГ (day_of_week = 3)
    # -------------------------------------------------------------
    {"day_of_week": 3, "lesson_number": 1, "class_name": "11Г", "subject": "Химия", "cabinet": "1/411", "teacher_name": "Юрина Т.Ю.", "profile_name": None, "subgroup": None, "note": "Пара (1/2)"},
    {"day_of_week": 3, "lesson_number": 2, "class_name": "11Г", "subject": "Химия", "cabinet": "1/411", "teacher_name": "Юрина Т.Ю.", "profile_name": None, "subgroup": None, "note": "Пара (2/2)"},
    {"day_of_week": 3, "lesson_number": 3, "class_name": "11Г", "subject": "Русский язык", "cabinet": "1/423", "teacher_name": "Шабалина Е.В.", "profile_name": None, "subgroup": None, "note": None},
    {"day_of_week": 3, "lesson_number": 4, "class_name": "11Г", "subject": "Биология", "cabinet": "1/307", "teacher_name": "Минина О.А.", "profile_name": None, "subgroup": None, "note": "Углубленный курс"},
    {"day_of_week": 3, "lesson_number": 5, "class_name": "11Г", "subject": "Решение генетических задач", "cabinet": "1/307", "teacher_name": "Минина О.А.", "profile_name": None, "subgroup": None, "note": "Спецкурс"},
    {"day_of_week": 3, "lesson_number": 6, "class_name": "11Г", "subject": "Алгебра и начала математического анализа", "cabinet": "3/311", "teacher_name": "Захарова Н.А.", "profile_name": None, "subgroup": None, "note": None},
    {"day_of_week": 3, "lesson_number": 7, "class_name": "11Г", "subject": "ЭК Основы теории химических процессов", "cabinet": "1/411", "teacher_name": "Юрина Т.Ю.", "profile_name": None, "subgroup": None, "note": "Элективный курс"},

    # -------------------------------------------------------------
    # 11Г - ПЯТНИЦА (day_of_week = 4)
    # -------------------------------------------------------------
    {"day_of_week": 4, "lesson_number": 1, "class_name": "11Г", "subject": "Литература", "cabinet": "1/423", "teacher_name": "Шабалина Е.В.", "profile_name": None, "subgroup": None, "note": None},
    {"day_of_week": 4, "lesson_number": 2, "class_name": "11Г", "subject": "Вероятность и статистика", "cabinet": "3/311", "teacher_name": "Захарова Н.А.", "profile_name": None, "subgroup": None, "note": None},
    {"day_of_week": 4, "lesson_number": 3, "class_name": "11Г", "subject": "Физическая культура", "cabinet": "сп.зал 3", "teacher_name": "Стародубцев Н.Л.", "profile_name": None, "subgroup": None, "note": "Пара (1/2)"},
    {"day_of_week": 4, "lesson_number": 4, "class_name": "11Г", "subject": "Физическая культура", "cabinet": "сп.зал 3", "teacher_name": "Стародубцев Н.Л.", "profile_name": None, "subgroup": None, "note": "Пара (2/2)"},
    {"day_of_week": 4, "lesson_number": 5, "class_name": "11Г", "subject": "История", "cabinet": "1/123", "teacher_name": "Романюк Э.В.", "profile_name": None, "subgroup": None, "note": None},
]

LESSONS_11ZH = [
    # -------------------------------------------------------------
    # 11Ж - ПОНЕДЕЛЬНИК (day_of_week = 0)
    # -------------------------------------------------------------
    {"day_of_week": 0, "lesson_number": 1, "class_name": "11Ж", "subject": "Разговоры о важном", "cabinet": "1/318", "teacher_name": "Южакова Е.А.", "profile_name": None, "subgroup": None, "note": "Классный час"},
    {"day_of_week": 0, "lesson_number": 2, "class_name": "11Ж", "subject": "Информатика", "cabinet": "1/205", "teacher_name": "Мышко Ю.Ю.", "profile_name": None, "subgroup": 1, "note": "Пара (1/2)"},
    {"day_of_week": 0, "lesson_number": 2, "class_name": "11Ж", "subject": "Английский язык", "cabinet": "1/309", "teacher_name": "Петрова А.В.", "profile_name": None, "subgroup": 2, "note": "Пара (1/2)"},
    {"day_of_week": 0, "lesson_number": 3, "class_name": "11Ж", "subject": "Информатика", "cabinet": "1/205", "teacher_name": "Мышко Ю.Ю.", "profile_name": None, "subgroup": 1, "note": "Пара (2/2)"},
    {"day_of_week": 0, "lesson_number": 3, "class_name": "11Ж", "subject": "Английский язык", "cabinet": "1/309", "teacher_name": "Петрова А.В.", "profile_name": None, "subgroup": 2, "note": "Пара (2/2)"},
    {"day_of_week": 0, "lesson_number": 4, "class_name": "11Ж", "subject": "Алгебра и начала математического анализа", "cabinet": "1/318", "teacher_name": "Южакова Е.А.", "profile_name": None, "subgroup": None, "note": "Пара (1/2)"},
    {"day_of_week": 0, "lesson_number": 5, "class_name": "11Ж", "subject": "Алгебра и начала математического анализа", "cabinet": "1/318", "teacher_name": "Южакова Е.А.", "profile_name": None, "subgroup": None, "note": "Пара (2/2)"},
    {"day_of_week": 0, "lesson_number": 6, "class_name": "11Ж", "subject": "Обществознание", "cabinet": "1/225", "teacher_name": "Васильева А.С.", "profile_name": None, "subgroup": None, "note": "Пара (1/2)"},
    {"day_of_week": 0, "lesson_number": 7, "class_name": "11Ж", "subject": "Обществознание", "cabinet": "1/225", "teacher_name": "Васильева А.С.", "profile_name": None, "subgroup": None, "note": "Пара (2/2)"},
    {"day_of_week": 0, "lesson_number": 8, "class_name": "11Ж", "subject": "Литература", "cabinet": "3/107", "teacher_name": "Ульянов В.Н.", "profile_name": None, "subgroup": None, "note": None},

    # -------------------------------------------------------------
    # 11Ж - ВТОРНИК (day_of_week = 1)
    # -------------------------------------------------------------
    {"day_of_week": 1, "lesson_number": 1, "class_name": "11Ж", "subject": "Литература", "cabinet": "3/107", "teacher_name": "Ульянов В.Н.", "profile_name": None, "subgroup": None, "note": None},
    {"day_of_week": 1, "lesson_number": 2, "class_name": "11Ж", "subject": "Английский язык", "cabinet": "3/305", "teacher_name": "Першина С.Н.", "profile_name": None, "subgroup": 1, "note": "Пара (1/2)"},
    {"day_of_week": 1, "lesson_number": 2, "class_name": "11Ж", "subject": "Информатика и ИКТ", "cabinet": "1/205", "teacher_name": "Мышко Ю.Ю.", "profile_name": None, "subgroup": 2, "note": "Пара (1/2)"},
    {"day_of_week": 1, "lesson_number": 3, "class_name": "11Ж", "subject": "Английский язык", "cabinet": "3/305", "teacher_name": "Першина С.Н.", "profile_name": None, "subgroup": 1, "note": "Пара (2/2)"},
    {"day_of_week": 1, "lesson_number": 3, "class_name": "11Ж", "subject": "Информатика и ИКТ", "cabinet": "1/205", "teacher_name": "Мышко Ю.Ю.", "profile_name": None, "subgroup": 2, "note": "Пара (2/2)"},
    {"day_of_week": 1, "lesson_number": 4, "class_name": "11Ж", "subject": "Геометрия", "cabinet": "1/318", "teacher_name": "Южакова Е.А.", "profile_name": None, "subgroup": None, "note": "Пара (1/2)"},
    {"day_of_week": 1, "lesson_number": 5, "class_name": "11Ж", "subject": "Геометрия", "cabinet": "1/318", "teacher_name": "Южакова Е.А.", "profile_name": None, "subgroup": None, "note": "Пара (2/2)"},
    {"day_of_week": 1, "lesson_number": 6, "class_name": "11Ж", "subject": "ЭК Родной язык в жизни общества", "cabinet": "3/107", "teacher_name": "Ульянов В.Н.", "profile_name": None, "subgroup": None, "note": "Элективный курс"},

    # -------------------------------------------------------------
    # 11Ж - СРЕДА (day_of_week = 2)
    # -------------------------------------------------------------
    {"day_of_week": 2, "lesson_number": 1, "class_name": "11Ж", "subject": "Физическая культура", "cabinet": "сп.зал 3", "teacher_name": "Стародубцев Н.Л.", "profile_name": None, "subgroup": None, "note": None},
    {"day_of_week": 2, "lesson_number": 2, "class_name": "11Ж", "subject": "География", "cabinet": "1/222", "teacher_name": "Ушакова И.Н.", "profile_name": None, "subgroup": None, "note": "Пара (1/2)"},
    {"day_of_week": 2, "lesson_number": 3, "class_name": "11Ж", "subject": "География", "cabinet": "1/222", "teacher_name": "Ушакова И.Н.", "profile_name": None, "subgroup": None, "note": "Пара (2/2)"},
    {"day_of_week": 2, "lesson_number": 4, "class_name": "11Ж", "subject": "Геометрия", "cabinet": "1/318", "teacher_name": "Южакова Е.А.", "profile_name": None, "subgroup": None, "note": None},
    {"day_of_week": 2, "lesson_number": 5, "class_name": "11Ж", "subject": "Информатика", "cabinet": "1/205", "teacher_name": "Мышко Ю.Ю.", "profile_name": None, "subgroup": 1, "note": None},
    {"day_of_week": 2, "lesson_number": 5, "class_name": "11Ж", "subject": "Английский язык", "cabinet": "1/309", "teacher_name": "Петрова А.В.", "profile_name": None, "subgroup": 2, "note": None},

    # -------------------------------------------------------------
    # 11Ж - ЧЕТВЕРГ (day_of_week = 3)
    # -------------------------------------------------------------
    {"day_of_week": 3, "lesson_number": 1, "class_name": "11Ж", "subject": "Алгебра и начала математического анализа", "cabinet": "1/318", "teacher_name": "Южакова Е.А.", "profile_name": None, "subgroup": None, "note": None},
    {"day_of_week": 3, "lesson_number": 2, "class_name": "11Ж", "subject": "Биология", "cabinet": "1/311", "teacher_name": "Андронова Е.В.", "profile_name": None, "subgroup": None, "note": "Пара (1/2)"},
    {"day_of_week": 3, "lesson_number": 3, "class_name": "11Ж", "subject": "Биология", "cabinet": "1/311", "teacher_name": "Андронова Е.В.", "profile_name": None, "subgroup": None, "note": "Пара (2/2)"},
    {"day_of_week": 3, "lesson_number": 4, "class_name": "11Ж", "subject": "Русский язык", "cabinet": "3/107", "teacher_name": "Ульянов В.Н.", "profile_name": None, "subgroup": None, "note": "Пара (1/2)"},
    {"day_of_week": 3, "lesson_number": 5, "class_name": "11Ж", "subject": "Русский язык", "cabinet": "3/107", "teacher_name": "Ульянов В.Н.", "profile_name": None, "subgroup": None, "note": "Пара (2/2)"},
    {"day_of_week": 3, "lesson_number": 6, "class_name": "11Ж", "subject": "Информатика", "cabinet": "1/205", "teacher_name": "Мышко Ю.Ю.", "profile_name": None, "subgroup": None, "note": None},

    # -------------------------------------------------------------
    # 11Ж - ПЯТНИЦА (day_of_week = 4)
    # -------------------------------------------------------------
    {"day_of_week": 4, "lesson_number": 1, "class_name": "11Ж", "subject": "Физика", "cabinet": "1/327", "teacher_name": "Уткина И.В.", "profile_name": None, "subgroup": None, "note": None},
    {"day_of_week": 4, "lesson_number": 2, "class_name": "11Ж", "subject": "История", "cabinet": "1/123", "teacher_name": "Романюк Э.В.", "profile_name": None, "subgroup": None, "note": "Пара (1/2)"},
    {"day_of_week": 4, "lesson_number": 3, "class_name": "11Ж", "subject": "История", "cabinet": "1/123", "teacher_name": "Романюк Э.В.", "profile_name": None, "subgroup": None, "note": "Пара (2/2)"},
    {"day_of_week": 4, "lesson_number": 4, "class_name": "11Ж", "subject": "Вероятность и статистика", "cabinet": "1/318", "teacher_name": "Южакова Е.А.", "profile_name": None, "subgroup": None, "note": None},
    {"day_of_week": 4, "lesson_number": 5, "class_name": "11Ж", "subject": "Английский язык", "cabinet": "3/305", "teacher_name": "Першина С.Н.", "profile_name": None, "subgroup": 1, "note": "Пара (1/2)"},
    {"day_of_week": 4, "lesson_number": 5, "class_name": "11Ж", "subject": "Информатика и ИКТ", "cabinet": "1/205", "teacher_name": "Мышко Ю.Ю.", "profile_name": None, "subgroup": 2, "note": "Пара (1/2)"},
    {"day_of_week": 4, "lesson_number": 6, "class_name": "11Ж", "subject": "Английский язык", "cabinet": "3/305", "teacher_name": "Першина С.Н.", "profile_name": None, "subgroup": 1, "note": "Пара (2/2)"},
    {"day_of_week": 4, "lesson_number": 6, "class_name": "11Ж", "subject": "Информатика и ИКТ", "cabinet": "1/205", "teacher_name": "Мышко Ю.Ю.", "profile_name": None, "subgroup": 2, "note": "Пара (2/2)"},
]

async def seed():
    logger.info("Initializing database schema...")
    await init_db()

    async with async_session() as session:
        # Seed defaults only when absent, so deploys never overwrite edits.
        bell_res = await session.execute(select(BellSchedule))
        if not bell_res.scalars().first():
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
        class_res = await session.execute(select(SchoolClass))
        existing_classes = {item.name for item in class_res.scalars().all()}
        for c_name in DEFAULT_CLASSES:
            if c_name not in existing_classes:
                session.add(SchoolClass(name=c_name))

        profile_res = await session.execute(select(Profile))
        existing_profiles = {item.name for item in profile_res.scalars().all()}
        for p_name in ALL_PROFILES:
            if p_name not in existing_profiles:
                session.add(Profile(name=p_name))

        # 3. Seed Lessons for 11A, 11В, 11Г, 11Д, 11Ж
        lessons_11d = [{**item, 'class_name': '11Д'} for item in LESSONS_11V]
        all_seeded_lessons = LESSONS_11A + LESSONS_11V + LESSONS_11G + LESSONS_11ZH + lessons_11d
        logger.info(f"Seeding {len(all_seeded_lessons)} lessons across 11А, 11В, 11Г, 11Д, 11Ж...")
        lesson_res = await session.execute(select(Lesson.id).limit(1))
        if lesson_res.first() is None:
            for item in all_seeded_lessons:
                session.add(Lesson(
                    day_of_week=item["day_of_week"],
                    lesson_number=item["lesson_number"],
                    class_name=item["class_name"],
                    subject=item["subject"],
                    teacher_name=item["teacher_name"],
                    cabinet=item["cabinet"],
                    profile_name=item.get("profile_name"),
                    subgroup=item.get("subgroup"),
                    note=item.get("note")
                ))

        # 4. Pre-seed Admin Profile dynamically from environment variables
        if settings.admin_ids:
            for aid in settings.admin_ids:
                admin_user = await session.get(User, aid)
                if not admin_user:
                    session.add(User(
                        id=aid,
                        first_name="Администратор",
                        last_name="",
                        username=settings.admin_usernames[0] if settings.admin_usernames else None,
                        class_name="11А",
                        profile_name="Соц-гум",
                        is_admin=True
                    ))
                else:
                    if not admin_user.class_name:
                        admin_user.class_name = "11А"
                    if not admin_user.profile_name:
                        admin_user.profile_name = "Соц-гум"
                    admin_user.is_admin = True

        await session.commit()
        from data_updates import apply_calendar_schedule, apply_photo_timetables
        await apply_calendar_schedule()
        await apply_photo_timetables()
        from learning import apply_learning_catalog
        await apply_learning_catalog()
        logger.info("✅ Database successfully populated with synchronized 11А schedule, bells, and profiles!")

if __name__ == "__main__":
    asyncio.run(seed())
