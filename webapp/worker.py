import os
import time
from datetime import datetime, timedelta
from collections import defaultdict

import pytz

from .models import db_session, Subscription, User
from .student_api import StudentAppClient, latest_term_code
import requests

TZ = pytz.timezone("US/Eastern")


_REFRESH_FLAG = {"needs": True}


def enqueue_refresh_flag():
    _REFRESH_FLAG["needs"] = True


def ntfy_publish(topic: str, message: str, *, title: str | None = None, priority: str | None = None, base: str = "https://ntfy.sh"):
    if not topic:
        return
    url = f"{base.rstrip('/')}/{topic}"
    headers = {}
    if title:
        headers["Title"] = title
    if priority:
        headers["Priority"] = priority
    requests.post(url, data=message.encode("utf-8"), headers=headers, timeout=15)


def run_loop():
    client = StudentAppClient(os.environ["CONSUMER_KEY"], os.environ["CONSUMER_SECRET"])
    term = os.getenv("TERM_CODE") or latest_term_code(client)
    interval = int(os.getenv("INTERVAL_SECS", "30"))
    renotify_secs = int(os.getenv("MIN_RENOTIFY_SECS", "20"))
    min_delta = timedelta(seconds=renotify_secs)

    while True:
        try:
            # group by course_id
            subs = db_session.query(Subscription).all()
            groups: dict[str, list[Subscription]] = defaultdict(list)
            for s in subs:
                groups[s.course_id].append(s)
            if not groups:
                time.sleep(interval)
                continue
            course_ids_csv = ",".join(groups.keys())
            seats = client.get_seats(term=term, course_ids_csv=course_ids_csv)
            courses = seats.get("course", []) if isinstance(seats, dict) else []
            now = datetime.now(TZ)
            for course in courses:
                courseid = str(course.get("course_id"))
                cls_map = {s.classid: s for s in groups.get(courseid, [])}
                for c in course.get("classes", []):
                    classid = str(c.get("class_number"))
                    if classid not in cls_map:
                        continue
                    status_open = c.get("pu_calc_status") == "Open"
                    try:
                        enroll = int(c.get("enrollment", 0))
                        cap = int(c.get("capacity", 0))
                    except Exception:
                        continue
                    n_open = max(cap - enroll, 0) if status_open and cap > enroll else 0
                    s = cls_map[classid]
                    user = db_session.query(User).filter_by(id=s.user_id).first()
                    should_notify = False
                    if n_open > 0:
                        if s.last_notified_open < 0:
                            should_notify = True
                        elif n_open != s.last_notified_open:
                            should_notify = True
                        elif not s.last_notified_at or (now - s.last_notified_at) >= min_delta:
                            should_notify = True
                    if should_notify:
                        msg = f"{n_open} open spot(s): {s.course_code} {s.section} (class {s.classid}) in course {s.course_id}."
                        ntfy_publish(user.ntfy_topic, msg, title="Seat opening detected", priority="high")
                        s.last_notified_open = n_open
                        s.last_notified_at = now
                        db_session.add(s)
            db_session.commit()
        except Exception:
            # swallow and keep looping
            pass

        # allow immediate loop after updates
        if _REFRESH_FLAG.get("needs"):
            _REFRESH_FLAG["needs"] = False
            continue
        time.sleep(interval)


if __name__ == "__main__":
    run_loop()
