from tests.support import FlaskBackendTestCase, PlaybackState, Playlist, PlaylistSong


class PlaylistRoutesTestCase(FlaskBackendTestCase):
    def test_create_and_list_playlists(self):
        user = self.create_user("owner")
        headers = self.auth_headers(user)

        create_response = self.client.post("/playlists", headers=headers, json={"name": "Roadtrip"})
        list_response = self.client.get("/playlists", headers=headers)

        self.assertEqual(create_response.status_code, 200, create_response.get_json())
        self.assertEqual(create_response.get_json()["name"], "Roadtrip")
        self.assertEqual(list_response.status_code, 200)
        self.assertEqual(len(list_response.get_json()), 1)
        self.assertEqual(list_response.get_json()[0]["name"], "Roadtrip")

    def test_playlist_routes_require_ownership(self):
        owner = self.create_user("owner")
        intruder = self.create_user("intruder")
        playlist = self.create_playlist(owner.id, name="Private")
        song = self.create_song("Secret Song")
        intruder_headers = self.auth_headers(intruder)

        get_response = self.client.get(f"/playlists/{playlist.id}", headers=intruder_headers)
        add_response = self.client.post(
            f"/playlists/{playlist.id}/add",
            headers=intruder_headers,
            json={"song_id": song.id},
        )

        self.assertEqual(get_response.status_code, 403)
        self.assertEqual(add_response.status_code, 403)

    def test_add_and_remove_song_from_playlist(self):
        user = self.create_user("owner")
        playlist = self.create_playlist(user.id, name="Favorites")
        song = self.create_song("Playlist Song")
        headers = self.auth_headers(user)

        add_response = self.client.post(
            f"/playlists/{playlist.id}/add",
            headers=headers,
            json={"song_id": song.id},
        )
        get_response = self.client.get(f"/playlists/{playlist.id}", headers=headers)
        remove_response = self.client.post(
            f"/playlists/{playlist.id}/remove",
            headers=headers,
            json={"song_id": song.id},
        )

        self.assertEqual(add_response.status_code, 200, add_response.get_json())
        self.assertEqual(len(get_response.get_json()["songs"]), 1)
        self.assertEqual(remove_response.status_code, 200)
        self.assertIsNone(
            PlaylistSong.query.filter_by(playlist_id=playlist.id, song_id=song.id).first()
        )

    def test_delete_playlist_removes_playlist_and_entries(self):
        user = self.create_user("owner")
        playlist = self.create_playlist(user.id, name="Disposable")
        song = self.create_song("Track")
        self.add_song_to_playlist(playlist.id, song.id)
        headers = self.auth_headers(user)

        response = self.client.delete(f"/playlists/{playlist.id}", headers=headers)

        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertIsNone(Playlist.query.get(playlist.id))
        self.assertEqual(PlaylistSong.query.filter_by(playlist_id=playlist.id).count(), 0)

    def test_play_playlist_loads_queue_into_playback_state(self):
        user = self.create_user("owner")
        playlist = self.create_playlist(user.id, name="Queued")
        first = self.create_song("First")
        second = self.create_song("Second")
        self.add_song_to_playlist(playlist.id, first.id)
        self.add_song_to_playlist(playlist.id, second.id)
        headers = self.auth_headers(user)

        response = self.client.post(f"/playlists/{playlist.id}/play", headers=headers)

        state = PlaybackState.query.filter_by(user_id=user.id).first()
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(response.get_json()["first_song"], first.id)
        self.assertEqual(state.current_song_id, first.id)
        self.assertEqual(state.original_queue, f"[{first.id}, {second.id}]")
