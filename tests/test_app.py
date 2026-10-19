import os
import sqlite3
import tempfile
import unittest

from flask import current_app

from app import create_app


class TaskAppTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.app = create_app(
            {
                "TESTING": True,
                "SECRET_KEY": "test-secret",
                "DATABASE": os.path.join(self.temp_dir.name, "test.sqlite3"),
            }
        )
        self.client = self.app.test_client()

    def tearDown(self):
        self.temp_dir.cleanup()

    def post(self, url, data):
        with self.client.session_transaction() as session:
            token = session.get("_csrf_token")
        if token is None:
            self.client.get("/login")
            with self.client.session_transaction() as session:
                token = session.get("_csrf_token")
        return self.client.post(url, data={**data, "csrf_token": token})

    def register(self, username):
        return self.post(
            "/register", {"username": username, "password": "correct-horse"}
        )

    def test_register_create_edit_complete_and_delete_task(self):
        response = self.register("alice")
        self.assertEqual(response.status_code, 302)
        response = self.post(
            "/tasks", {"title": "Escribir", "description": "Primer borrador"}
        )
        self.assertEqual(response.status_code, 302)

        with self.client.session_transaction() as session:
            user_id = session["user_id"]
        with self.app.app_context():
            db = sqlite3.connect(current_app.config["DATABASE"])
            task_id = db.execute(
                "SELECT id FROM tasks WHERE user_id = ?", (user_id,)
            ).fetchone()[0]
            db.close()

        response = self.post(
            f"/tasks/{task_id}/edit",
            {"title": "Escribir hoy", "description": "Capítulo uno"},
        )
        self.assertEqual(response.status_code, 302)
        response = self.post(f"/tasks/{task_id}/toggle", {})
        self.assertEqual(response.status_code, 302)
        response = self.client.get("/tasks")
        self.assertIn(b"Escribir hoy", response.data)
        self.assertIn(b"is-complete", response.data)

        response = self.post(f"/tasks/{task_id}/delete", {})
        self.assertEqual(response.status_code, 302)
        self.assertNotIn(b"Escribir hoy", self.client.get("/tasks").data)

    def test_users_cannot_access_each_others_tasks(self):
        self.register("alice")
        self.post("/tasks", {"title": "Privada", "description": ""})
        self.post("/logout", {})
        self.register("bob")

        with self.app.app_context():
            db = sqlite3.connect(current_app.config["DATABASE"])
            task_id = db.execute("SELECT id FROM tasks").fetchone()[0]
            db.close()

        self.assertEqual(self.client.get(f"/tasks/{task_id}/edit").status_code, 404)
        self.assertEqual(
            self.post(
                f"/tasks/{task_id}/edit",
                {"title": "Robada", "description": ""},
            ).status_code,
            404,
        )
        self.assertEqual(self.post(f"/tasks/{task_id}/toggle", {}).status_code, 404)
        self.assertEqual(
            self.post(f"/tasks/{task_id}/delete", {}).status_code, 404
        )
        with self.app.app_context():
            db = sqlite3.connect(current_app.config["DATABASE"])
            task = db.execute(
                "SELECT title, completed FROM tasks WHERE id = ?", (task_id,)
            ).fetchone()
            self.assertEqual(task, ("Privada", 0))
            db.close()

    def test_login_requires_correct_password_and_csrf(self):
        self.register("alice")
        self.post("/logout", {})
        response = self.post(
            "/login", {"username": "alice", "password": "wrong-password"}
        )
        self.assertEqual(response.status_code, 200)
        with self.client.session_transaction() as session:
            self.assertNotIn("user_id", session)

        with self.client.session_transaction() as session:
            session.clear()
        response = self.client.post(
            "/login", data={"username": "alice", "password": "correct-horse"}
        )
        self.assertEqual(response.status_code, 400)

        self.client.get("/login")
        with self.client.session_transaction() as session:
            token = session["_csrf_token"]
        response = self.client.post(
            "/login",
            data={
                "username": "alice",
                "password": "correct-horse",
                "csrf_token": token,
            },
        )
        self.assertEqual(response.status_code, 302)


if __name__ == "__main__":
    unittest.main()
