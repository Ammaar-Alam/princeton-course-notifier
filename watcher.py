#!/usr/bin/env python3
import argparse
import base64
import logging
import json
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

import pytz
import requests


TZ = pytz.timezone("US/Eastern")
STUDENT_APP_BASE = "https://api.princeton.edu:443/student-app/1.0.3"
TOKEN_URL = "https://api.princeton.edu:443/token"


class StudentAppClient:
    def __init__(self, consumer_key: str, consumer_secret: str):
        self.consumer_key = consumer_key
        self.consumer_secret = consumer_secret
        self.access_token: Optional[str] = None
        self.token_expiry: Optional[float] = None

    def _ensure_token(self):
        if self.access_token and self.token_expiry and time.time() < self.token_expiry - 30:
            return
        auth = base64.b64encode(f"{self.consumer_key}:{self.consumer_secret}".encode()).decode()
        resp = requests.post(
            TOKEN_URL,
            data={"grant_type": "client_credentials"},
            headers={"Authorization": f"Basic {auth}"},
            timeout=20,
        )
        resp.raise_for_status()
        data = resp.json()
        self.access_token = data["access_token"]
        # Typically expires_in is in seconds
        self.token_expiry = time.time() + int(data.get("expires_in", 300))

    def _get(self, path: str, params: Dict[str, str]):
        self._ensure_token()
        url = f"{STUDENT_APP_BASE}{path}"
        resp = requests.get(url, params=params, headers={"Authorization": f"Bearer {self.access_token}"}, timeout=30)
        # If token failed, retry once
        if resp.status_code == 401:
            self.access_token = None
            self._ensure_token()
            resp = requests.get(url, params=params, headers={"Authorization": f"Bearer {self.access_token}"}, timeout=30)
        resp.raise_for_status()
        return resp.json()

    def get_terms(self):
        return self._get("/courses/terms", {"fmt": "json"})

    def get_courses(self, term: str, subject: Optional[str] = None, catnum: Optional[str] = None, search: Optional[str] = None):
        params = {"fmt": "json", "term": term}
        if subject:
            params["subject"] = subject
        if catnum:
            # API expects a leading space
            if not catnum.startswith(" "):
                catnum = f" {catnum}"
            params["catnum"] = catnum
        if search:
            params["search"] = search
        return self._get("/courses/courses", params)

    def get_seats(self, term: str, course_ids_csv: str):
        return self._get("/courses/seats", {"fmt": "json", "term": term, "course_ids": course_ids_csv})


def latest_term_code(api: StudentAppClient) -> str:
    data = api.get_terms()
    # Pick the last entry that has a term code; if field names differ, print a hint
    terms = data
    # The StudentApp response typically has terms in data["term"], but exact shape can change
    if isinstance(data, dict) and "term" in data:
        terms = data["term"]
    # Expect most recent term last
    if isinstance(terms, list) and terms:
        # Try common keys
        for key in ("code", "term_code", "strm"):
            if key in terms[-1]:
                return terms[-1][key]
        # Fallback: scan for first item with a numeric-looking code
        for item in reversed(terms):
            for key, val in item.items():
                if isinstance(val, str) and val.isdigit():
                    return val
    raise RuntimeError("Unable to determine latest term code from /courses/terms response")


@dataclass
class CourseSpec:
    course_code: Optional[str] = None  # e.g., COS333
    sections: Optional[List[str]] = None  # e.g., ["L01", "P01"]
    course_id: Optional[str] = None  # e.g., 002054
    class_ids: Optional[List[str]] = None  # e.g., ["21931", ...]


def parse_course_arg(arg: str) -> CourseSpec:
    # Accept forms:
    #   COS333:L01,P01
    #   002054:21931,21927
    if ":" in arg:
        left, right = arg.split(":", 1)
        parts = [p.strip() for p in right.split(",") if p.strip()]
        if left.isdigit():
            return CourseSpec(course_id=left, class_ids=parts)
        else:
            return CourseSpec(course_code=left.upper(), sections=parts)
    else:
        # Only a course code: monitor all sections
        return CourseSpec(course_code=arg.upper(), sections=None)


