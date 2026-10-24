"""One source for the lesson times used by cards and notifications."""
from sqlalchemy import select
from models import BellSchedule

MONDAY_BELLS = [
    (0, "08:00", "08:30"), (1, "08:35", "09:15"), (2, "09:30", "10:10"),
    (3, "10:25", "11:05"), (4, "11:25", "12:05"), (5, "12:25", "13:05"),
    (6, "13:10", "13:50"), (7, "14:00", "14:40"),
]


async def day_bells(db, day):
    if day == 0:
        return {number: (start, end) for number, start, end in MONDAY_BELLS}
    rows = (await db.scalars(select(BellSchedule).where(BellSchedule.is_saturday.is_(day == 5)))).all()
    return {row.lesson_number: (row.start_time, row.end_time) for row in rows}
