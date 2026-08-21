from flask import Flask, request, redirect, jsonify
import os
import threading
import time
import jiosaavn
from flask_cors import CORS


app = Flask(__name__)
CORS(app)

MAX_QUERY_LENGTH = 200
MAX_PAGE = 1_000
MAX_LIMIT = 50
RATE_LIMIT_REQUESTS = 120
RATE_LIMIT_WINDOW_SECONDS = 60
_rate_limit_lock = threading.Lock()
_rate_limit_buckets = {}


def api_error(message, status=502):
    return jsonify({"success": False, "status": False, "error": message}), status


def _validated_query(error_message):
    query = request.args.get("query", "").strip()
    if not query:
        return None, api_error(error_message, 400)
    if len(query) > MAX_QUERY_LENGTH:
        return None, api_error(
            f"Query must be {MAX_QUERY_LENGTH} characters or fewer.", 400)
    return query, None


def _validated_positive_int(name, default, maximum):
    raw_value = request.args.get(name)
    if raw_value is None:
        return default, None
    try:
        value = int(raw_value)
    except (TypeError, ValueError):
        return None, api_error(f"{name.title()} must be a whole number.", 400)
    if not 1 <= value <= maximum:
        return None, api_error(
            f"{name.title()} must be between 1 and {maximum}.", 400)
    return value, None


@app.before_request
def rate_limit():
    """Small in-memory limiter suitable for an individual Render worker."""
    if request.endpoint in {"healthz", "static"}:
        return None
    now = time.monotonic()
    client = request.headers.get("X-Forwarded-For", request.remote_addr or "unknown")
    client = client.split(",", 1)[0].strip()
    with _rate_limit_lock:
        window_start, count = _rate_limit_buckets.get(client, (now, 0))
        if now - window_start >= RATE_LIMIT_WINDOW_SECONDS:
            window_start, count = now, 0
        count += 1
        _rate_limit_buckets[client] = (window_start, count)
        if len(_rate_limit_buckets) > 10_000:
            stale_before = now - RATE_LIMIT_WINDOW_SECONDS
            for key, (started, _) in list(_rate_limit_buckets.items()):
                if started < stale_before:
                    _rate_limit_buckets.pop(key, None)
    if count > RATE_LIMIT_REQUESTS:
        return api_error("Too many requests. Please try again shortly.", 429)
    return None


@app.route('/healthz')
def healthz():
    return jsonify({"success": True, "status": "ok"})


# ============================================================
# HOME
# ============================================================

@app.route('/')
def home():
    return redirect(
        "https://cyberboysumanjay.github.io/JioSaavnAPI/"
    )


# ============================================================
# SONG SEARCH
# ============================================================

@app.route('/song/')
def search():

    lyrics = False
    songdata = True

    query, error = _validated_query("Query is required to search songs!")
    if error:
        return error

    lyrics_ = request.args.get(
        'lyrics'
    )

    songdata_ = request.args.get(
        'songdata'
    )

    page, error = _validated_positive_int("page", 1, MAX_PAGE)
    if error:
        return error
    limit, error = _validated_positive_int("limit", 20, MAX_LIMIT)
    if error:
        return error

    if lyrics_ and lyrics_.lower() != 'false':
        lyrics = True

    if songdata_ and songdata_.lower() != 'true':
        songdata = False

    try:

        results = jiosaavn.search_for_song(
            query,
            lyrics,
            songdata,
            page=page,
            limit=limit
        )

        return jsonify({"success": True, "results": results or []})

    except Exception:
        return api_error("Unable to fetch search results")


# ============================================================
# GET SINGLE SONG
# ============================================================

@app.route('/song/get/')
def get_song():

    lyrics = False

    song_id = request.args.get(
        'id'
    )

    lyrics_ = request.args.get(
        'lyrics'
    )

    if lyrics_ and lyrics_.lower() != 'false':
        lyrics = True

    if not song_id:
        return api_error("Song ID is required to get a song!", 400)

    try:

        resp = jiosaavn.get_song(
            song_id,
            lyrics
        )

        if not resp:

            return api_error("Invalid Song ID received!", 404)

        return jsonify({"success": True, "result": resp})

    except Exception:
        return api_error("Unable to fetch song details")


# ============================================================
# PLAYLIST
# ============================================================

@app.route('/playlist/')
def playlist():

    lyrics = False

    query = request.args.get(
        'query'
    )

    lyrics_ = request.args.get(
        'lyrics'
    )

    if lyrics_ and lyrics_.lower() != 'false':
        lyrics = True

    if not query:
        return jsonify({
            "status": False,
            "error": "Query is required to search playlists!"
        })

    try:

        playlist_id = jiosaavn.get_playlist_id(
            query
        )

        if not playlist_id:

            return jsonify({
                "status": False,
                "error": "Invalid playlist!"
            })

        songs = jiosaavn.get_playlist(
            playlist_id,
            lyrics
        )

        return jsonify(
            songs if songs else []
        )

    except Exception:
        return jsonify({
            "status": False,
            "error": "Unable to fetch playlist details"
        })