def resolve_course_to_ids(api: StudentAppClient, term: str, spec: CourseSpec) -> Tuple[str, List[str]]:
    """Return (course_id, class_ids) for the spec. If spec already provides IDs, passthrough."""
    if spec.course_id and spec.class_ids:
        return spec.course_id, spec.class_ids
    if not spec.course_code:
        raise ValueError("Invalid course spec; need course_code or course_id")
    subj = spec.course_code[:3]
    cat = spec.course_code[3:]
    data = api.get_courses(term=term, subject=subj, catnum=cat)
    # Navigate terms->subjects->courses to find matching displayname
    term_list = data.get("term", []) if isinstance(data, dict) else []
    if not term_list:
        raise RuntimeError(f"No data for {spec.course_code}")
    # find first subject/courses with matching catalog_number
    course_id = None
    classes = []
    for subj_obj in term_list[0].get("subjects", []):
        for course in subj_obj.get("courses", []):
            # Build displayname like COS333
            disp = f"{subj_obj.get('code','')}{course.get('catalog_number','')}"
            if disp.upper() != spec.course_code.upper():
                continue
            course_id = course.get("course_id")
            for c in course.get("classes", []):
                if spec.sections:
                    if c.get("section") in spec.sections:
                        classes.append(str(c.get("class_number")))
                else:
                    classes.append(str(c.get("class_number")))
            break
        if course_id:
            break
    if not course_id or not classes:
        raise RuntimeError(f"Could not resolve course/classes for {spec}")
    return course_id, classes


def compute_openings(seats_resp: dict, target_classids: set) -> List[Tuple[str, int, str, dict]]:
    """Return list of (classid, n_open, courseid, class_obj) where openings detected."""
    out: List[Tuple[str, int, str, dict]] = []
    courses = seats_resp.get("course") if isinstance(seats_resp, dict) else None
    if not courses:
        return out
    for course in courses:
        courseid = str(course.get("course_id")) if course.get("course_id") is not None else "?"
        for c in course.get("classes", []):
            classid = str(c.get("class_number"))
            if classid not in target_classids:
                continue
            status_open = c.get("pu_calc_status") == "Open"
            try:
                enroll = int(c.get("enrollment", 0))
                cap = int(c.get("capacity", 0))
            except Exception:
                continue
            if status_open and cap > enroll:
                out.append((classid, cap - enroll, courseid, c))
    return out


def ntfy_publish(topic: str, message: str, *, title: Optional[str] = None, priority: Optional[str] = None, base: str = "https://ntfy.sh"):
    url = f"{base.rstrip('/')}/{topic}"
    headers = {}
    if title:
        headers["Title"] = title
    if priority:
        headers["Priority"] = priority
    # no emoji/tags to keep notifications plain
    # ntfy supports raw body text; encode for safety
    requests.post(url, data=message.encode("utf-8"), headers=headers, timeout=15)


