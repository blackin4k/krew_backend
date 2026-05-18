from tests.support import FlaskBackendTestCase, User


class AuthRoutesTestCase(FlaskBackendTestCase):
    def test_register_creates_user(self):
        response = self.client.post(
            "/auth/register",
            json={
                "username": "newuser",
                "email": "newuser@example.com",
                "password": "password123",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["msg"], "Registered successfully")
        self.assertIsNotNone(User.query.filter_by(username="newuser").first())

    def test_register_rejects_duplicate_identity(self):
        self.create_user("existing", email="existing@example.com")

        response = self.client.post(
            "/auth/register",
            json={
                "username": "existing",
                "email": "other@example.com",
                "password": "password123",
            },
        )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.get_json()["error"], "Username or email already exists")

    def test_login_returns_jwt_for_valid_credentials(self):
        self.create_user("listener")

        response = self.client.post(
            "/auth/login",
            json={"username": "listener", "password": "password123"},
        )

        body = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertIn("token", body)
        self.assertTrue(body["token"])

    def test_login_rejects_invalid_credentials(self):
        self.create_user("listener")

        response = self.client.post(
            "/auth/login",
            json={"username": "listener", "password": "wrong-password"},
        )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.get_json()["error"], "Invalid credentials")
