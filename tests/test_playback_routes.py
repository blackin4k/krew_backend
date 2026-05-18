from tests.support import FlaskBackendTestCase, PlayLog, PlaybackState, db


class PlaybackRoutesTestCase(FlaskBackendTestCase):
    def test_player_play_requires_song_id(self):
        user = self.create_user("listener")
        headers = self.auth_headers(user)

        response = self.client.post("/player/play", headers=headers, json={})

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["error"], "song_id required")

    def test_player_play_sets_current_song_and_seeds_play_log(self):
        user = self.create_user("listener")
        song = self.create_song("First Song")
        headers = self.auth_headers(user)

        response = self.client.post(
            "/player/play",
            headers=headers,
            json={"song_id": song.id},
        )

        state = PlaybackState.query.filter_by(user_id=user.id).first()
        log = PlayLog.query.filter_by(user_id=user.id, song_id=song.id).first()

        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(response.get_json()["id"], song.id)
        self.assertEqual(state.current_song_id, song.id)
        self.assertIsNotNone(log)
        self.assertFalse(log.completed)

    def test_player_next_advances_queue_and_updates_history(self):
        user = self.create_user("listener")
        first = self.create_song("First")
        second = self.create_song("Second")
        third = self.create_song("Third")
        self.create_playback_state(
            user_id=user.id,
            current_song_id=first.id,
            original_queue=[second.id, third.id],
            history=[],
        )
        headers = self.auth_headers(user)

        response = self.client.post("/player/next", headers=headers)

        state = PlaybackState.query.filter_by(user_id=user.id).first()
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(response.get_json()["id"], second.id)
        self.assertEqual(state.current_song_id, second.id)
        self.assertEqual(state.history, f"[{first.id}]")
        self.assertEqual(state.original_queue, f"[{third.id}]")

    def test_player_prev_uses_history_and_requeues_current_song(self):
        user = self.create_user("listener")
        first = self.create_song("First")
        second = self.create_song("Second")
        third = self.create_song("Third")
        self.create_playback_state(
            user_id=user.id,
            current_song_id=second.id,
            original_queue=[third.id],
            history=[first.id],
        )
        headers = self.auth_headers(user)

        response = self.client.post("/player/prev", headers=headers)

        state = PlaybackState.query.filter_by(user_id=user.id).first()
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(response.get_json()["id"], first.id)
        self.assertEqual(state.current_song_id, first.id)
        self.assertEqual(state.history, "[]")
        self.assertEqual(state.original_queue, f"[{second.id}, {third.id}]")

    def test_record_play_updates_recent_log(self):
        user = self.create_user("listener")
        song = self.create_song("Tracked Song")
        db.session.add(
            PlayLog(
                user_id=user.id,
                song_id=song.id,
                listen_duration=20,
                completed=False,
            )
        )
        db.session.commit()
        headers = self.auth_headers(user)

        response = self.client.post(
            "/player/record-play",
            headers=headers,
            json={"song_id": song.id, "duration": 45},
        )

        logs = PlayLog.query.filter_by(user_id=user.id, song_id=song.id).all()
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(len(logs), 1)
        self.assertTrue(logs[0].completed)
        self.assertEqual(logs[0].listen_duration, 45)