# ============================================================
# ALBUM
# ============================================================

@app.route('/album/')
def album():

    lyrics = False

    query = request.args.get(
        'query'
    )

    lyrics_ = request.args.get(
        'lyrics'
    )

    if lyrics_ and lyrics_.lower() != 'false':
        lyrics = True

    if not query:
        return jsonify({
            "status": False,
            "error": "Query is required to search albums!"
        })

    try:

        album_id = jiosaavn.get_album_id(
            query
        )

        if not album_id:

            return jsonify({
                "status": False,
                "error": "Invalid album!"
            })

        songs = jiosaavn.get_album(
            album_id,
            lyrics
        )

        return jsonify(
            songs if songs else []
        )

    except Exception:
        return jsonify({
            "status": False,
            "error": "Unable to fetch album details"
        })


# ============================================================
# LYRICS
# ============================================================

@app.route('/lyrics/')
def lyrics():

    query = request.args.get(
        'query'
    )

    if not query:

        return jsonify({
            "status": False,
            "error": (
                "Query containing song link or "
                "id is required to fetch lyrics!"
            )
        })

    try:

        if (
            'http' in query.lower()
            and 'saavn' in query.lower()
        ):

            song_id = jiosaavn.get_song_id(
                query
            )

            if not song_id:

                return jsonify({
                    "status": False,
                    "error": "Could not find song ID!"
                })

            lyrics_text = jiosaavn.get_lyrics(
                song_id
            )

        else:

            lyrics_text = jiosaavn.get_lyrics(
                query
            )

        return jsonify({
            "status": True,
            "lyrics": lyrics_text
        })

    except Exception:
        return jsonify({
            "status": False,
            "error": "Unable to fetch lyrics"
        })


# ============================================================
# UNIVERSAL RESULT ENDPOINT
# ============================================================

@app.route('/result/')
def result():

    lyrics = False

    query, error = _validated_query("Query is required!")
    if error:
        return error

    lyrics_ = request.args.get(
        'lyrics'
    )

    page, error = _validated_positive_int("page", 1, MAX_PAGE)
    if error:
        return error
    limit, error = _validated_positive_int("limit", 20, MAX_LIMIT)
    if error:
        return error

    # --------------------------------------------------------
    # Lyrics
    # --------------------------------------------------------

    if lyrics_ and lyrics_.lower() != 'false':
        lyrics = True

    try:

        # ====================================================
        # NORMAL TEXT SEARCH
        # ====================================================

        if 'saavn' not in query.lower():

            # IMPORTANT:
            #
            # FALSE means:
            # return search results directly.
            #
            # We DO NOT call get_song() for every result.
            #
            results = jiosaavn.search_for_song(
                query,
                lyrics,
                False,
                page=page,
                limit=limit
            )

            return jsonify({"success": True, "results": results or []})


        # ====================================================
        # SONG URL
        # ====================================================

        if '/song/' in query.lower():

            song_id = jiosaavn.get_song_id(
                query
            )

            if not song_id:

                return api_error("Could not find song ID!", 404)

            song = jiosaavn.get_song(
                song_id,
                lyrics
            )

            return jsonify({"success": True, "result": song})


        # ====================================================
        # ALBUM URL
        # ====================================================

        elif '/album/' in query.lower():

            album_id = jiosaavn.get_album_id(
                query
            )

            if not album_id:

                return api_error("Could not find album ID!", 404)

            songs = jiosaavn.get_album(
                album_id,
                lyrics
            )

            return jsonify({"success": True, "results": songs or []})


        # ====================================================
        # PLAYLIST / FEATURED URL
        # ====================================================

        elif (
            '/playlist/' in query.lower()
            or '/featured/' in query.lower()
        ):

            playlist_id = (
                jiosaavn.get_playlist_id(
                    query
                )
            )

            if not playlist_id:

                return api_error("Could not find playlist ID!", 404)

            songs = jiosaavn.get_playlist(
                playlist_id,
                lyrics
            )

            return jsonify({"success": True, "results": songs or []})


        # ====================================================
        # UNSUPPORTED URL
        # ====================================================

        return api_error("Unsupported JioSaavn URL.", 400)


    except Exception:
        return api_error("Unable to fetch JioSaavn results")


# ============================================================
# START SERVER
# ============================================================

if __name__ == '__main__':

    app.run(
        host='0.0.0.0',
        port=int(os.environ.get('PORT', '5100')),
        debug=False,
        use_reloader=False,
        threaded=True
    )
