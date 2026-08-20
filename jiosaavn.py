import json
import re
import requests

import endpoints
import helper

from traceback import print_exc
from urllib.parse import quote


# ============================================================
# SESSION
# ============================================================

session = requests.Session()

session.headers.update({
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 "
        "(KHTML, like Gecko) "
        "Chrome/151.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://www.jiosaavn.com/",
})

# Keep each upstream request bounded.  The first value limits TCP connection
# setup; the second limits waiting for a JioSaavn response.
REQUEST_TIMEOUT = (3.05, 8)


class JioSaavnUpstreamError(RuntimeError):
    """Raised when JioSaavn cannot provide a usable response."""


# ============================================================
# SEARCH
# ============================================================

def search_for_song(query, lyrics=False, songdata=False, page=1, limit=20):
    """
    Search JioSaavn songs.

    query  = search text
    page   = page number
    limit  = number of results

    Example:

        search_for_song(
            "the weekend",
            False,
            False,
            1,
            20
        )

    When songdata=False:
        Returns lightweight search results.

    When songdata=True:
        Fetches complete song information for every result.
    """

    query = (query or "").strip()

    if not query:
        return []

    # --------------------------------------------------------
    # Direct JioSaavn song URL
    # --------------------------------------------------------

    if query.startswith("http") and "saavn.com" in query:
        try:
            song_id = get_song_id(query)

            if song_id:
                return get_song(song_id, lyrics)

        except Exception:
            print_exc()

        return None


    # --------------------------------------------------------
    # Page
    # --------------------------------------------------------

    try:
        page = int(page)
    except (TypeError, ValueError):
        page = 1

    page = max(page, 1)


    # --------------------------------------------------------
    # Limit
    # --------------------------------------------------------

    try:
        limit = int(limit)
    except (TypeError, ValueError):
        limit = 20

    # Don't request crazy amounts.
    limit = max(1, min(limit, 50))


    # --------------------------------------------------------
    # JioSaavn search endpoint
    # --------------------------------------------------------

    search_url = (
        "https://www.jiosaavn.com/api.php"
        "?__call=search.getResults"
        f"&q={quote(query)}"
        f"&p={page}"
        f"&n={limit}"
        "&_format=json"
        "&_marker=0"
        "&api_version=4"
        "&ctx=web6dot0"
    )

    print()
    print("=" * 70)
    print("JioSaavn SEARCH")
    print("=" * 70)
    print("Query :", query)
    print("Page  :", page)
    print("Limit :", limit)
    print("URL   :", search_url)
    print("=" * 70)


    # --------------------------------------------------------
    # Request
    # --------------------------------------------------------

    try:

        response = session.get(search_url, timeout=REQUEST_TIMEOUT)

        print(
            "HTTP status:",
            response.status_code
        )

        print(
            "Response length:",
            len(response.text)
        )

        response.raise_for_status()

    except requests.RequestException as e:

        print(
            "JioSaavn request failed:",
            e
        )

        raise JioSaavnUpstreamError("JioSaavn search request failed") from e


    # --------------------------------------------------------
    # Parse JSON
    # --------------------------------------------------------

    data = _parse_json_response(
        response.text
    )

    if data is None:

        print(
            "Could not parse JioSaavn JSON."
        )

        print(
            response.text[:2000]
        )

        raise JioSaavnUpstreamError("JioSaavn returned invalid search JSON")


    # --------------------------------------------------------
    # Extract songs
    # --------------------------------------------------------

    songs_data = _extract_search_songs(
        data
    )


    print(
        "Raw JioSaavn songs:",
        len(songs_data)
    )


    if not songs_data:

        print(
            "No songs found in JioSaavn response."
        )

        print(
            "Response structure:"
        )

        try:
            print(
                json.dumps(
                    data,
                    indent=2,
                    ensure_ascii=False
                )[:5000]
            )

        except Exception:
            print(data)

        return []


    # --------------------------------------------------------
    # Return lightweight search data
    # --------------------------------------------------------

    if not songdata:

        return songs_data


    # --------------------------------------------------------
    # Full song information
    # --------------------------------------------------------

    songs = []

    for song in songs_data:

        try:

            if not isinstance(song, dict):
                continue

            song_id = str(
                song.get("id", "")
            ).strip()

            if not song_id:
                continue

            song_data = get_song(
                song_id,
                lyrics
            )

            if song_data:
                songs.append(
                    song_data
                )

        except Exception:

            print(
                "Error processing song:"
            )

            print_exc()


    print(
        "Complete songs:",
        len(songs)
    )

    return songs