def main():
    parser = argparse.ArgumentParser(description="TigerSnatch-like watcher with ntfy push")
    parser.add_argument("--courses", nargs="*", help="Specs like COS333:L01,P01 (monitor only those sections) or COS333 (all). If omitted, reads COURSE_SPECS env (space-separated)")
    parser.add_argument("--ids", nargs="*", help="Specs like 002054:21931,21927 (courseid:classids). If omitted, reads ID_SPECS env (space-separated)")
    parser.add_argument("--interval", type=int, default=int(os.getenv("INTERVAL_SECS", "30")), help="Polling interval in seconds (default 30 or INTERVAL_SECS env)")
    parser.add_argument("--min-renotify-secs", type=int, default=int(os.getenv("MIN_RENOTIFY_SECS", "20")), help="Seconds before repeating notification for unchanged open count (default 20 or MIN_RENOTIFY_SECS env)")
    parser.add_argument("--topic", help="ntfy topic; overrides NTFY_TOPIC env var")
    parser.add_argument("--ntfy-url", default=os.getenv("NTFY_URL", "https://ntfy.sh"), help="ntfy base URL (default https://ntfy.sh or NTFY_URL env)")
    parser.add_argument("--log-level", default=os.getenv("LOG_LEVEL", "INFO"), help="Logging level (DEBUG, INFO, WARNING, ERROR)")
    args = parser.parse_args()

    consumer_key = os.getenv("CONSUMER_KEY")
    consumer_secret = os.getenv("CONSUMER_SECRET")
    if not consumer_key or not consumer_secret:
        print("ERROR: Set CONSUMER_KEY and CONSUMER_SECRET env vars", file=sys.stderr)
        sys.exit(1)

    topic = args.topic or os.getenv("NTFY_TOPIC")
    if not topic:
        print("ERROR: Set --topic or NTFY_TOPIC env var to your ntfy topic", file=sys.stderr)
        sys.exit(1)

    # logging setup
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    log = logging.getLogger("watcher")

    api = StudentAppClient(consumer_key, consumer_secret)
    term = os.getenv("TERM_CODE") or latest_term_code(api)

    # Build mapping course_id -> set(classids)
    specs: List[CourseSpec] = []
    env_courses = os.getenv("COURSE_SPECS", "").split()
    for s in (args.courses or env_courses):
        specs.append(parse_course_arg(s))
    env_ids = os.getenv("ID_SPECS", "").split()
    for s in (args.ids or env_ids):
        specs.append(parse_course_arg(s))

    if not specs:
        print("Provide at least one course spec via --courses or --ids", file=sys.stderr)
        sys.exit(1)

    course_to_classes: Dict[str, List[str]] = {}
    for spec in specs:
        course_id, class_ids = resolve_course_to_ids(api, term, spec)
        course_to_classes.setdefault(course_id, [])
        # de-dup
        course_to_classes[course_id] = sorted(set(course_to_classes[course_id]) | set(class_ids))

    # Prepare polling
    target_course_ids = ",".join(course_to_classes.keys())
    target_classids_set = set([cid for lst in course_to_classes.values() for cid in lst])

    last_alert: Dict[str, Tuple[int, datetime]] = {}
    min_delta = timedelta(seconds=args.min_renotify_secs)

    log.info(
        "Started watcher (term %s); %d section(s) across %d course(s)",
        term,
        len(target_classids_set),
        len(course_to_classes),
    )
    ntfy_publish(
        topic,
        f"Watcher started (term {term}); monitoring {len(target_classids_set)} sections across {len(course_to_classes)} course(s)",
        title="TigerSnatch Watcher",
        priority="low",
        base=args.ntfy_url,
    )

    try:
        while True:
            try:
                seats = api.get_seats(term=term, course_ids_csv=target_course_ids)
                openings = compute_openings(seats, target_classids_set)
                if openings:
                    log.info("Openings: %s", ", ".join([f"{cid}:{n}" for cid, n, _, _ in openings]))
                for classid, n_open, courseid, obj in openings:
                    prev = last_alert.get(classid)
                    should_send = False
                    if prev is None:
                        should_send = True
                    else:
                        prev_n, prev_t = prev
                        if n_open != prev_n or (datetime.now(TZ) - prev_t) >= min_delta:
                            should_send = True

                    if should_send:
                        msg = (
                            f"{n_open} open spot(s): class {classid} in course {courseid}.\n"
                            f"Enroll via TigerHub; check details in TigerSnatch."
                        )
                        ntfy_publish(
                            topic,
                            msg,
                            title="Seat opening detected",
                            priority="high",
                            base=args.ntfy_url,
                        )
                        log.info("Notified for class %s (course %s) with %d open", classid, courseid, n_open)
                        last_alert[classid] = (n_open, datetime.now(TZ))
            except Exception as e:
                log.warning("poll error: %s", e)

            time.sleep(max(1, args.interval))
    except KeyboardInterrupt:
        log.info("Shutting down watcher")


if __name__ == "__main__":
    main()
