import os
from datetime import datetime

from flask import Flask, redirect, render_template, request, session, url_for, flash

from .models import db_session, init_db, User, Subscription, upsert_user
from .student_api import StudentAppClient, latest_term_code, resolve_course_to_ids


def create_app():
    app = Flask(__name__)
    app.secret_key = os.getenv("SECRET_KEY", "dev-secret-change-me")

    init_db()

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            token = request.form.get("token", "").strip()
            if token and token == os.getenv("ADMIN_TOKEN", token):
                session["token"] = token
                # Ensure a user row exists for this token
                upsert_user(token)
                return redirect(url_for("dashboard"))
            flash("Invalid token", "error")
        poll_interval = int(os.getenv("INTERVAL_SECS", "30"))
        renotify_secs = int(os.getenv("MIN_RENOTIFY_SECS", "20"))
        return render_template("login.html", poll_interval=poll_interval, renotify_secs=renotify_secs)

    def _require_login():
        tok = session.get("token")
        if not tok:
            return False
        return True

    @app.route("/")
    def index():
        if not _require_login():
            return redirect(url_for("login"))
        return redirect(url_for("dashboard"))

    @app.route("/healthz")
    def healthz():
        return "ok", 200

    @app.route("/dashboard")
    def dashboard():
        if not _require_login():
            return redirect(url_for("login"))
        token = session["token"]
        user = db_session.query(User).filter_by(token=token).first()
        subs = (
            db_session.query(Subscription)
            .filter_by(user_id=user.id)
            .order_by(Subscription.course_code, Subscription.classid)
            .all()
        )
        poll_interval = int(os.getenv("INTERVAL_SECS", "30"))
        renotify_secs = int(os.getenv("MIN_RENOTIFY_SECS", "20"))
        return render_template("dashboard.html", user=user, subs=subs, poll_interval=poll_interval, renotify_secs=renotify_secs)

    @app.route("/set_topic", methods=["POST"])
    def set_topic():
        if not _require_login():
            return redirect(url_for("login"))
        token = session["token"]
        user = db_session.query(User).filter_by(token=token).first()
        user.ntfy_topic = request.form.get("ntfy_topic", "").strip()
        db_session.commit()
        flash("Topic saved", "success")
        return redirect(url_for("dashboard"))

    @app.route("/search", methods=["GET", "POST"])
    def search():
        if not _require_login():
            return redirect(url_for("login"))
        course_code = request.values.get("code", "").upper().strip()
        sections = []
        error = None
        if course_code:
            try:
                client = StudentAppClient(
                    os.environ["CONSUMER_KEY"], os.environ["CONSUMER_SECRET"]
                )
                term = os.getenv("TERM_CODE") or latest_term_code(client)
                # resolve to classids and also show section names
                course_id, classids, meta = resolve_course_to_ids(
                    client, term, course_code
                )
                sections = meta  # list of dicts: {classid, section}
            except Exception as e:
                error = str(e)
        return render_template("search.html", code=course_code, sections=sections, error=error)

    @app.route("/subscribe", methods=["POST"])
    def subscribe():
        if not _require_login():
            return redirect(url_for("login"))
        token = session["token"]
        user = db_session.query(User).filter_by(token=token).first()
        course_code = request.form.get("course_code").upper().strip()
        selected = request.form.getlist("sections")  # classids
        if not selected:
            flash("No sections selected", "error")
            return redirect(url_for("search", code=course_code))
        try:
            client = StudentAppClient(os.environ["CONSUMER_KEY"], os.environ["CONSUMER_SECRET"])
            term = os.getenv("TERM_CODE") or latest_term_code(client)
            course_id, _classids, meta = resolve_course_to_ids(client, term, course_code)
            picked = [m for m in meta if str(m["classid"]) in selected]
            for m in picked:
                sub = (
                    db_session.query(Subscription)
                    .filter_by(user_id=user.id, course_id=course_id, classid=str(m["classid"]))
                    .first()
                )
                if not sub:
                    sub = Subscription(
                        user_id=user.id,
                        course_code=course_code,
                        course_id=course_id,
                        classid=str(m["classid"]),
                        section=m["section"],
                        last_notified_open=-1,
                    )
                    db_session.add(sub)
            db_session.commit()
            flash("Subscribed", "success")
        except Exception as e:
            flash(str(e), "error")
        return redirect(url_for("dashboard"))

    @app.route("/unsubscribe/<int:sub_id>", methods=["POST"])
    def unsubscribe(sub_id: int):
        if not _require_login():
            return redirect(url_for("login"))
        token = session["token"]
        user = db_session.query(User).filter_by(token=token).first()
        sub = db_session.query(Subscription).filter_by(id=sub_id, user_id=user.id).first()
        if sub:
            db_session.delete(sub)
            db_session.commit()
            flash("Unsubscribed", "success")
        return redirect(url_for("dashboard"))

    return app


app = create_app()
