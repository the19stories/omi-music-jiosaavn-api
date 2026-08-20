from flask import Flask, request, redirect, jsonify
import os
import jiosaavn
from traceback import print_exc
from flask_cors import CORS


app = Flask(__name__)

app.secret_key = os.environ.get(
    "SECRET",
    "thankyoutonystark#weloveyou3000"
)

CORS(app)


def api_error(message, status=502):
    return jsonify({"success": False, "status": False, "error": message}), status


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

    query = request.args.get(
        'query',
        ''
    ).strip()

    lyrics_ = request.args.get(
        'lyrics'
    )

    songdata_ = request.args.get(
        'songdata'
    )

    page = request.args.get(
        'page',
        1,
        type=int
    )

    limit = request.args.get(
        'limit',
        20,
        type=int
    )

    if lyrics_ and lyrics_.lower() != 'false':
        lyrics = True

    if songdata_ and songdata_.lower() != 'true':
        songdata = False

    if not query:
        return api_error("Query is required to search songs!", 400)

    try:

        results = jiosaavn.search_for_song(
            query,
            lyrics,
            songdata,
            page=page,
            limit=limit
        )

        return jsonify({"success": True, "results": results or []})

    except Exception as e:

        print_exc()
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

    except Exception as e:

        print_exc()

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

    except Exception as e:

        print_exc()

        return jsonify({
            "status": False,
            "error": str(e)
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

    except Exception as e:

        print_exc()

        return jsonify({
            "status": False,
            "error": str(e)
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

    except Exception as e:

        print_exc()

        return jsonify({
            "status": False,
            "error": str(e)
        })


# ============================================================
# UNIVERSAL RESULT ENDPOINT
# ============================================================

@app.route('/result/')
def result():

    lyrics = False

    query = request.args.get(
        'query',
        ''
    ).strip()

    lyrics_ = request.args.get(
        'lyrics'
    )

    page = request.args.get(
        'page',
        1,
        type=int
    )

    limit = request.args.get(
        'limit',
        20,
        type=int
    )

    # --------------------------------------------------------
    # Validate page
    # --------------------------------------------------------

    page = max(
        1,
        page
    )

    # --------------------------------------------------------
    # Validate limit
    # --------------------------------------------------------

    limit = max(
        1,
        min(limit, 50)
    )

    # --------------------------------------------------------
    # Lyrics
    # --------------------------------------------------------

    if lyrics_ and lyrics_.lower() != 'false':
        lyrics = True

    # --------------------------------------------------------
    # Query required
    # --------------------------------------------------------

    if not query:

        return jsonify({
            "status": False,
            "error": "Query is required!"
        })


    try:

        # ====================================================
        # NORMAL TEXT SEARCH
        # ====================================================

        if 'saavn' not in query.lower():

            print()
            print("=" * 60)
            print("SEARCH REQUEST")
            print("=" * 60)
            print("Query :", query)
            print("Page  :", page)
            print("Limit :", limit)
            print("=" * 60)

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

            print(
                "Results returned:",
                len(results) if results else 0
            )

            return jsonify({"success": True, "results": results or []})


        # ====================================================
        # SONG URL
        # ====================================================

        if '/song/' in query.lower():

            print(
                "JioSaavn Song URL"
            )

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

            print(
                "JioSaavn Album URL"
            )

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

            print(
                "JioSaavn Playlist URL"
            )

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


    except Exception as e:

        print()
        print(
            "RESULT ENDPOINT ERROR:"
        )

        print_exc()

        return api_error("Unable to fetch JioSaavn results")


# ============================================================
# START SERVER
# ============================================================

if __name__ == '__main__':

    app.run(
        host='0.0.0.0',
        port=int(os.environ.get('PORT', '5100')),
        debug=os.environ.get('FLASK_DEBUG') == '1',
        use_reloader=False,
        threaded=True
    )
