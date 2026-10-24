"""One source for the lesson times used by cards and notifications."""
from sqlalchemy import select
from models import BellSchedule, Lesson

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


def lesson_times(lesson, bells):
    if lesson.start_time and lesson.end_time:
        return lesson.start_time, lesson.end_time
    return bells.get(lesson.lesson_number, ("", ""))


async def lesson_timeline(db, day, class_name=None, profile_name=None, subgroup=None):
    bells = await day_bells(db, day)
    if not class_name:
        return [{"number": number, "start": start, "end": end, "lessons": []}
                for number, (start, end) in sorted(bells.items())]
    rows = (await db.scalars(select(Lesson).where(Lesson.class_name == class_name, Lesson.day_of_week == day))).all()
    grouped = {}
    for lesson in rows:
        if profile_name and lesson.profile_name and lesson.profile_name.casefold() != profile_name.casefold():
            continue
        if subgroup and lesson.subgroup and subgroup != lesson.subgroup:
            continue
        start, end = lesson_times(lesson, bells)
        if not start or not end:
            continue
        key = (start, end)
        grouped.setdefault(key, {"number": lesson.lesson_number, "start": start, "end": end, "lessons": []})["lessons"].append(lesson)
    return sorted(grouped.values(), key=lambda item: (item["start"], item["end"]))
