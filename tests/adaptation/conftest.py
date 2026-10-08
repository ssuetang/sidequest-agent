import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.adaptation.schemas import PlaceCandidate, QuestStep, SideQuest  # noqa: E402


def place(pid, name, tags, *, indoor=True, lat=40.73, lng=-73.99, cost=0.0, rating=4.5, open_now=True):
    return PlaceCandidate(pid, name, tags, indoor=indoor, lat=lat, lng=lng,
                          rating=rating, open_now=open_now, est_cost=cost)


@pytest.fixture
def novelist_quest():
    """A 'day as a struggling novelist' quest in Greenwich Village."""
    cafe = place("p_cafe", "Caffe Reggio", ["cafe", "writing", "literary"], lat=40.7302, lng=-73.9999, cost=8)
    gallery = place("p_gallery", "Salmagundi Gallery", ["gallery", "art", "literary"], lat=40.7335, lng=-73.9945, cost=0)
    park = place("p_park", "Washington Square Park", ["park", "people-watching", "inspiration"],
                 indoor=False, lat=40.7308, lng=-73.9973)
    bar = place("p_bar", "White Horse Tavern", ["bar", "literary", "history"], lat=40.7359, lng=-74.0060, cost=15)
    steps = [
        QuestStep("s1", cafe, 45, "Open your notebook at Caffe Reggio.",
                  ["Write the first line of your novel at Caffe Reggio"], ["writing", "cafe"], 3,
                  chapter="Chapter 1: The Blank Page"),
        QuestStep("s2", gallery, 40, "Find your antagonist's face at Salmagundi Gallery.",
                  ["Pick a painting at Salmagundi Gallery and name the character"], ["art", "gallery", "literary"], 2,
                  travel_min_from_prev=9, chapter="Chapter 2: The Muse"),
        QuestStep("s3", park, 30, "Eavesdrop for dialogue in Washington Square Park.",
                  ["Write down three overheard lines"], ["people-watching", "inspiration"], 1,
                  optional=True, travel_min_from_prev=6, chapter="Chapter 3: Overheard"),
        QuestStep("s4", bar, 60, "End where Dylan Thomas drank: White Horse Tavern.",
                  ["Toast your unfinished manuscript"], ["literary", "bar"], 3,
                  travel_min_from_prev=14, chapter="Chapter 4: The Last Round"),
    ]
    return SideQuest("q1", "novelist", steps, total_time_min=204,
                     persona="struggling 1950s novelist", budget=40)


@pytest.fixture
def spare_candidates():
    return [
        place("c_bookstore", "Three Lives & Company", ["bookstore", "literary", "inspiration", "art"],
              lat=40.7339, lng=-74.0021, cost=0, rating=4.8),
        place("c_library", "Jefferson Market Library", ["library", "people-watching", "history", "inspiration"],
              lat=40.7344, lng=-73.9989, cost=0, rating=4.7),
        place("c_museum", "Far Uptown Art Museum", ["art", "gallery", "museum"],
              lat=40.7794, lng=-73.9632, cost=25, rating=4.9),
        place("c_garden", "Liz Christy Garden", ["garden", "inspiration", "people-watching"],
              indoor=False, lat=40.7240, lng=-73.9920, rating=4.6),
        place("c_offtheme", "Sports Bar Arena", ["sports", "bar"], lat=40.7310, lng=-73.9990, cost=20, rating=4.0),
        place("c_closed_gallery", "Closed Studio", ["art", "gallery"], open_now=False),
    ]
