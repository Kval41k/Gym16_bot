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


async def lesson_timeline(db, day, class_name=None, profile_name=None, subgroup=None, lesson_date=None):
    bells = await day_bells(db, day)
    if not class_name:
        return [{"number": number, "start": start, "end": end, "lessons": []}
                for number, (start, end) in sorted(bells.items())]
    rows = await effective_lessons(db, day, class_name, lesson_date)
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


async def effective_lessons(db, day, class_name=None, lesson_date=None):
    """Date overrides replace only that class/day; weekly rows are never mutated."""
    from types import SimpleNamespace
    import json
    from models import DatedSchedule
    query = select(Lesson).where(Lesson.day_of_week == day)
    if class_name:
        query = query.where(Lesson.class_name == class_name)
    rows = list((await db.scalars(query.order_by(Lesson.lesson_number, Lesson.profile_name))).all())
    if lesson_date is None:
        return rows
    query = select(DatedSchedule).where(DatedSchedule.lesson_date == lesson_date)
    if class_name:
        query = query.where(DatedSchedule.class_name == class_name)
    overrides = (await db.scalars(query)).all()
    for override in overrides:
        rows = [row for row in rows if row.class_name != override.class_name]
        rows.extend(SimpleNamespace(id=-(override.id * 1000 + index + 1), class_name=override.class_name, **row)
                    for index, row in enumerate(json.loads(override.rows_json)))
    return sorted(rows, key=lambda row: (row.lesson_number, row.profile_name or '', row.subgroup or 0))
