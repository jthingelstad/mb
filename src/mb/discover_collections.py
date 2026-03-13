"""Curated Micro.blog Discover collection registry."""

DISCOVER_COLLECTIONS = [
    {"slug": "books", "label": "Books & Reading", "emoji": ":books: :open_book:", "kind": "topic"},
    {"slug": "music", "label": "Music", "emoji": ":musical_note: :notes:", "kind": "topic"},
    {"slug": "rocket", "label": "Space", "emoji": ":rocket:", "kind": "topic"},
    {"slug": "basketball", "label": "Sports/Basketball", "emoji": ":basketball:", "kind": "topic"},
    {"slug": "football", "label": "Sports/Football", "emoji": ":football:", "kind": "topic"},
    {"slug": "rugby", "label": "Sports/Rugby", "emoji": ":rugby_football:", "kind": "topic"},
    {"slug": "soccer", "label": "Sports/Soccer", "emoji": ":soccer:", "kind": "topic"},
    {"slug": "tennis", "label": "Sports/Tennis", "emoji": ":tennis:", "kind": "topic"},
    {"slug": "baseball", "label": "Sports/Baseball", "emoji": ":baseball:", "kind": "topic"},
    {"slug": "hockey", "label": "Sports/Hockey", "emoji": ":ice_hockey:", "kind": "topic"},
    {"slug": "cricket", "label": "Sports/Cricket", "emoji": ":cricket_bat_and_ball:", "kind": "topic"},
    {"slug": "startrek", "label": "Star Trek", "emoji": ":vulcan_salute:", "kind": "topic"},
    {"slug": "tv", "label": "TV", "emoji": ":tv:", "kind": "topic"},
    {"slug": "videogames", "label": "Video Games", "emoji": ":video_game: :joystick:", "kind": "topic"},
    {"slug": "pizza", "label": "Pizza", "emoji": ":pizza:", "kind": "topic"},
    {"slug": "breakfast", "label": "Breakfast", "emoji": ":fried_egg: :pancakes: :bacon:", "kind": "topic"},
    {"slug": "travel", "label": "Travel", "emoji": ":world_map: :airplane:", "kind": "topic"},
    {"slug": "cats", "label": "Cats", "emoji": ":cat2: :cat:", "kind": "topic"},
    {"slug": "dogs", "label": "Dogs", "emoji": ":dog2: :dog:", "kind": "topic"},
    {"slug": "movies", "label": "Movies", "emoji": ":film_projector: :popcorn: :movie_camera:", "kind": "topic"},
    {"slug": "racing", "label": "Racing", "emoji": ":racing_car: :checkered_flag:", "kind": "topic"},
    {"slug": "guitar", "label": "Guitar", "emoji": ":guitar:", "kind": "topic"},
    {"slug": "knitting", "label": "Knitting & Crochet", "emoji": ":yarn:", "kind": "topic"},
    {"slug": "art", "label": "Art", "emoji": ":art: :paintbrush:", "kind": "topic"},
    {"slug": "camping", "label": "Camping", "emoji": ":camping: :tent:", "kind": "topic"},
    {"slug": "beer", "label": "Beer", "emoji": ":beer: :beers:", "kind": "topic"},
    {"slug": "wine", "label": "Wine", "emoji": ":wine_glass:", "kind": "topic"},
    {"slug": "bread", "label": "Bread", "emoji": ":bread:", "kind": "topic"},
    {"slug": "writing", "label": "Writing", "emoji": ":memo: :pencil2:", "kind": "topic"},
    {"slug": "pens", "label": "Pens & Ink", "emoji": ":fountain_pen:", "kind": "topic"},
    {"slug": "gardening", "label": "Gardening", "emoji": ":seedling:", "kind": "topic"},
    {"slug": "quotes", "label": "Quotes", "emoji": ":speech_balloon:", "kind": "topic"},
    {"slug": "lgbtq", "label": "LGBTQ+", "emoji": ":rainbow_flag: :transgender_flag:", "kind": "topic"},
    {"slug": "coffee", "label": "Coffee", "emoji": ":coffee:", "kind": "topic"},
    {"slug": "running", "label": "Running", "emoji": ":running_man: :running_woman: :man_running:", "kind": "topic"},
    {"slug": "cycling", "label": "Cycling", "emoji": ":bike: :biking_woman: :man_biking:", "kind": "topic"},
    {"slug": "meditation", "label": "Meditation", "emoji": ":person_in_lotus_position:", "kind": "topic"},
    {"slug": "theater", "label": "Theater", "emoji": ":performing_arts:", "kind": "topic"},
    {"slug": "photos", "label": "Photos", "emoji": ":camera:", "kind": "special"},
    {"slug": "podcasts", "label": "Podcasts", "emoji": ":studio_microphone:", "kind": "special"},
    {"slug": "micromonday", "label": "Micro Monday", "emoji": "Micro Monday", "kind": "special"},
    {"slug": "inktober", "label": "Inktober", "emoji": "Inktober", "kind": "special"},
    {"slug": "nanowrimo", "label": "NaNoWriMo", "emoji": "NaNoWriMo", "kind": "special"},
]

_DISCOVER_BY_SLUG = {entry["slug"]: entry for entry in DISCOVER_COLLECTIONS}


def get_discover_collection(slug: str) -> dict | None:
    """Return metadata for a curated discover collection."""
    return _DISCOVER_BY_SLUG.get(slug)


def list_discover_collections() -> list[dict]:
    """Return curated discover collection metadata with canonical URLs."""
    return [
        {
            **entry,
            "url": f"https://micro.blog/discover/{entry['slug']}",
        }
        for entry in DISCOVER_COLLECTIONS
    ]
