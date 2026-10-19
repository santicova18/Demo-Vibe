import hmac
import os
import secrets
import sqlite3
from functools import wraps
from pathlib import Path

from flask import (
    Flask,
    abort,
    current_app,
    flash,
    g,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash


def create_app(test_config=None):
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_mapping(
        SECRET_KEY=os.environ.get("SECRET_KEY") or secrets.token_hex(32),
        DATABASE=str(Path(app.instance_path) / "tasks.sqlite3"),
    )
    if test_config:
        app.config.update(test_config)

    Path(app.instance_path).mkdir(parents=True, exist_ok=True)
    init_db(app)

    @app.before_request
    def load_user_and_check_csrf():
        g.user = None
        user_id = session.get("user_id")
        if user_id is not None:
            g.user = get_db().execute(
                "SELECT id, username FROM users WHERE id = ?", (user_id,)
            ).fetchone()

        if request.method == "POST":
            submitted = request.form.get("csrf_token", "")
            expected = session.get("_csrf_token", "")
            if not expected or not hmac.compare_digest(submitted, expected):
                abort(
                    400,
                    description="El formulario expiró. Recarga la página e inténtalo de nuevo.",
                )

    @app.context_processor
    def provide_csrf_token():
        def csrf_token():
            token = session.get("_csrf_token")
            if token is None:
                token = secrets.token_urlsafe(32)
                session["_csrf_token"] = token
            return token

        return {"csrf_token": csrf_token}

    app.teardown_appcontext(close_db)

    def login_required(view):
        @wraps(view)
        def wrapped_view(**kwargs):
            if g.user is None:
                flash("Inicia sesión para continuar.", "info")
                return redirect(url_for("login"))
            return view(**kwargs)

        return wrapped_view

    @app.route("/")
    def index():
        if g.user is None:
            return redirect(url_for("login"))
        return redirect(url_for("tasks"))

    @app.route("/register", methods=("GET", "POST"))
    def register():
        if request.method == "POST":
            username = request.form.get("username", "").strip()
            password = request.form.get("password", "")
            error = None

            if not 3 <= len(username) <= 30:
                error = "El nombre de usuario debe tener entre 3 y 30 caracteres."
            elif len(password) < 8:
                error = "La contraseña debe tener al menos 8 caracteres."

            if error is None:
                try:
                    get_db().execute(
                        "INSERT INTO users (username, password_hash) VALUES (?, ?)",
                        (username, generate_password_hash(password)),
                    )
                    get_db().commit()
                except sqlite3.IntegrityError:
                    error = "Ese nombre de usuario ya está en uso."
                else:
                    session.clear()
                    user = get_db().execute(
                        "SELECT id FROM users WHERE username = ?", (username,)
                    ).fetchone()
                    session["user_id"] = user["id"]
                    session["_csrf_token"] = secrets.token_urlsafe(32)
                    flash("Tu cuenta está lista. ¡Añade tu primera tarea!", "success")
                    return redirect(url_for("tasks"))

            flash(error, "error")

        return render_template("auth.html", mode="register")

    @app.route("/login", methods=("GET", "POST"))
    def login():
        if request.method == "POST":
            username = request.form.get("username", "").strip()
            password = request.form.get("password", "")
            user = get_db().execute(
                "SELECT id, username, password_hash FROM users WHERE username = ?",
                (username,),
            ).fetchone()

            if user is None or not check_password_hash(user["password_hash"], password):
                flash("El usuario o la contraseña no son correctos.", "error")
            else:
                session.clear()
                session["user_id"] = user["id"]
                session["_csrf_token"] = secrets.token_urlsafe(32)
                flash(f"¡Qué bueno verte, {user['username']}!", "success")
                return redirect(url_for("tasks"))

        return render_template("auth.html", mode="login")

    @app.route("/logout", methods=("POST",))
    @login_required
    def logout():
        session.clear()
        flash("Has cerrado sesión.", "info")
        return redirect(url_for("login"))

    @app.route("/tasks", methods=("GET", "POST"))
    @login_required
    def tasks():
        if request.method == "POST":
            title = request.form.get("title", "").strip()
            description = request.form.get("description", "").strip()
            error = validate_task(title, description)
            if error:
                flash(error, "error")
            else:
                get_db().execute(
                    "INSERT INTO tasks (user_id, title, description) VALUES (?, ?, ?)",
                    (g.user["id"], title, description),
                )
                get_db().commit()
                flash("Tarea añadida.", "success")
                return redirect(url_for("tasks"))

        task_rows = get_db().execute(
            """SELECT id, title, description, completed, created_at
               FROM tasks WHERE user_id = ?
               ORDER BY completed ASC, created_at DESC, id DESC""",
            (g.user["id"],),
        ).fetchall()
        return render_template("tasks.html", tasks=task_rows)

    @app.route("/tasks/<int:task_id>/edit", methods=("GET", "POST"))
    @login_required
    def edit_task(task_id):
        task = owned_task_or_404(task_id)
        if request.method == "POST":
            title = request.form.get("title", "").strip()
            description = request.form.get("description", "").strip()
            error = validate_task(title, description)
            if error:
                flash(error, "error")
            else:
                get_db().execute(
                    """UPDATE tasks SET title = ?, description = ?
                       WHERE id = ? AND user_id = ?""",
                    (title, description, task_id, g.user["id"]),
                )
                get_db().commit()
                flash("Cambios guardados.", "success")
                return redirect(url_for("tasks"))

        return render_template("edit_task.html", task=task)

    @app.route("/tasks/<int:task_id>/toggle", methods=("POST",))
    @login_required
    def toggle_task(task_id):
        task = owned_task_or_404(task_id)
        get_db().execute(
            "UPDATE tasks SET completed = ? WHERE id = ? AND user_id = ?",
            (0 if task["completed"] else 1, task_id, g.user["id"]),
        )
        get_db().commit()
        return redirect(url_for("tasks"))

    @app.route("/tasks/<int:task_id>/delete", methods=("POST",))
    @login_required
    def delete_task(task_id):
        owned_task_or_404(task_id)
        get_db().execute(
            "DELETE FROM tasks WHERE id = ? AND user_id = ?",
            (task_id, g.user["id"]),
        )
        get_db().commit()
        flash("Tarea eliminada.", "info")
        return redirect(url_for("tasks"))

    return app


def validate_task(title, description):
    if not title:
        return "El título de la tarea es obligatorio."
    if len(title) > 120:
        return "El título no puede superar los 120 caracteres."
    if len(description) > 1000:
        return "La descripción no puede superar los 1000 caracteres."
    return None


def owned_task_or_404(task_id):
    task = get_db().execute(
        """SELECT id, title, description, completed
           FROM tasks WHERE id = ? AND user_id = ?""",
        (task_id, g.user["id"]),
    ).fetchone()
    if task is None:
        abort(404)
    return task


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(current_app.config["DATABASE"])
        g.db.row_factory = sqlite3.Row
    return g.db


def close_db(_error=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db(app):
    db = sqlite3.connect(app.config["DATABASE"])
    try:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                title TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                completed INTEGER NOT NULL DEFAULT 0 CHECK (completed IN (0, 1)),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS tasks_user_id_idx ON tasks(user_id);
            """
        )
    finally:
        db.close()


app = create_app()


if __name__ == "__main__":
    app.run(debug=os.environ.get("FLASK_DEBUG") == "1")