# ============================================================
# JSON PARSER
# ============================================================

def _parse_json_response(text):
    """
    Safely parse JioSaavn response.

    JioSaavn has historically returned slightly different
    JSON formatting, so this parser has fallbacks.
    """

    if not text:
        return None

    text = text.strip()


    # --------------------------------------------------------
    # Normal JSON
    # --------------------------------------------------------

    try:

        return json.loads(text)

    except Exception:
        pass


    # --------------------------------------------------------
    # Remove prefix before JSON
    # --------------------------------------------------------

    json_start = text.find("{")

    if json_start > 0:

        cleaned = text[
            json_start:
        ]

        try:

            return json.loads(
                cleaned
            )

        except Exception:
            pass


    # --------------------------------------------------------
    # Old escaped Unicode response
    # --------------------------------------------------------

    try:

        decoded = (
            text
            .encode("utf-8")
            .decode("unicode-escape")
        )

        return json.loads(
            decoded
        )

    except Exception:
        pass


    # --------------------------------------------------------
    # Old "(From "...")" problem
    # --------------------------------------------------------

    try:

        fixed = re.sub(
            r'\(From "([^"]+)"\)',
            r"(From '\1')",
            text
        )

        return json.loads(
            fixed
        )

    except Exception:
        pass


    return None


# ============================================================
# SEARCH RESULT EXTRACTOR
# ============================================================

def _extract_search_songs(data):
    """
    Extract song list from multiple possible JioSaavn
    response structures.
    """

    if not isinstance(data, dict):
        return []


    # --------------------------------------------------------
    # Standard JioSaavn structure
    #
    # {
    #   "songs": {
    #       "data": [...]
    #   }
    # }
    # --------------------------------------------------------

    songs = data.get("songs")

    if isinstance(songs, dict):

        song_list = songs.get("data")

        if isinstance(song_list, list):
            return song_list


    # --------------------------------------------------------
    # Alternative:
    #
    # {
    #   "results": [...]
    # }
    # --------------------------------------------------------

    results = data.get("results")

    if isinstance(results, list):
        return results


    # --------------------------------------------------------
    # Alternative nested result
    # --------------------------------------------------------

    result = data.get("result")

    if isinstance(result, dict):

        nested_songs = result.get(
            "songs"
        )

        if isinstance(
            nested_songs,
            dict
        ):

            song_list = nested_songs.get(
                "data"
            )

            if isinstance(
                song_list,
                list
            ):
                return song_list


    # --------------------------------------------------------
    # data.results
    # --------------------------------------------------------

    nested_data = data.get("data")

    if isinstance(
        nested_data,
        dict
    ):

        nested_results = nested_data.get(
            "results"
        )

        if isinstance(
            nested_results,
            list
        ):
            return nested_results


        nested_songs = nested_data.get(
            "songs"
        )

        if isinstance(
            nested_songs,
            list
        ):
            return nested_songs


    return []


# ============================================================
# GET SONG
# ============================================================

def get_song(id, lyrics=False):

    try:

        id = str(id).strip()

        if not id:
            return None


        song_details_url = (
            endpoints.song_details_base_url
            + id
        )


        response = session.get(
            song_details_url,
            timeout=REQUEST_TIMEOUT
        )


        if response.status_code != 200:

            print(
                "Song details HTTP:",
                response.status_code
            )

            return None


        text = response.text


        # ----------------------------------------------------
        # Normal JSON
        # ----------------------------------------------------

        try:

            song_response = json.loads(
                text
            )

        except Exception:

            try:

                song_response = json.loads(
                    text
                    .encode()
                    .decode(
                        "unicode-escape"
                    )
                )

            except Exception:

                return None


        # ----------------------------------------------------
        # Find song object
        # ----------------------------------------------------

        song_object = None


        if isinstance(
            song_response,
            dict
        ):

            song_object = song_response.get(
                id
            )


            if song_object is None:

                song_object = song_response.get(
                    "song"
                )


            if song_object is None:

                song_object = song_response.get(
                    "data"
                )


        if not song_object:
            return None


        # ----------------------------------------------------
        # Format song
        # ----------------------------------------------------

        song_data = helper.format_song(
            song_object,
            lyrics
        )


        return song_data


    except Exception:

        print(
            "get_song error:"
        )

        print_exc()

        return None


