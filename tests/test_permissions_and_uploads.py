from io import BytesIO

from tests.support import ArtistApplication, FlaskBackendTestCase, User, db


class PermissionsAndUploadsTestCase(FlaskBackendTestCase):
    def test_artist_upload_requires_artist_role(self):
        user = self.create_user("listener")
        headers = self.auth_headers(user)

        response = self.client.post(
            "/songs/upload",
            headers=headers,
            data={"audio": (BytesIO(b"fake-audio"), "track.mp3")},
            content_type="multipart/form-data",
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(
            response.get_json()["error"],
            "Unauthorized: Only approved artists can upload songs.",
        )

    def test_artist_upload_requires_audio_file(self):
        artist = self.create_user("artist", is_artist=True)
        headers = self.auth_headers(artist)

        response = self.client.post(
            "/songs/upload",
            headers=headers,
            data={"title": "No Audio"},
            content_type="multipart/form-data",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["error"], "No audio file part")

    def test_artist_upload_rejects_invalid_audio_extension(self):
        artist = self.create_user("artist", is_artist=True)
        headers = self.auth_headers(artist)

        response = self.client.post(
            "/songs/upload",
            headers=headers,
            data={"audio": (BytesIO(b"fake-audio"), "track.txt")},
            content_type="multipart/form-data",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["error"], "Invalid file type")

    def test_artist_upload_rejects_duplicate_audio_content(self):
        artist = self.create_user("artist", is_artist=True)
        headers = self.auth_headers(artist)

        first = self.client.post(
            "/songs/upload",
            headers=headers,
            data={"audio": (BytesIO(b"same-bytes"), "one.mp3"), "title": "One"},
            content_type="multipart/form-data",
        )
        second = self.client.post(
            "/songs/upload",
            headers=headers,
            data={"audio": (BytesIO(b"same-bytes"), "two.mp3"), "title": "Two"},
            content_type="multipart/form-data",
        )

        self.assertEqual(first.status_code, 201, first.get_json())
        self.assertEqual(second.status_code, 409)
        self.assertEqual(second.get_json()["error"], "Duplicate song (same audio content)")

    def test_admin_upload_requires_admin_access(self):
        response = self.client.post(
            "/admin/upload",
            data={"audio": (BytesIO(b"admin-audio"), "admin.mp3")},
            content_type="multipart/form-data",
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.get_json()["error"], "Admin access required")

    def test_admin_upload_accepts_admin_secret(self):
        response = self.client.post(
            "/admin/upload",
            headers={"X-Admin-Secret": "unit-test-admin-secret"},
            data={"audio": (BytesIO(b"admin-audio"), "admin.mp3"), "title": "Admin Track"},
            content_type="multipart/form-data",
        )

        self.assertEqual(response.status_code, 201, response.get_json())
        self.assertEqual(response.get_json()["song"]["title"], "Admin Track")

    def test_non_admin_cannot_view_artist_applications(self):
        user = self.create_user("listener")
        headers = self.auth_headers(user)

        response = self.client.get("/admin/artist-applications", headers=headers)

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.get_json()["error"], "Admin access required")

    def test_admin_can_approve_artist_application(self):
        applicant = self.create_user("pending-user")
        admin = self.create_user("admin-user", is_admin=True)
        applicant_headers = self.auth_headers(applicant)
        admin_headers = self.auth_headers(admin)

        apply_response = self.client.post(
            "/artist/apply",
            headers=applicant_headers,
            json={
                "artist_name": "Pending Artist",
                "bio": "This biography is comfortably longer than fifty characters for validation.",
            },
        )
        application_id = apply_response.get_json()["application_id"]

        approve_response = self.client.post(
            f"/admin/artist-applications/{application_id}/approve",
            headers=admin_headers,
        )

        db.session.refresh(applicant)
        application = ArtistApplication.query.get(application_id)
        self.assertEqual(approve_response.status_code, 200)
        self.assertTrue(applicant.is_artist)
        self.assertEqual(application.status, "approved")
        self.assertEqual(application.reviewed_by, admin.id)
