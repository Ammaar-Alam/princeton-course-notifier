import base64
import os
import requests


BASE = "https://api.princeton.edu:443/student-app/1.0.3"
TOKEN_URL = "https://api.princeton.edu:443/token"


class StudentAppClient:
    def __init__(self, consumer_key: str, consumer_secret: str):
        self.ck = consumer_key
        self.cs = consumer_secret
        self.token = None

    def _ensure_token(self):
        if self.token:
            return
        auth = base64.b64encode(f"{self.ck}:{self.cs}".encode()).decode()
        r = requests.post(TOKEN_URL, data={"grant_type": "client_credentials"}, headers={"Authorization": f"Basic {auth}"}, timeout=20)
        r.raise_for_status()
        self.token = r.json()["access_token"]

    def _get(self, path: str, params: dict):
        self._ensure_token()
        r = requests.get(f"{BASE}{path}", params=params, headers={"Authorization": f"Bearer {self.token}"}, timeout=30)
        if r.status_code == 401:
            self.token = None
            self._ensure_token()
            r = requests.get(f"{BASE}{path}", params=params, headers={"Authorization": f"Bearer {self.token}"}, timeout=30)
        r.raise_for_status()
        return r.json()

    def get_terms(self):
        return self._get("/courses/terms", {"fmt": "json"})

    def get_courses(self, term: str, subject: str, catnum: str):
        if not catnum.startswith(" "):
            catnum = f" {catnum}"
        return self._get("/courses/courses", {"fmt": "json", "term": term, "subject": subject, "catnum": catnum})

    def get_seats(self, term: str, course_ids_csv: str):
        return self._get("/courses/seats", {"fmt": "json", "term": term, "course_ids": course_ids_csv})


def latest_term_code(api: StudentAppClient) -> str:
    data = api.get_terms()
    terms = data.get("term", []) if isinstance(data, dict) else []
    if not terms:
        raise RuntimeError("No terms found")
    for key in ("code", "term_code", "strm"):
        if key in terms[-1]:
            return terms[-1][key]
    for item in reversed(terms):
        for key, val in item.items():
            if isinstance(val, str) and val.isdigit():
                return val
    raise RuntimeError("Unable to resolve term code")


def resolve_course_to_ids(api: StudentAppClient, term: str, course_code: str):
    subj = course_code[:3]
    cat = course_code[3:]
    data = api.get_courses(term=term, subject=subj, catnum=cat)
    term_list = data.get("term", []) if isinstance(data, dict) else []
    if not term_list:
        raise RuntimeError(f"No data for {course_code}")
    course_id = None
    classes = []
    meta = []
    for subj_obj in term_list[0].get("subjects", []):
        for course in subj_obj.get("courses", []):
            disp = f"{subj_obj.get('code','')}{course.get('catalog_number','')}"
            if disp.upper() != course_code.upper():
                continue
            course_id = course.get("course_id")
            for c in course.get("classes", []):
                classid = str(c.get("class_number"))
                section = c.get("section")
                meta.append({"classid": classid, "section": section})
                classes.append(classid)
            break
        if course_id:
            break
    if not course_id or not classes:
        raise RuntimeError(f"Could not resolve classes for {course_code}")
    return course_id, classes, meta

