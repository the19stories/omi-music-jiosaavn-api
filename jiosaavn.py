import json
import re
import requests
import html
import unicodedata

import endpoints
import helper

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


# Keep the search request to one upstream call.  This deliberately only fixes a
# very common misspelling; a broad fuzzy-correction list would make title
# searches less predictable.
QUERY_ALIASES = {
    "the weekend": "the weeknd",
}

# These are metadata categories, not aliases.  Keeping this deliberately small
# prevents an ordinary artist or title query from being mistaken for a language.
LANGUAGE_QUERIES = {"telugu"}

# Release descriptors are ignored only when comparing a song's core title.  A
# result still keeps its original title in the API response.
TITLE_VERSION_SUFFIX = re.compile(
    r"\b(?:remix|remastered|live|acoustic|instrumental|karaoke|version|edit|mix)\b.*$",
    re.IGNORECASE,
)


def normalize_search_text(value):
    """Return a case-, punctuation-, whitespace-, and accent-insensitive key."""
    value = html.unescape(str(value or ""))
    value = unicodedata.normalize("NFKD", value)
    value = "".join(char for char in value if not unicodedata.combining(char))
    value = value.casefold()
    return " ".join(re.sub(r"[^\w]+", " ", value, flags=re.UNICODE).split())


def canonical_search_query(query):
    """Apply safe query aliases after normalization."""
    normalized = normalize_search_text(query)
    return QUERY_ALIASES.get(normalized, normalized)


def normalized_title_identity(value):
    """Return a title key that groups legitimate release variants together."""
    text = normalize_search_text(value)
    text = TITLE_VERSION_SUFFIX.sub("", text).strip()
    return text


def _song_field(song, *keys):
    """Read a search-result field, including the occasional nested metadata."""
    for key in keys:
        value = song.get(key)
        if value:
            return str(value)
    more_info = song.get("more_info")
    if isinstance(more_info, dict):
        for key in keys:
            value = more_info.get(key)
            if value:
                return str(value)
    return ""


def _artist_values(song):
    """Collect individual artists from both legacy and current result shapes."""
    values = [_song_field(song, "primary_artists", "singers", "artist", "music")]
    more_info = song.get("more_info")
    if isinstance(more_info, dict):
        artist_map = more_info.get("artistMap")
        if isinstance(artist_map, dict):
            # Primary artists are most relevant, while the full artist list
            # preserves useful singer/composer matches when that is all Saavn
            # returns.
            for group in ("primary_artists", "featured_artists", "artists"):
                for artist in artist_map.get(group, []) or []:
                    if isinstance(artist, dict) and artist.get("name"):
                        values.append(str(artist["name"]))
    return [value for value in values if value]


def _primary_artist_values(song):
    """Read only primary artist metadata; never infer an artist from credits."""
    source = song.get("primary_artists")
    more_info = song.get("more_info")
    if not source and isinstance(more_info, dict):
        artist_map = more_info.get("artistMap")
        if isinstance(artist_map, dict):
            source = artist_map.get("primary_artists")

    if isinstance(source, dict):
        source = [source]
    if not isinstance(source, list):
        source = [source] if source else []

    names = []
    for artist in source:
        value = artist.get("name") if isinstance(artist, dict) else artist
        if value:
            names.extend(str(value).split(","))
    return [name.strip() for name in names if name and name.strip()]


def _deduplicate_search_songs(songs):
    """Keep first-seen IDs before classifying search intent."""
    deduplicated = []
    seen_ids = set()
    for song in songs or []:
        if not isinstance(song, dict):
            continue
        song_id = str(song.get("id", "")).strip()
        if song_id and song_id in seen_ids:
            continue
        if song_id:
            seen_ids.add(song_id)
        deduplicated.append(song)
    return deduplicated


def _match_strength(query, value):
    """Score a field using the documented relevance categories."""
    if not value:
        return 0
    if query == value:
        return 1_000
    if len(query) >= 3 and (query in value or value in query):
        return 700
    query_tokens = set(query.split())
    value_tokens = set(value.split())
    if query_tokens and value_tokens:
        overlap = len(query_tokens & value_tokens)
        if overlap:
            return 200 + int(200 * overlap / len(query_tokens))
    return 0


def _all_query_tokens_match(query, value):
    query_tokens = set(query.split())
    return bool(query_tokens) and query_tokens.issubset(set(value.split()))


def _search_intent(query, candidates):
    """Infer intent from strong upstream metadata without a broad alias list."""
    if query in LANGUAGE_QUERIES:
        return "language"
    for song in candidates:
        if not isinstance(song, dict):
            continue
        if any(
            _match_strength(query, normalize_search_text(artist)) >= 700
            for artist in _primary_artist_values(song)
        ):
            return "artist"
    for song in candidates:
        if not isinstance(song, dict):
            continue
        title = _song_field(song, "title", "song", "name")
        if query == normalized_title_identity(title):
            return "title"
    return "general"