# ============================================================
# GET SONG ID
# ============================================================

def get_song_id(url):

    try:

        response = session.get(
            url,
            timeout=REQUEST_TIMEOUT
        )


        text = response.text


        # ----------------------------------------------------
        # Modern pid
        # ----------------------------------------------------

        try:

            return (
                text
                .split('"pid":"')[1]
                .split('","')[0]
            )

        except IndexError:
            pass


        # ----------------------------------------------------
        # Older song object
        # ----------------------------------------------------

        try:

            return (
                text
                .split('"song":{"type":"')[1]
                .split('","image":')[0]
                .split('"id":"')[-1]
            )

        except IndexError:
            pass


    except Exception:

        print_exc()


    return None


# ============================================================
# ALBUM
# ============================================================

def get_album(album_id, lyrics=False):

    try:

        response = session.get(
            endpoints.album_details_base_url
            + str(album_id),
            timeout=REQUEST_TIMEOUT
        )


        if response.status_code != 200:
            return None


        text = response.text


        try:

            songs_json = json.loads(
                text
            )

        except Exception:

            songs_json = json.loads(
                text
                .encode()
                .decode(
                    "unicode-escape"
                )
            )


        return helper.format_album(
            songs_json,
            lyrics
        )


    except Exception as e:

        print(
            "get_album error:",
            e
        )

        print_exc()

        return None


# ============================================================
# ALBUM ID
# ============================================================

def get_album_id(input_url):

    try:

        response = session.get(
            input_url,
            timeout=REQUEST_TIMEOUT
        )


        text = response.text


        try:

            return (
                text
                .split('"album_id":"')[1]
                .split('"')[0]
            )

        except IndexError:
            pass


        try:

            return (
                text
                .split('"page_id","')[1]
                .split('","')[0]
            )

        except IndexError:
            pass


    except Exception:

        print_exc()


    return None


# ============================================================
# PLAYLIST
# ============================================================

def get_playlist(listId, lyrics=False):

    try:

        response = session.get(
            endpoints.playlist_details_base_url
            + str(listId),
            timeout=REQUEST_TIMEOUT
        )


        if response.status_code != 200:
            return None


        text = response.text


        try:

            songs_json = json.loads(
                text
            )

        except Exception:

            songs_json = json.loads(
                text
                .encode()
                .decode(
                    "unicode-escape"
                )
            )


        return helper.format_playlist(
            songs_json,
            lyrics
        )


    except Exception:

        print_exc()

        return None


# ============================================================
# PLAYLIST ID
# ============================================================

def get_playlist_id(input_url):

    try:

        response = session.get(
            input_url,
            timeout=REQUEST_TIMEOUT
        )


        text = response.text


        try:

            return (
                text
                .split(
                    '"type":"playlist","id":"'
                )[1]
                .split('"')[0]
            )

        except IndexError:
            pass


        try:

            return (
                text
                .split('"page_id","')[1]
                .split('","')[0]
            )

        except IndexError:
            pass


    except Exception:

        print_exc()


    return None


# ============================================================
# LYRICS
# ============================================================

def get_lyrics(id):

    try:

        url = (
            endpoints.lyrics_base_url
            + str(id)
        )


        response = session.get(
            url,
            timeout=REQUEST_TIMEOUT
        )


        response.raise_for_status()


        lyrics_json = json.loads(
            response.text
        )


        return lyrics_json.get(
            "lyrics",
            ""
        )


    except Exception:

        print_exc()

        return None
