from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from config import settings

def get_db_url() -> str:
    url = settings.DATABASE_URL
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+asyncpg://", 1)
    elif url.startswith("postgresql://") and not url.startswith("postgresql+asyncpg://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return url

DB_URL = get_db_url()

# High-performance async SQLAlchemy engine with connection pooling
is_sqlite = "sqlite" in DB_URL
engine_kwargs = {
    "echo": False,
    "future": True,
}
if is_sqlite:
    engine_kwargs["connect_args"] = {"check_same_thread": False}
else:
    engine_kwargs["pool_size"] = 25
    engine_kwargs["max_overflow"] = 35
    engine_kwargs["pool_pre_ping"] = True
    engine_kwargs["pool_recycle"] = 300

engine = create_async_engine(DB_URL, **engine_kwargs)

# Async session factory
async_session = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False
)

# Base class for all models
class Base(DeclarativeBase):
    pass

# FastAPI Dependency for database session
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session() as session:
        try:
            yield session
        finally:
            await session.close()

# Database initialization (creates tables and initial seeds)
async def init_db() -> None:
    from models import SchoolClass, Profile, BellSchedule
    from config import DEFAULT_CLASSES, ALL_PROFILES, DEFAULT_BELLS
    from sqlalchemy import select

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with async_session() as session:
        # 1. Seed classes if missing
        class_res = await session.execute(select(SchoolClass))
        existing_classes = {c.name for c in class_res.scalars().all()}
        for name in DEFAULT_CLASSES:
            if name not in existing_classes:
                session.add(SchoolClass(name=name))

        # 2. Seed profiles if missing
        prof_res = await session.execute(select(Profile))
        existing_profiles = {p.name for p in prof_res.scalars().all()}
        for name in ALL_PROFILES:
            if name not in existing_profiles:
                session.add(Profile(name=name))

        # 3. Seed bell schedule if empty
        bell_res = await session.execute(select(BellSchedule))
        if not bell_res.scalars().first():
            for b in DEFAULT_BELLS:
                session.add(BellSchedule(
                    lesson_number=b["lesson_number"],
                    start_time=b["start_time"],
                    end_time=b["end_time"],
                    is_saturday=False
                ))

        # 4. Seed EGE subjects and starter materials if missing
        from models import EgeSubject, EgeMaterial
        subj_res = await session.execute(select(EgeSubject))
        if not subj_res.scalars().first():
            session.add(EgeSubject(code="russian", name="Русский язык", icon="📖", tasks_count=27))
            session.add(EgeSubject(code="math", name="Математика", icon="📐", tasks_count=19))
            
            # Starter materials for Russian
            session.add(EgeMaterial(
                subject_code="russian",
                task_number=4,
                title="Орфоэпические нормы (ударения)",
                theory="📌 Основные правила орфоэпии ЕГЭ:\n\n"
                       "1. Глаголы прошедшего времени женского рода имеют ударение на окончание -А: бралА, бралИсь, взялА, добралА, ждалА, звалА, лилА.\n"
                       "Исключения: клАла, крАла, слАла, послАла, стлАла.\n\n"
                       "2. Причастия с суффиксом -Т-: согнУтый, завЁрнутый, нАчатый, нанЯтый.\n\n"
                       "3. Существительные: жалюзИ, тортЫ, шАрфы, бАнты, звонИт, сливОвый, свЁкла, экспЕрт, диалОг, каталОг, некролОг.\n\n"
                       "4. Наречия: довЕрху, донИзу, досУха, зАгодя, зАсветло, зАтемно."
            ))
            session.add(EgeMaterial(
                subject_code="russian",
                task_number=9,
                title="Правописание корней (проверяемые, непроверяемые, чередующиеся)",
                theory="📌 Чередующиеся корни в русском языке:\n\n"
                       "1. Зависят от ударения:\n"
                       "• ГАР/ГОР — под ударением А (загАр), без ударения О (загорЕлый). Исключения: прИгарь, вЫгарки.\n"
                       "• ЗАР/ЗОР — без ударения А (зарЯ), под ударением что слышится (зОри, зАрево). Исключение: зоревАть.\n"
                       "• КЛАН/КЛОН, ТВАР/ТВОР — без ударения О (поклониться, творение). Исключение: Утварь.\n\n"
                       "2. Зависят от суффикса -А-:\n"
                       "• БЕР/БИР, ДЕР/ДИР, МЕР/МИР, ПЕР/ПИР, ТЕР/ТИР, БЛЕСТ/БЛИСТ, ЖЕГ/ЖИГ, СТЕЛ/СТИЛ, ЧЕТ/ЧИТ — И пишется, если есть суффикс А (собИрать, застИлать). Исключения: сочетАть, сочетАние.\n"
                       "• ЛАГ/ЛОЖ — полАгать / положИть.\n"
                       "• КАС/КОС — касАться / коснУться.\n\n"
                       "3. Зависят от согласной в корне:\n"
                       "• РАСТ/РАЩ/РОС — вырАсти, вырАщенный, вырОсли. Исключения: росток, ростовщик, Ростов, Ростислав, отрасль.\n"
                       "• СКАК/СКОЧ — скАкать, подскочИть. Исключения: скачок, скачу.\n\n"
                       "4. Зависят от значения:\n"
                       "• МАК (погружать в жидкость: макать хлеб) / МОК (пропускать жидкость: вымокнуть под дождем).\n"
                       "• РАВН (одинаковый: сравнять счет) / РОВН (гладкий, прямой: подровнять газон)."
            ))
            session.add(EgeMaterial(
                subject_code="russian",
                task_number=12,
                title="Личные окончания глаголов и суффиксы причастий",
                theory="📌 Спряжение глаголов (целУЮ — мИлАЯ):\n\n"
                       "1 спряжение (в окончаниях Е, У, Ю): глаголы на -ЕТЬ, -АТЬ, -ОТЬ, -УТЬ, -ЫТЬ, -ТИ.\n"
                       "Исключения: брить, стелить, зиждиться, зыбиться.\n\n"
                       "2 спряжение (в окончаниях И, А, Я):\n"
                       "• Все глаголы на -ИТЬ (кроме брить, стелить).\n"
                       "• 7 на -ЕТЬ: терпеть, вертеть, обидеть, зависеть, ненавидеть, видеть, смотреть.\n"
                       "• 4 на -АТЬ: гнать, дышать, держать, слышать.\n\n"
                       "Суффиксы причастий настоящего времени:\n"
                       "• От 1 спр.: -УЩ-/-ЮЩ-, -ОМ-/-ЕМ- (борющийся, читаемый).\n"
                       "• От 2 спр.: -АЩ-/-ЯЩ-, -ИМ- (дышащий, клеящий, видимый)."
            ))

            # Starter materials for Math
            session.add(EgeMaterial(
                subject_code="math",
                task_number=1,
                title="Планиметрия (Треугольники и окружности)",
                theory="📌 Основные формулы геометрии:\n\n"
                       "1. Площади треугольника:\n"
                       "• S = 1/2 * a * h_a\n"
                       "• S = 1/2 * a * b * sin(C)\n"
                       "• S = p * r (где p — полупериметр, r — радиус вписанной окр.)\n"
                       "• S = a*b*c / (4R) (R — радиус описанной окр.)\n"
                       "• Формула Герона: S = sqrt(p*(p-a)*(p-b)*(p-c))\n\n"
                       "2. Теоремы:\n"
                       "• Теорема синусов: a/sin(A) = b/sin(B) = c/sin(C) = 2R\n"
                       "• Теорема косинусов: c² = a² + b² - 2ab*cos(C)\n\n"
                       "3. Прямоугольный треугольник:\n"
                       "• r = (a + b - c) / 2\n"
                       "• R = c / 2 (медиана к гипотенузе равна радиусу описанной окружности: m_c = R = c/2)"
            ))
            session.add(EgeMaterial(
                subject_code="math",
                task_number=6,
                title="Производная и первообразная",
                theory="📌 Геометрический и физический смысл производной:\n\n"
                       "1. Геометрический смысл:\n"
                       "• f'(x_0) = k = tg(a) — угловой коэффициент касательной равен тангенсу угла наклона касательной к оси Ox.\n"
                       "• Уравнение касательной: y = f(x_0) + f'(x_0)*(x - x_0).\n\n"
                       "2. Исследование функции:\n"
                       "• Если f'(x) > 0 на интервале, функция возрастает.\n"
                       "• Если f'(x) < 0 на интервале, функция убывает.\n"
                       "• Точки экстремума: где f'(x) = 0 и производная меняет знак (с + на -: максимум, с - на +: минимум).\n\n"
                       "3. Физический смысл:\n"
                       "• Скорость v(t) = x'(t) (производная от координаты).\n"
                       "• Ускорение a(t) = v'(t) = x''(t)."
            ))
            session.add(EgeMaterial(
                subject_code="math",
                task_number=12,
                title="Тригонометрические уравнения",
                theory="📌 Основные решения простейших уравнений:\n\n"
                       "1. sin(x) = a (|a| <= 1):\n"
                       "• x = (-1)^k * arcsin(a) + pi*k, k in Z\n"
                       "Частные случаи:\n"
                       "• sin(x) = 0 => x = pi*k\n"
                       "• sin(x) = 1 => x = pi/2 + 2*pi*k\n"
                       "• sin(x) = -1 => x = -pi/2 + 2*pi*k\n\n"
                       "2. cos(x) = a (|a| <= 1):\n"
                       "• x = +- arccos(a) + 2*pi*k, k in Z\n"
                       "Частные случаи:\n"
                       "• cos(x) = 0 => x = pi/2 + pi*k\n"
                       "• cos(x) = 1 => x = 2*pi*k\n"
                       "• cos(x) = -1 => x = pi + 2*pi*k\n\n"
                       "3. Формулы понижения степени:\n"
                       "• sin²(x) = (1 - cos(2x)) / 2\n"
                       "• cos²(x) = (1 + cos(2x)) / 2"
            ))

        await session.commit()
