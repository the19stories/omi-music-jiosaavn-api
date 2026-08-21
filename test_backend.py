import unittest
from unittest.mock import patch

import app
import jiosaavn


def song(song_id, title, artist, album="", language=""):
    return {
        "id": song_id,
        "title": title,
        "primary_artists": artist,
        "album": album,
        "language": language,
    }


class SearchRankingTests(unittest.TestCase):
    def test_exact_title_wins_and_duplicate_ids_are_removed(self):
        results = jiosaavn.rank_search_results([
            song("1", "A Different Title", "Someone"),
            song("2", "Blinding Lights", "The Weeknd"),
            song("2", "Blinding Lights (duplicate)", "The Weeknd"),
            song("3", "Blinding Lights Remix", "The Weeknd"),
        ], "Blinding Lights")
        self.assertEqual([item["id"] for item in results], ["2", "3", "1"])

    def test_artist_alias_and_language_rank_highest(self):
        artist_results = jiosaavn.rank_search_results([
            song("1", "Weekend Party", "DJ Example"),
            song("2", "Starboy", "The Weeknd"),
        ], "the weekend")
        language_results = jiosaavn.rank_search_results([
            song("1", "Hindi Song", "Artist", language="hindi"),
            song("2", "Telugu Song", "Artist", language="telugu"),
        ], "Telugu")
        self.assertEqual(artist_results[0]["id"], "2")
        self.assertEqual(language_results[0]["id"], "2")

    def test_current_nested_artist_map_is_ranked(self):
        nested_artist = song("1", "Starboy", "")
        nested_artist["more_info"] = {
            "artistMap": {"primary_artists": [{"name": "The Weeknd"}]}
        }
        results = jiosaavn.rank_search_results([
            song("2", "Weekend Party", "DJ Example"), nested_artist,
        ], "the weekend")
        self.assertEqual(results[0]["id"], "1")


class ApiValidationTests(unittest.TestCase):
    def setUp(self):
        app.app.config.update(TESTING=True)
        app._rate_limit_buckets.clear()
        self.client = app.app.test_client()

    def test_healthz(self):
        response = self.client.get("/healthz")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"success": True, "status": "ok"})

    def test_result_validation(self):
        self.assertEqual(self.client.get("/result/").status_code, 400)
        self.assertEqual(self.client.get("/result/?query=x&page=0").status_code, 400)
        self.assertEqual(self.client.get("/result/?query=x&limit=51").status_code, 400)
        self.assertEqual(
            self.client.get("/result/?query=" + ("x" * 201)).status_code, 400)

    @patch("app.jiosaavn.search_for_song")
    def test_result_keeps_compatible_success_shape(self, search_for_song):
        search_for_song.return_value = [song("1", "Test", "Artist")]
        response = self.client.get("/result/?query=Test")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {
            "success": True,
            "results": [song("1", "Test", "Artist")],
        })
        search_for_song.assert_called_once_with("Test", False, False, page=1, limit=20)


if __name__ == "__main__":
    unittest.main()
