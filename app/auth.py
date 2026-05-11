import random
import string

from flask import Blueprint, redirect, render_template, request, url_for
from flask_login import LoginManager, UserMixin, current_user, login_required, login_user, logout_user
from werkzeug.security import check_password_hash, generate_password_hash

from app import db

login_manager = LoginManager()
login_manager.login_view = "auth.login"
login_manager.login_message = ""

auth_bp = Blueprint("auth", __name__)


class User(UserMixin):
    def __init__(self, user_row: dict):
        self.id = user_row["id"]
        self.email = user_row["email"]

    @staticmethod
    def get(user_id: int) -> "User | None":
        row = db.get_user_by_id(user_id)
        return User(row) if row else None


@login_manager.user_loader
def load_user(user_id: str) -> "User | None":
    return User.get(int(user_id))


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("index"))

    error = None
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        row = db.get_user_by_email(email)
        if row and check_password_hash(row["password_hash"], password):
            login_user(User(row), remember=True)
            return redirect(request.args.get("next") or url_for("index"))
        error = "Invalid email or password."

    return render_template("login.html", error=error)


@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("index"))

    error = None
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm", "")

        if not email or not password:
            error = "Email and password are required."
        elif password != confirm:
            error = "Passwords do not match."
        elif len(password) < 8:
            error = "Password must be at least 8 characters."
        elif db.get_user_by_email(email):
            error = "An account with that email already exists."
        else:
            password_hash = generate_password_hash(password)
            user_id = db.create_user(email, password_hash)
            # Seed notification/Resy settings from .env so first user keeps existing config
            db.seed_user_settings_from_env(user_id)
            # Generate an ntfy topic for the new user
            suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=6))
            db.save_user_settings({"NTFY_TOPIC": f"resy-notifier-{suffix}"}, user_id)
            row = db.get_user_by_id(user_id)
            login_user(User(row), remember=True)
            return redirect(url_for("index"))

    return render_template("register.html", error=error)


@auth_bp.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("auth.login"))