def rank_search_results(songs, query):
    """Deduplicate, score, and safely filter existing JioSaavn results."""
    normalized_query = canonical_search_query(query)
    if not normalized_query:
        return []

    songs = _deduplicate_search_songs(songs)
    intent = _search_intent(normalized_query, songs)

    ranked = []
    seen_ids = set()
    for upstream_index, song in enumerate(songs):

        title = normalize_search_text(_song_field(song, "title", "song", "name"))
        title_identity = normalized_title_identity(
            _song_field(song, "title", "song", "name"))
        artists = [normalize_search_text(value) for value in _artist_values(song)]
        primary_artists = [
            normalize_search_text(value) for value in _primary_artist_values(song)
        ]
        album = normalize_search_text(_song_field(song, "album"))
        language = normalize_search_text(_song_field(song, "language"))

        title_match = _match_strength(normalized_query, title)
        artist_match = max(
            (_match_strength(normalized_query, artist) for artist in artists),
            default=0,
        )
        primary_artist_match = max(
            (_match_strength(normalized_query, artist) for artist in primary_artists),
            default=0,
        )
        album_match = _match_strength(normalized_query, album)
        language_match = _match_strength(normalized_query, language)

        # Do not let a provider-side fuzzy match leak unrelated songs into the
        # response.  Title identity keeps remix/live/acoustic variants. Artist
        # intent requires primary artist metadata because provider titles and
        # composer credits can mention artists for unrelated covers, karaoke
        # tracks, and emulations.
        title_identity_match = (
            title_identity == normalized_query
            or _all_query_tokens_match(normalized_query, title_identity)
        )
        if intent == "artist" and primary_artist_match < 700:
            continue
        if intent == "title" and not title_identity_match:
            continue
        if intent == "language" and language_match < 700:
            continue
        if intent == "general" and max(
            title_match, artist_match, album_match, language_match
        ) < 200:
            continue

        # Category weights preserve the requested precedence.  Language is
        # treated as metadata around album strength so searches such as
        # "Telugu" don't get buried beneath unrelated results.
        if title_identity == normalized_query:
            score = 7_000
        elif primary_artist_match == 1_000:
            score = 6_500
        elif artist_match == 1_000:
            score = 6_000
        elif title_match >= 700:
            score = 5_000 + title_match
        elif primary_artist_match >= 700:
            score = 4_500 + primary_artist_match
        elif artist_match >= 700:
            score = 4_000 + artist_match
        elif album_match:
            score = 3_000 + album_match
        elif language_match:
            score = 2_900 + language_match
        else:
            score = max(title_match, artist_match, album_match, language_match)

        ranked.append((-score, upstream_index, song))

    ranked.sort(key=lambda item: (item[0], item[1]))
    return [song for _, _, song in ranked]


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

    upstream_query = canonical_search_query(query) or query

    # --------------------------------------------------------
    # Direct JioSaavn song URL
    # --------------------------------------------------------

    if query.startswith("http") and "saavn.com" in query:
        try:
            song_id = get_song_id(query)

            if song_id:
                return get_song(song_id, lyrics)

        except Exception:
            pass

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

    # Ask for a bounded pool larger than the client page.  Filtering after only
    # the first requested items can otherwise leave a sparse, low-quality page.
    upstream_limit = min(max(limit * 4, 20), 50)
    search_url = (
        "https://www.jiosaavn.com/api.php"
        "?__call=search.getResults"
        f"&q={quote(upstream_query)}"
        f"&p={page}"
        f"&n={upstream_limit}"
        "&_format=json"
        "&_marker=0"
        "&api_version=4"
        "&ctx=web6dot0"
    )

    # --------------------------------------------------------
    # Request
    # --------------------------------------------------------

    try:

        response = session.get(search_url, timeout=REQUEST_TIMEOUT)

        response.raise_for_status()

    except requests.RequestException as exc:
        raise JioSaavnUpstreamError("JioSaavn search request failed") from exc


    # --------------------------------------------------------
    # Parse JSON
    # --------------------------------------------------------

    data = _parse_json_response(
        response.text
    )

    if data is None:

        raise JioSaavnUpstreamError("JioSaavn returned invalid search JSON")


    # --------------------------------------------------------
    # Extract songs
    # --------------------------------------------------------

    songs_data = _extract_search_songs(
        data
    )


    if not songs_data:
        return []

    songs_data = rank_search_results(songs_data, query)[:limit]


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
            continue


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
        pass


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


    except Exception:
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
        pass


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
        pass

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
        pass


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
        return None
