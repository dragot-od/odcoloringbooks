import base64
import io
import json
import os
import random
import shutil
import threading
import time
import uuid
from contextlib import ExitStack
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
import requests
from PIL import Image, ImageDraw, ImageFont, ImageOps
from reportlab.lib.pagesizes import letter
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

load_dotenv()

ROOT = Path(__file__).resolve().parent
STATIC_DIR = ROOT / "static"
JOBS_DIR = ROOT / "jobs"
DEMO_PRESETS_DIR = ROOT / "demo_presets"
JOBS_DIR.mkdir(exist_ok=True)

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
IMAGE_MODEL = os.getenv("IMAGE_MODEL", "gpt-image-2").strip() or "gpt-image-2"
SITE_PASSWORD = os.getenv("SITE_PASSWORD", "").strip()
JOB_TTL_HOURS = float(os.getenv("JOB_TTL_HOURS", "6") or 6)

app = FastAPI(title="Personalized Coloring Book Demo")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

jobs: dict[str, dict] = {}
jobs_lock = threading.Lock()

APP_VERSION = "random-helper-below-standard-v9.3"
TEXT_MODEL = os.getenv("TEXT_MODEL", "gpt-4.1-mini").strip() or "gpt-4.1-mini"

RNG = random.SystemRandom()

# Hidden creative variables used to make two books with the same customer inputs
# take materially different creative paths before any image generation begins.
STORY_STRUCTURES = [
    "guided expedition through a changing world",
    "discovery trail where each scene reveals a new surprise",
    "light quest built around reaching a memorable destination",
    "day-in-the-life adventure with escalating unusual moments",
    "friendly mystery solved through visual clues and discoveries",
    "skill-building journey where each stop introduces a different activity",
    "festival or special-event journey moving through distinct locations",
    "rescue-and-helping adventure focused on teamwork",
    "map-led exploration with a different destination on each stop",
    "collection quest where the character finds a series of themed objects",
    "before-during-after adventure with a clear visual progression",
    "unexpected detour story where each new place changes the plan",
]

OPENING_SITUATIONS = [
    "arriving at the edge of the themed world and deciding where to go first",
    "discovering an unusual clue or object that starts the adventure",
    "being welcomed by a friendly guide or helper",
    "stepping through an entrance, gate, trail, portal, doorway, or other clear threshold",
    "beginning with a hands-on activity that leads naturally into exploration",
    "starting during a cheerful event or busy moment already in progress",
    "finding a map, sign, invitation, tool, or keepsake that suggests the first destination",
    "noticing something surprising in the distance and setting off to investigate",
    "meeting a friendly creature or supporting character who needs help",
    "beginning in a calm familiar place before the themed adventure expands outward",
]

ACTIVITY_EMPHASES = [
    "exploration and discovery",
    "helping and teamwork",
    "hands-on making and building",
    "games, play, and friendly challenges",
    "observation, learning, and collecting clues",
    "travel between distinct locations",
    "caregiving and friendly interaction",
    "problem solving and practical tasks",
    "performance, celebration, and playful participation",
    "nature, animals, and outdoor discovery",
    "food, crafts, and everyday activities inside the themed world",
    "movement, sports, and energetic action",
]

RECURRING_MOTIFS = [
    "a small map that appears naturally in several scenes",
    "a backpack or satchel used differently across the adventure",
    "a friendly recurring animal or helper appearing occasionally",
    "a simple collectible token or keepsake discovered along the way",
    "a trail of signs, markers, or visual clues linking locations",
    "a favorite tool or activity prop that changes purpose from scene to scene",
    "a playful visual shape or symbol repeated subtly in the environment",
    "a recurring snack, gift, or object exchanged with supporting characters",
    "a notebook or sketchbook used during discoveries",
    "a small flag, badge, ribbon, or sticker marking accomplishments",
    "a recurring vehicle or mode of travel",
    "a themed hat, scarf, or accessory used as a visual thread",
]

PACING_PATTERNS = [
    "quiet discovery → active play → problem solving → celebration",
    "active opening → calmer exploration → bigger challenge → warm ending",
    "curious opening → several increasingly adventurous stops → peaceful finale",
    "small-scale activity → wider exploration → close interaction → energetic finish",
    "alternating calm and energetic scenes throughout the book",
    "steady exploration with one surprising high-energy scene near the middle",
    "progressively larger environments followed by an intimate final moment",
    "varied episodic pacing with no two adjacent scenes having the same energy",
]

SUPPORTING_DYNAMICS = [
    "friendly guides who appear only when useful to the scene",
    "different supporting creatures or helpers at different stops",
    "one recurring helper plus several one-scene supporting characters",
    "mostly independent exploration with occasional friendly encounters",
    "teamwork moments balanced with solo discovery",
    "supporting characters who introduce activities rather than dominate the scene",
    "a rotating cast of helpers tied to each specific location",
    "environmental storytelling with only a few supporting characters",
]

ENDING_TYPES = [
    "a proud accomplishment at a scenic destination",
    "a cheerful group celebration tied to the adventure",
    "a calm sunset or end-of-day reflection with a treasured keepsake",
    "a final discovery that visually echoes the opening scene",
    "a playful victory or completed challenge",
    "a warm goodbye to new friends before heading home",
    "a final panoramic view showing how far the adventure traveled",
    "a quiet satisfied moment after completing a meaningful task",
    "a celebratory photo-like moment without becoming a stiff posed portrait",
    "an open-ended final scene suggesting another adventure could follow",
]

PAGE_ACTION_ARCHETYPES = [
    "entering or arriving", "meeting or greeting", "searching or discovering", "building or making",
    "feeding or caring", "riding or traveling", "playing a game", "solving a practical problem",
    "learning or observing", "helping a supporting character", "crossing an obstacle", "using a map or clue",
    "sharing food or a craft", "performing or celebrating", "exploring an indoor location", "exploring an outdoor location",
    "repairing or organizing", "collecting or sorting", "practicing a skill", "resting or reflecting",
    "following a trail", "working as a team", "reacting to a surprise", "completing a final challenge",
]

PAGE_COMPOSITION_CUES = [
    "wide establishing view", "medium three-quarter interaction", "close character-and-prop moment", "side-view action",
    "slightly overhead activity view", "low-angle adventurous view", "foreground object framing the action", "doorway or arch framing the scene",
    "path or road leading into the scene", "diagonal movement across the page", "character offset with environment emphasized", "balanced two-subject composition",
    "near-far depth with a landmark behind", "seated or kneeling interaction", "walking-toward-viewer composition", "walking-away-into-the-world composition",
    "object-discovery close view", "large environmental feature with smaller character", "character-centered scene with sparse setting", "layered landscape composition",
    "activity table or workbench composition", "bridge, fence, or railing defining depth", "curving trail or shoreline composition", "celebratory final-page composition",
]

PAGE_ENERGY_CUES = [
    "calm and curious", "playful and light", "active but readable", "focused and purposeful",
    "warm and social", "surprising and delighted", "adventurous and energetic", "quietly proud",
]

PRESCHOOL_ACTION_ARCHETYPES = [
    "arriving or waving hello", "petting or gently touching", "feeding or caring", "walking or following",
    "looking at or discovering", "holding or carrying one simple prop", "playing one simple game", "helping with one simple task",
    "sitting or kneeling together", "pointing at something interesting", "sharing a snack or object", "celebrating one small accomplishment",
]

PRESCHOOL_COMPOSITION_CUES = [
    "simple centered interaction", "simple side-view action", "two large subjects with open space", "one large foreground subject and one simple background landmark",
    "kneeling interaction with a sparse setting", "standing interaction with a sparse setting", "simple walking scene", "simple seated scene",
    "large character shapes with one clear prop", "simple fence or path defining the setting", "simple indoor scene with two or three large objects", "simple outdoor scene with two or three large objects",
]


RANDOM_IDEA_NAMES = [
    "Willy", "Mickey", "David", "Luna", "Oliver", "Hazel", "Hendrix", "Milo", "Zoe", "Eli",
    "Nora", "Finn", "Rosie", "Theo", "Lucy", "Leo", "Ruby", "Jasper", "Ellie", "Max",
]

RANDOM_IDEA_SUBJECTS = [
    "robots", "dinosaurs", "pirates", "space", "dragons", "mermaids", "jungle animals", "construction trucks",
    "fairies", "farm animals", "race cars", "underwater adventure", "castle", "camping", "superheroes",
    "candy land", "petting zoo", "monster town", "treasure hunt", "friendly ghosts", "wild west",
    "ocean rescue", "magic school", "rocket ships", "detectives", "rainforest", "snow adventure",
]

SUBJECT_BUNDLES = {
    "robot": {
        "world": "a bright robot workshop city full of gadget stations and friendly helper bots",
        "locations": ["a welcome gate", "a robot workshop", "a parts factory", "a charging station", "a rooftop garden", "a race track", "a repair bay", "a celebration plaza"],
        "props": ["gears", "tools", "control panels", "tiny helper bots", "blueprints"],
        "activities": ["meeting a robot guide", "building a small gadget", "fixing a simple machine", "racing a mini bot", "delivering parts", "celebrating with robot friends"],
        "helpers": "friendly robots and silly mini helper bots",
        "mood": "playful, inventive, and adventurous",
    },
    "robots": {
        "world": "a bright robot workshop city full of gadget stations and friendly helper bots",
        "locations": ["a welcome gate", "a robot workshop", "a parts factory", "a charging station", "a rooftop garden", "a race track", "a repair bay", "a celebration plaza"],
        "props": ["gears", "tools", "control panels", "tiny helper bots", "blueprints"],
        "activities": ["meeting a robot guide", "building a small gadget", "fixing a simple machine", "racing a mini bot", "delivering parts", "celebrating with robot friends"],
        "helpers": "friendly robots and silly mini helper bots",
        "mood": "playful, inventive, and adventurous",
    },
    "dinosaur": {
        "world": "a colorful dinosaur valley with jungles, gentle volcanoes, and friendly dinosaurs",
        "locations": ["a jungle path", "a fern meadow", "a dinosaur nest", "a wooden bridge", "a waterfall cove", "a volcano overlook", "a fossil dig site", "a dino party clearing"],
        "props": ["binoculars", "a field journal", "fossils", "large leaves", "backpacks"],
        "activities": ["meeting a baby dinosaur", "following big footprints", "finding dinosaur eggs", "feeding a gentle dinosaur", "crossing a bridge", "celebrating with dinosaur friends"],
        "helpers": "friendly dinosaurs of different sizes",
        "mood": "exciting, warm, and adventurous",
    },
    "dinosaurs": {
        "world": "a colorful dinosaur valley with jungles, gentle volcanoes, and friendly dinosaurs",
        "locations": ["a jungle path", "a fern meadow", "a dinosaur nest", "a wooden bridge", "a waterfall cove", "a volcano overlook", "a fossil dig site", "a dino party clearing"],
        "props": ["binoculars", "a field journal", "fossils", "large leaves", "backpacks"],
        "activities": ["meeting a baby dinosaur", "following big footprints", "finding dinosaur eggs", "feeding a gentle dinosaur", "crossing a bridge", "celebrating with dinosaur friends"],
        "helpers": "friendly dinosaurs of different sizes",
        "mood": "exciting, warm, and adventurous",
    },
    "space": {
        "world": "a cheerful outer-space adventure with planets, rockets, and friendly aliens",
        "locations": ["a rocket launch pad", "the moon", "a ringed planet lookout", "a floating space station", "a crystal asteroid", "an alien garden", "a rover trail", "a star celebration scene"],
        "props": ["helmets", "star maps", "moon rocks", "space backpacks", "control panels"],
        "activities": ["waving from a rocket", "driving a rover", "discovering moon rocks", "meeting a friendly alien", "floating in zero gravity", "celebrating among the stars"],
        "helpers": "friendly aliens and tiny robot helpers",
        "mood": "wonder-filled, playful, and adventurous",
    },
    "pirates": {
        "world": "a fun pirate world with sunny islands, treasure maps, and friendly pirate ships",
        "locations": ["a pirate dock", "a ship deck", "a treasure cave", "a palm-tree island", "a rope bridge", "a hidden lagoon", "a lookout tower", "a treasure party"],
        "props": ["maps", "keys", "treasure chests", "spyglasses", "flags"],
        "activities": ["reading a treasure map", "steering a ship", "digging for treasure", "crossing a rope bridge", "spotting clues", "celebrating with a treasure chest"],
        "helpers": "friendly pirate friends and silly parrots",
        "mood": "playful, bold, and adventurous",
    },
    "bigfoot": {
        "world": "a whimsical forest full of giant trees, mushrooms, creeks, and a friendly Bigfoot",
        "locations": ["a woodland trail", "a creek crossing", "a waterfall", "a log bridge", "a cozy cave", "a fern clearing", "a giant tree grove", "a sunset overlook"],
        "props": ["lanterns", "backpacks", "maps", "boots", "forest snacks"],
        "activities": ["meeting Bigfoot", "crossing a stream", "following a trail map", "exploring a cave", "sharing a snack", "celebrating on a scenic overlook"],
        "helpers": "a friendly Bigfoot and small forest animals",
        "mood": "warm, whimsical, and adventurous",
    },
    "superheroes": {
        "world": "a lively superhero city with rooftops, training areas, and cheerful city scenes",
        "locations": ["a city street", "a rooftop", "a practice gym", "a park rescue scene", "a bridge", "a control room", "a skyline lookout", "a hero celebration"],
        "props": ["capes", "masks", "gadgets", "hero emblems", "city maps"],
        "activities": ["striking a hero pose", "training", "helping people", "stopping a silly problem", "zooming across the city", "celebrating like a hero"],
        "helpers": "friendly sidekicks and helpful city characters",
        "mood": "energetic, brave, and upbeat",
    },
    "petting zoo": {
        "world": "a gentle petting-zoo adventure with small farm paths and friendly animals",
        "locations": ["the zoo gate", "a duck pond", "a goat pen", "a sheep yard", "a bunny corner", "a little barn", "a feeding station", "a picnic spot"],
        "props": ["feed cups", "fences", "hay bales", "watering cans", "small signs"],
        "activities": ["feeding ducks", "petting a goat", "watching a sheep", "meeting a bunny", "helping at the barn", "waving goodbye to the animals"],
        "helpers": "friendly farm animals and gentle zookeepers",
        "mood": "sweet, calm, and cheerful",
    },
}

GENERIC_WORLD_OPTIONS = [
    "a bright themed world full of fun places to explore",
    "a playful adventure setting with several distinct locations",
    "a cheerful world built around the theme",
    "a whimsical place where every stop feels different",
]
GENERIC_LOCATION_POOL = [
    "a welcome entrance", "a winding path", "a busy central area", "a lookout point", "a hidden nook",
    "a bridge or crossing", "a workshop or activity area", "a scenic final destination",
]
GENERIC_PROP_POOL = ["maps", "backpacks", "small tools", "snacks", "signs", "decorations", "collectibles", "lanterns"]
GENERIC_ACTIVITY_POOL = [
    "meeting a friendly helper", "discovering something surprising", "following clues", "trying a fun activity",
    "helping with a simple task", "finding a special object", "exploring a new area", "celebrating at the end",
]
GENERIC_HELPER_POOL = [
    "friendly helpers that fit the theme", "silly side characters", "helpful creatures", "fun background friends",
]
GENERIC_MOOD_POOL = [
    "playful and adventurous", "warm and imaginative", "fun and energetic", "bright and cheerful",
]

RANDOM_IDEA_TONES = {
    "funny": "funny, silly, and lighthearted, with harmless visual jokes and playful situations",
    "adventurous": "adventurous, energetic, and discovery-focused, with a sense of movement and exploration",
    "cute": "cute, sweet, and gentle, with friendly expressions and warm interactions",
    "educational": "curious and educational, mixing fun with age-appropriate discovery, observation, and learning moments",
    "magical": "magical, whimsical, and imaginative, with wonder-filled locations and delightful surprises",
    "mysterious": "mysterious but kid-friendly, with clues, discoveries, and gentle suspense rather than anything scary",
    "calm": "calm, cozy, and comforting, with relaxed activities and peaceful locations",
    "action": "action-packed and energetic, with lots of movement, challenges, and exciting but family-friendly activity",
}
RANDOM_IDEA_TONE_LABELS = {
    "funny": "Funny",
    "adventurous": "Adventurous",
    "cute": "Cute & Gentle",
    "educational": "Educational",
    "magical": "Magical",
    "mysterious": "Mysterious",
    "calm": "Calm & Cozy",
    "action": "Action-Packed",
}

TITLE_TEMPLATES = [
    "{name} and the {subject_title} Adventure",
    "{name} Explores the {subject_title} World",
    "{name} Visits the {subject_title} Kingdom",
    "{name}'s {subject_title} Journey",
]


def subject_key(subject: str) -> str:
    return " ".join((subject or "").strip().lower().replace("_", " ").split())


def age_bucket(age: int) -> str:
    if age <= 4:
        return "preschool"
    if age <= 7:
        return "early"
    if age <= 10:
        return "middle"
    if age <= 13:
        return "upper"
    return "teen"


def random_age_value() -> int:
    weighted = [3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17]
    weights = [1, 2, 3, 4, 5, 5, 5, 4, 4, 3, 3, 2, 2, 1, 1]
    return RNG.choices(weighted, weights=weights, k=1)[0]


def pick_subject_bundle(subject: str) -> tuple[str, dict]:
    raw = (subject or "").strip()
    key = subject_key(raw)
    if key in SUBJECT_BUNDLES:
        return raw or key, SUBJECT_BUNDLES[key]
    singular = key[:-1] if key.endswith("s") else key
    if singular in SUBJECT_BUNDLES:
        return raw or singular, SUBJECT_BUNDLES[singular]
    generated_subject = raw or RNG.choice(RANDOM_IDEA_SUBJECTS)
    locations = RNG.sample(GENERIC_LOCATION_POOL, k=min(6, len(GENERIC_LOCATION_POOL)))
    bundle = {
        "world": f"a {generated_subject} themed world with several fun places to explore" if generated_subject else RNG.choice(GENERIC_WORLD_OPTIONS),
        "locations": locations,
        "props": RNG.sample(GENERIC_PROP_POOL, k=4),
        "activities": RNG.sample(GENERIC_ACTIVITY_POOL, k=5),
        "helpers": RNG.choice(GENERIC_HELPER_POOL),
        "mood": RNG.choice(GENERIC_MOOD_POOL),
    }
    return generated_subject, bundle


def humanize_subject(subject: str) -> str:
    s = (subject or "").strip()
    if not s:
        return "Adventure"
    return " ".join(word.capitalize() for word in s.replace("_", " ").split())


def random_book_title(name: str, subject: str) -> str:
    subject_title = humanize_subject(subject)
    return RNG.choice(TITLE_TEMPLATES).format(name=name, subject_title=subject_title)


def choose_random_idea_tone(tone: str | None = None) -> tuple[str, str]:
    key = (tone or "").strip().lower()
    aliases = {
        "surprise": "", "random": "", "auto": "",
        "cute & gentle": "cute", "cute and gentle": "cute",
        "calm & cozy": "calm", "calm and cozy": "calm",
        "action-packed": "action", "action packed": "action",
    }
    key = aliases.get(key, key)
    if key not in RANDOM_IDEA_TONES:
        key = RNG.choice(list(RANDOM_IDEA_TONES.keys()))
    return key, RANDOM_IDEA_TONES[key]


def build_random_description(name: str, age: int, subject: str, bundle: dict, tone_guidance: str) -> str:
    bucket = age_bucket(age)
    locations = list(bundle.get("locations", []))[:6]
    props = list(bundle.get("props", []))[:4]
    activities = list(bundle.get("activities", []))[:5]
    while len(locations) < 6:
        locations.append(RNG.choice(GENERIC_LOCATION_POOL))
    while len(props) < 4:
        props.append(RNG.choice(GENERIC_PROP_POOL))
    while len(activities) < 5:
        activities.append(RNG.choice(GENERIC_ACTIVITY_POOL))
    helpers = bundle.get("helpers", "friendly side characters")
    bundle_mood = bundle.get("mood", "playful and adventurous")
    mood = tone_guidance or bundle_mood
    world = bundle.get("world", f"a {subject or 'fun'} themed adventure world")
    subject_phrase = subject or "adventure"

    if bucket == "preschool":
        return (
            f"Create a very simple coloring-book adventure for a {age}-year-old about {name} exploring {world}. "
            f"Use large, easy-to-recognize scenes such as {locations[0]}, {locations[1]}, {locations[2]}, and {locations[3]}. "
            f"Include friendly {helpers}, simple props like {props[0]} and {props[1]}, and easy activities like {activities[0]}, {activities[1]}, {activities[2]}, and {activities[3]}. "
            f"Use a {mood} tone throughout, with very simple environments and clear visual variety."
        )

    if bucket == "early":
        return (
            f"Create a playful {subject_phrase} adventure for {name}. Set it in {world}. "
            f"Show different locations such as {locations[0]}, {locations[1]}, {locations[2]}, {locations[3]}, and {locations[4]}. "
            f"Include {helpers}, props like {props[0]}, {props[1]}, and {props[2]}, and activities such as {activities[0]}, {activities[1]}, {activities[2]}, {activities[3]}, and {activities[4]}. "
            f"Keep the tone {mood}, with a clear beginning, middle, and happy ending."
        )

    if bucket in {"middle", "upper"}:
        return (
            f"Create a detailed, kid-friendly {subject_phrase} adventure starring {name}. Set the story in {world}. "
            f"Spread the pages across varied places such as {locations[0]}, {locations[1]}, {locations[2]}, {locations[3]}, {locations[4]}, and {locations[5]}. "
            f"Include {helpers}, useful props like {props[0]}, {props[1]}, {props[2]}, and {props[3]}, and show activities like {activities[0]}, {activities[1]}, {activities[2]}, {activities[3]}, and {activities[4]}. "
            f"Keep the tone {mood} and make the pages visually varied from one another."
        )

    return (
        f"Create a more advanced coloring-book adventure for {name} built around the theme of {subject_phrase}. "
        f"Set it in {world} and move through distinct scenes such as {locations[0]}, {locations[1]}, {locations[2]}, {locations[3]}, {locations[4]}, and {locations[5]}. "
        f"Include {helpers}, props like {props[0]}, {props[1]}, {props[2]}, and {props[3]}, and activities such as {activities[0]}, {activities[1]}, {activities[2]}, {activities[3]}, and {activities[4]}. "
        f"Keep the tone {mood}, while making the pages distinct and story-like."
    )


def generate_random_book_idea(name: str | None = None, age: int | None = None, subject: str | None = None, tone: str | None = None) -> dict:
    chosen_name = (name or "").strip() or RNG.choice(RANDOM_IDEA_NAMES)
    chosen_age = age if isinstance(age, int) and 3 <= age <= 17 else random_age_value()
    chosen_subject, bundle = pick_subject_bundle(subject or "")
    tone_key, tone_guidance = choose_random_idea_tone(tone)
    title = random_book_title(chosen_name, chosen_subject)
    description = build_random_description(chosen_name, chosen_age, chosen_subject, bundle, tone_guidance)
    return {
        "name": chosen_name,
        "age": chosen_age,
        "subject": chosen_subject,
        "tone": tone_key,
        "tone_label": RANDOM_IDEA_TONE_LABELS[tone_key],
        "title": title,
        "description": description,
    }


def generate_book_dna(age: int, page_count: int = 8) -> dict:
    """Create a high-entropy hidden creative fingerprint for one book generation."""
    def sample_cycle(pool: list[str], count: int) -> list[str]:
        values = list(pool)
        RNG.shuffle(values)
        while len(values) < count:
            extra = list(pool)
            RNG.shuffle(extra)
            values.extend(extra)
        return values[:count]

    action_pool = PRESCHOOL_ACTION_ARCHETYPES if age <= 4 else PAGE_ACTION_ARCHETYPES
    composition_pool = PRESCHOOL_COMPOSITION_CUES if age <= 4 else PAGE_COMPOSITION_CUES
    actions = sample_cycle(action_pool, page_count)
    compositions = sample_cycle(composition_pool, page_count)
    energies = sample_cycle(PAGE_ENERGY_CUES, page_count)
    recipes = [
        {
            "page": i + 1,
            "action": actions[i],
            "composition": compositions[i],
            "energy": energies[i],
        }
        for i in range(page_count)
    ]
    return {
        "id": uuid.uuid4().hex[:10],
        "story_structure": RNG.choice(STORY_STRUCTURES),
        "opening_situation": RNG.choice(OPENING_SITUATIONS),
        "activity_emphasis": RNG.choice(ACTIVITY_EMPHASES),
        "recurring_motif": RNG.choice(RECURRING_MOTIFS),
        "pacing_pattern": RNG.choice(PACING_PATTERNS),
        "supporting_dynamic": RNG.choice(SUPPORTING_DYNAMICS),
        "ending_type": RNG.choice(ENDING_TYPES),
        "mood": RNG.choice(MOODS),
        "cover_composition": RNG.choice(COVER_COMPOSITIONS),
        "page_recipes": recipes,
        "target_age": age,
    }


def book_dna_text(dna: dict, include_recipes: bool = True) -> str:
    lines = [
        f"Creative fingerprint ID: {dna['id']}",
        f"Story structure: {dna['story_structure']}",
        f"Opening situation: {dna['opening_situation']}",
        f"Activity emphasis: {dna['activity_emphasis']}",
        f"Recurring visual motif: {dna['recurring_motif']}",
        f"Pacing pattern: {dna['pacing_pattern']}",
        f"Supporting-character dynamic: {dna['supporting_dynamic']}",
        f"Ending type: {dna['ending_type']}",
        f"Overall mood: {dna['mood']}",
        f"Cover composition: {dna['cover_composition']}",
    ]
    if include_recipes:
        lines.append("Page-by-page creative recipes:")
        for recipe in dna["page_recipes"]:
            lines.append(
                f"- Page {recipe['page']}: action={recipe['action']}; composition={recipe['composition']}; energy={recipe['energy']}"
            )
    return "\n".join(lines)

COPYRIGHT_SAFETY = (
    "Use only original, generic imagery. Do not include or closely imitate copyrighted characters, "
    "recognizable franchise designs, team logos, branded costumes, company logos, trademarked mascots, "
    "or other protected fictional designs."
)

DEMO_PRESETS = {
    "dinosaurs": {
        "label": "Dinosaurs",
        "title": "Hendrix and the Dinosaur Kingdom",
        "name": "Hendrix",
        "age": 6,
        "description": "Hendrix enters a magical dinosaur kingdom where he meets many different dinosaurs. Some appear in natural prehistoric environments, while others become friendly characters interacting with Hendrix in everyday settings like a kitchen, classroom, library, greenhouse, workshop, music room, playground, boat, soccer field, and post office. Keep it playful, adventurous, educational, and age-appropriate.",
        "interior_pages": 20,
        "pdf_pages": 24,
    },
    "superhero": {
        "label": "Superhero",
        "title": "Adam Jr Saves the Day",
        "name": "Adam Jr",
        "age": 12,
        "description": "Adam Jr becomes a young superhero and races across the city with a masked partner, stopping robots and quirky villains in places like subway stations, rooftops, markets, bridges, museums, parks, waterfronts, and other city locations. Keep it energetic, adventurous, heroic, and comic-book inspired while using original generic characters and designs.",
        "interior_pages": 20,
        "pdf_pages": 24,
    },
    "pyramids": {
        "label": "Pyramids",
        "title": "Willy Explores the Pyramids",
        "name": "Willy",
        "age": 8,
        "description": "Willy explores ancient Egypt on an adventurous trip through the pyramids and temples. Show desert landscapes, pyramid interiors, hieroglyphs, torch-lit passages, treasure, camels, the Sphinx, ancient ruins, scrolls, tombs, the Nile, and other Egyptian landmarks and discoveries. Keep it adventurous, educational, and family-friendly.",
        "interior_pages": 20,
        "pdf_pages": 24,
    },
    "petting_zoo": {
        "label": "Petting Zoo",
        "title": "Erik at the Petting Zoo",
        "name": "Erik",
        "age": 3,
        "description": "Erik visits a cheerful petting zoo and meets friendly animals in very simple preschool scenes. Show him feeding a goat, petting a sheep, brushing a rabbit, feeding a duck, greeting an alpaca, giving a pig a snack, feeding a horse, and meeting a colorful parrot. Use extra-simple shapes, thick outlines, large open coloring areas, minimal background detail, and a warm friendly mood.",
        "interior_pages": 8,
        "pdf_pages": 12,
    },
}


SCENE_DIRECTIONS = [
    "an establishing scene that clearly shows a distinctive part of the described setting, with the character actively entering, exploring, or reacting to it",
    "a hands-on activity in a different specific area or sub-setting from the description, using meaningful environmental props and architecture",
    "an energetic action scene in another visually distinct location, with the surroundings occupying a substantial part of the composition",
    "a curious discovery scene centered on an interesting room, landscape feature, structure, or environmental detail from the description",
    "a skill-practice or problem-solving scene in a new part of the setting, with multiple recognizable background objects that establish where the action is happening",
    "a playful or surprising moment in another distinct environment, using foreground, middle-ground, and background details rather than an empty backdrop",
    "a teamwork or accomplishment scene that uses the setting itself as part of the action and includes several location-specific visual details",
    "a final adventurous scene in a memorable area of the described world, with a strong full-page environmental composition and a proud or delighted expression",
]

COVER_COMPOSITIONS = [
    "Use a lively three-quarter composition with the characters in the foreground and the themed world opening behind them. Keep the upper scene visually calm enough for decorative title lettering directly over the artwork; no title panel or banner.",
    "Use a dynamic low-angle storybook composition with the characters caught in an active moment rather than posing. Keep the upper scene visually calm enough for decorative title lettering directly over the artwork; no title panel or banner.",
    "Use a warm cinematic wide composition with foreground props framing the characters and a clear themed landmark behind them. Keep the upper scene visually calm enough for decorative title lettering directly over the artwork; no title panel or banner.",
    "Use an inviting close-to-medium composition centered on the characters discovering something together, with layered scenery creating depth. Keep the upper scene visually calm enough for decorative title lettering directly over the artwork; no title panel or banner.",
    "Use an asymmetrical adventure-poster composition with the characters offset from center and a strong environmental feature balancing the scene. Keep the upper scene visually calm enough for decorative title lettering directly over the artwork; no title panel or banner.",
]

MOODS = [
    "warm, whimsical, energetic, and friendly",
    "playful, adventurous, curious, and storybook-like",
    "bright, charming, expressive, and full of discovery",
    "lighthearted, imaginative, active, and inviting",
]

VIEWPOINTS = [
    "mix eye-level, low-angle, side-profile, three-quarter, and slightly overhead viewpoints",
    "avoid repeated straight-on portraits; use varied camera distances and angles",
    "mix close, medium, and wider environmental compositions throughout the book",
]


def age_guidance(age: int) -> str:
    if age <= 4:
        return (
            "Target age is 3–4. EXTREME SIMPLICITY is required. Use very thick bold outlines, huge open coloring areas, simple rounded shapes, and minimal overlap. "
            "Keep each page focused on ONE clear action. Use only a few large background objects needed to identify the setting. Avoid dense scenery, texture strokes, repeated leaves, many rocks, grass blades, water ripples, bark grain, fur hatching, tiny clothing details, or other small decorative marks. "
            "A preschooler should be able to color most spaces with a crayon without needing fine motor precision. Age simplicity overrides requests for rich environmental detail."
        )
    if age <= 6:
        return (
            "Target age is 5–6. Keep the artwork very simple: thick bold outlines, large coloring spaces, simple shapes, limited overlap, and uncluttered scenes. Show the setting with a small number of large recognizable elements, not dense texture or many tiny props."
        )
    if age <= 9:
        return (
            "Target age is 7–9. Use simple-to-moderate detail: bold clean outlines, large-to-medium coloring areas, clear action, recognizable settings, and a modest number of props. Avoid excessive texture and tiny repeated details."
        )
    if age <= 12:
        return (
            "Target age is 10–12. Use moderate detail: clean line art, richer settings, more props and environmental elements, and some smaller coloring regions, while keeping the composition readable and enjoyable to color."
        )
    return (
        "Target age is 13+. Use more sophisticated coloring-book line art with richer environments, more texture and props, more complex scenery, and smaller detail areas while maintaining clear, printable outlines."
    )


def environment_guidance(age: int) -> str:
    if age <= 4:
        return (
            "PRESCHOOL ENVIRONMENT RULE: The setting must be recognizable but SPARSE. Use about 2–4 large environmental elements total beyond the main character(s), such as one big tree, one log, a simple stream edge, and a distant hill. "
            "Do not fill every empty area. Large blank white spaces are desirable. Do not use foreground/middle-ground/background density as a goal. Remove decorative clutter and repeated texture marks."
        )
    if age <= 6:
        return (
            "YOUNG-CHILD ENVIRONMENT RULE: Clearly show the setting using a few large, simple environmental elements. Keep backgrounds uncluttered and leave generous white space. Avoid dense foliage, many small props, or texture-heavy scenery."
        )
    if age <= 9:
        return (
            "CHILD ENVIRONMENT RULE: Show a clear setting with several recognizable elements and moderate background detail, but keep the scene easy to read and color."
        )
    return (
        "ENVIRONMENT RULE: Show a complete, recognizable setting using location-specific architecture, scenery, props, and layered environmental details appropriate to the target age."
    )


def age_label(age: int) -> str:
    if age <= 4:
        return "ages 3–4"
    if age <= 6:
        return "ages 5–6"
    if age <= 9:
        return "ages 7–9"
    if age <= 12:
        return "ages 10–12"
    return "ages 13+"


def _unauthorized() -> Response:
    return Response(status_code=401, headers={"WWW-Authenticate": 'Basic realm="Coloring Book Demo"'})


@app.middleware("http")
async def basic_auth(request: Request, call_next):
    if not SITE_PASSWORD or request.url.path == "/health":
        return await call_next(request)
    auth = request.headers.get("authorization", "")
    if not auth.startswith("Basic "):
        return _unauthorized()
    try:
        raw = base64.b64decode(auth.split(" ", 1)[1]).decode("utf-8")
        username, password = raw.split(":", 1)
    except Exception:
        return _unauthorized()
    if username != "demo" or password != SITE_PASSWORD:
        return _unauthorized()
    return await call_next(request)


def set_job(job_id: str, **changes):
    with jobs_lock:
        if job_id in jobs:
            jobs[job_id].update(changes)


def get_job(job_id: str) -> dict:
    with jobs_lock:
        job = jobs.get(job_id)
        if not job:
            raise HTTPException(404, "Job not found or expired.")
        return dict(job)


def cleanup_old_jobs():
    cutoff = time.time() - JOB_TTL_HOURS * 3600
    for p in JOBS_DIR.iterdir():
        try:
            if p.is_dir() and p.stat().st_mtime < cutoff:
                shutil.rmtree(p, ignore_errors=True)
        except FileNotFoundError:
            pass
    with jobs_lock:
        stale = [k for k, v in jobs.items() if v.get("created", 0) < cutoff]
        for k in stale:
            jobs.pop(k, None)


def safe_slug(text: str) -> str:
    out = "".join(ch if ch.isalnum() else "_" for ch in text.strip())
    out = "_".join(filter(None, out.split("_")))
    return (out[:70] or "coloring_book")


def read_and_normalize_upload(data: bytes) -> Image.Image:
    if len(data) > 15 * 1024 * 1024:
        raise ValueError("Each photo must be 15 MB or smaller.")
    try:
        im = Image.open(io.BytesIO(data))
        im.verify()
        im = Image.open(io.BytesIO(data))
        im = ImageOps.exif_transpose(im).convert("RGB")
    except Exception as exc:
        raise ValueError("One of the uploaded files is not a readable image.") from exc
    if min(im.size) < 200:
        raise ValueError("Please use photos at least 200 pixels on each side.")
    im.thumbnail((1800, 1800), Image.Resampling.LANCZOS)
    return im


def save_reference(im: Image.Image, path: Path):
    im.save(path, "JPEG", quality=92, optimize=True)


def font(size: int, bold: bool = False):
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
    ]
    for p in candidates:
        if Path(p).exists():
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def wrap_text(draw: ImageDraw.ImageDraw, text: str, fnt, max_width: int) -> list[str]:
    words = text.split()
    lines, current = [], ""
    for word in words:
        test = f"{current} {word}".strip()
        if draw.textbbox((0, 0), test, font=fnt)[2] <= max_width or not current:
            current = test
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def build_pdf(job_dir: Path, title: str) -> Path:
    """Automatic demo output: 12 pages = cover, blank, 8 coloring pages, 2 blanks."""
    output = job_dir / f"{safe_slug(title)}_print_ready.pdf"
    c = canvas.Canvas(str(output), pagesize=letter)
    pw, ph = letter  # exactly 612 x 792 points

    ordered: list[Optional[Path]] = [job_dir / "cover.png", None]
    ordered += [job_dir / f"page_{i}.png" for i in range(1, 9)]
    ordered += [None, None]

    for page_no, path in enumerate(ordered, start=1):
        if path is not None:
            with Image.open(path) as im:
                iw, ih = im.size
            margin = 0 if page_no == 1 else 18
            scale = min((pw - 2 * margin) / iw, (ph - 2 * margin) / ih)
            w, h = iw * scale, ih * scale
            x, y = (pw - w) / 2, (ph - h) / 2
            c.drawImage(ImageReader(str(path)), x, y, width=w, height=h, preserveAspectRatio=True, mask="auto")
        c.showPage()
    c.save()
    return output


def page_assignments(names: list[str]) -> list[dict]:
    if len(names) == 1:
        return [{"kind": "solo", "indices": [0]} for _ in range(8)]
    # Four solo slots and four everyone-together slots, interleaved.
    solo = [i % len(names) for i in range(4)]
    out = []
    for i in range(4):
        out.append({"kind": "solo", "indices": [solo[i]]})
        out.append({"kind": "group", "indices": list(range(len(names)))})
    return out


def identity_text(names: list[str], indices: list[int]) -> str:
    selected = [names[i] for i in indices]
    if len(selected) == 1:
        return (
            f"The input photograph is the identity reference for {selected[0]}. Preserve that person's recognizable facial structure, "
            "hair or baldness, glasses if present, facial hair, age cues, and other defining features, while allowing a new natural expression and pose. "
            "Do not copy the original photo's background, clothing, or pose unless the theme requires it."
        )
    labels = "; ".join(f"input image {j+1} is {name}" for j, name in enumerate(selected))
    return (
        f"There are multiple identity references: {labels}. Keep every person visually distinct and matched to the correct input image. "
        "Do not blend, merge, swap, average, or confuse their facial features. Preserve each person's recognizable identity while giving them new natural expressions and poses."
    )


def _extract_json_object(raw: str) -> dict:
    raw = raw.strip()
    if raw.startswith("```"):
        parts = raw.split("```")
        if len(parts) >= 3:
            raw = parts[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()
    start = raw.find("{")
    end = raw.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("No JSON object found in model response.")
    return json.loads(raw[start:end+1])


def fallback_scene_plan(names: list[str], description: str, assignments: list[dict], age: int, book_dna: dict) -> dict:
    people = ", ".join(names)
    cover_brief = (
        f"A highly creative personalized children's-book cover for {age_label(age)} showing {people} in a scene that clearly expresses this detailed description: {description}. "
        f"Follow this unique creative fingerprint: story structure={book_dna['story_structure']}; opening={book_dna['opening_situation']}; "
        f"motif={book_dna['recurring_motif']}; mood={book_dna['mood']}; cover composition={book_dna['cover_composition']}. "
        f"Use a fresh composition, strong sense of place, expressive faces, and a clear family-friendly storybook feel."
    )
    pages = []
    for i, assignment in enumerate(assignments, start=1):
        selected = [names[x] for x in assignment["indices"]]
        who = selected[0] if len(selected) == 1 else " and ".join(selected)
        recipe = book_dna["page_recipes"][i - 1]
        pages.append({
            "page": i,
            "brief": (
                f"Page {i} should feature {who} in a specific location from the Detailed Description. "
                f"Creative recipe: {recipe['action']}; {recipe['composition']}; {recipe['energy']}. "
                f"Use the book's recurring motif ({book_dna['recurring_motif']}) only when it fits naturally. "
                f"Strongly ground the scene in this description: {description}. Complexity must strictly suit {age_label(age)}; "
                f"for preschool ages, use only a few large background elements and no decorative clutter."
            )
        })
    return {"cover_brief": cover_brief, "pages": pages}


def plan_scene_briefs(names: list[str], title: str, description: str, assignments: list[dict], age: int, book_dna: dict) -> dict:
    if not OPENAI_API_KEY:
        return fallback_scene_plan(names, description, assignments, age, book_dna)

    plan_lines = []
    for i, assignment in enumerate(assignments, start=1):
        selected = [names[x] for x in assignment["indices"]]
        label = selected[0] if len(selected) == 1 else " + ".join(selected)
        plan_lines.append(f"Page {i}: {'solo' if len(selected)==1 else 'group'} — {label}")
    plan_text = "\n".join(plan_lines)
    people = ", ".join(names)
    dna_text = book_dna_text(book_dna, include_recipes=True)
    system = (
        "You are a creative art director for children's coloring books. "
        "Transform the user's description into distinct scene briefs for image generation. "
        "AGE APPROPRIATENESS HAS HIGHEST PRIORITY: for preschool ages, simplify aggressively and do not create visually dense scene briefs; for older children and teens, progressively allow more environmental richness. "
        "Use varied sub-locations and specific actions without exceeding the target-age complexity. "
        "A hidden Book DNA creative fingerprint will be supplied. Treat every DNA field and every page recipe as a mandatory creative constraint, not a suggestion. "
        "Avoid generic default sequences and repeated stock scenes. Return strict JSON only."
    )
    user = f"""Create an 8-page interior scene plan plus one cover scene brief for a personalized children's coloring book.

Book title: {title}
Characters: {people}
Target age: {age} ({age_label(age)})\nAge-specific art guidance: {age_guidance(age)}\nEnvironment guidance: {environment_guidance(age)}\n\nDetailed Description:\n{description}\n\nUNIQUE BOOK DNA FOR THIS GENERATION (must materially shape the plan):\n{dna_text}\n\nInterior page cast plan (must be followed):
{plan_text}

Requirements:
- Create one short but specific cover_brief for the cover image.
- Create exactly 8 page briefs, one for each page listed above.
- Each page brief must be visually distinct from the others.
- Follow the Book DNA page recipe for the corresponding page, including its action archetype, composition cue, and energy.
- Let the Book DNA story structure, opening, pacing, recurring motif, supporting dynamic, and ending materially change the sequence.
- Do not fall back to the most obvious generic sequence for the theme. Two books with the same customer description but different Book DNA should feel recognizably different.
- Each page brief must clearly establish a specific environment or sub-location, but the amount of scenery must obey the target-age guidance.
- Spread the action across different rooms, landmarks, settings, or activity moments implied by the description.
- For ages 3–4, name only a few large environmental elements and leave abundant visual breathing room; for older ages, progressively allow more props, scenery, and background detail.
- Make the scenes imaginative, storybook-like, and more creative than a literal one-line interpretation.
- Keep the scenes family-friendly and suitable for a children's coloring book.
- Respect the page cast plan exactly.
- Do not include copyrighted characters or franchise-specific elements.

Return JSON only in this exact structure:
{{
  "cover_brief": "...",
  "pages": [
    {{"page": 1, "brief": "..."}},
    {{"page": 2, "brief": "..."}},
    {{"page": 3, "brief": "..."}},
    {{"page": 4, "brief": "..."}},
    {{"page": 5, "brief": "..."}},
    {{"page": 6, "brief": "..."}},
    {{"page": 7, "brief": "..."}},
    {{"page": 8, "brief": "..."}}
  ]
}}
"""

    headers = {"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"}
    payload = {
        "model": TEXT_MODEL,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 1.0,
        "max_tokens": 1800,
    }
    response = requests.post("https://api.openai.com/v1/chat/completions", headers=headers, json=payload, timeout=120)
    if response.status_code >= 400:
        return fallback_scene_plan(names, description, assignments, age, book_dna)
    try:
        raw = response.json()["choices"][0]["message"]["content"]
        data = _extract_json_object(raw)
        pages = data.get("pages", [])
        if not isinstance(data.get("cover_brief"), str) or len(pages) != len(assignments):
            raise ValueError("Planner returned invalid structure")
        normalized = []
        for i, item in enumerate(pages, start=1):
            brief = str(item.get("brief", "")).strip()
            if not brief:
                raise ValueError("Planner page brief missing")
            normalized.append({"page": i, "brief": brief})
        return {"cover_brief": str(data["cover_brief"]).strip(), "pages": normalized}
    except Exception:
        return fallback_scene_plan(names, description, assignments, age, book_dna)


def openai_edit(reference_paths: list[Path], prompt: str, quality: str) -> Image.Image:
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY is not configured. Add the key in Render.")

    url = "https://api.openai.com/v1/images/edits"
    headers = {"Authorization": f"Bearer {OPENAI_API_KEY}"}
    data = {
        "model": IMAGE_MODEL,
        "prompt": prompt,
        "size": "1088x1408",  # exact 8.5:11 aspect ratio; both dimensions divisible by 16
        "quality": quality,
        "output_format": "png",
    }

    # Multiple identity references are sent as repeated image[] multipart fields.
    with ExitStack() as stack:
        files = []
        for ref in reference_paths:
            fh = stack.enter_context(open(ref, "rb"))
            files.append(("image[]", (ref.name, fh, "image/jpeg")))
        response = requests.post(url, headers=headers, data=data, files=files, timeout=300)

    if response.status_code >= 400:
        detail = response.text[:1600]
        raise RuntimeError(f"OpenAI image request failed ({response.status_code}): {detail}")
    payload = response.json()
    try:
        b64 = payload["data"][0]["b64_json"]
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError("The image API returned no image data.") from exc
    return Image.open(io.BytesIO(base64.b64decode(b64))).convert("RGB")


def cover_prompt(names: list[str], title: str, description: str, scene_brief: str, age: int, book_dna: dict) -> str:
    people = ", ".join(names)
    ids = identity_text(names, list(range(len(names))))
    return f"""
Draw a polished full-color personalized coloring-book COVER illustration.
DETAILED DESCRIPTION:
{description}

TARGET AGE: {age} ({age_label(age)})\nAGE-APPROPRIATE ART GUIDANCE: {age_guidance(age)}\nENVIRONMENT GUIDANCE: {environment_guidance(age)}\n\nUNIQUE BOOK DNA:\n{book_dna_text(book_dna, include_recipes=False)}\n\nCREATIVE COVER BRIEF:\n{scene_brief}\n\nCharacters who must all appear: {people}
{ids}

TITLE — EXACT TEXT:
"{title}"

Render that title exactly once as decorative children's-book lettering DIRECTLY OVER THE ILLUSTRATED SCENE near the top of the cover. The title must feel hand-lettered and integrated into the artwork itself. The illustration/background must remain visible immediately behind, around, and between the letters. A subtle outline or drop shadow on the LETTERS is allowed only for readability.

ABSOLUTELY NO TITLE BACKDROP OR CONTAINER. Do not place the title on or inside any box, rectangle, rounded rectangle, white panel, solid panel, banner, ribbon, placard, sign, card, label, frame, speech bubble, cloud shape, plaque, or separate text area. Do not draw any border around the title. Do not reserve a blank white title block. The only title elements should be the letters themselves over the artwork.

Do NOT add any other words, captions, labels, logos, watermarks, or stray text.

Treat the Detailed Description as a visual specification, not merely a loose theme. The cover must clearly show the described world or location through recognizable architecture, scenery, props, objects, and atmosphere. Do not reduce the scene to only the people and supporting creatures. Use a fresh composition, natural poses, expressive faces, and a family-friendly storybook aesthetic. The complexity of the drawing, environmental density, and amount of detail must match the target age guidance. Compose the upper background so it has enough visual simplicity for lettering while still remaining part of the illustrated scene. Keep key faces and bodies safely away from page edges. Single full-page portrait composition only; no panels, grids, contact sheets, borders of mini-scenes, or collage layouts.
{COPYRIGHT_SAFETY}
""".strip()


def interior_prompt(names: list[str], description: str, page_index: int, assignment: dict, scene_brief: str, age: int, book_dna: dict) -> str:
    indices = assignment["indices"]
    selected = [names[i] for i in indices]
    who = selected[0] if len(selected) == 1 else " and ".join(selected)
    ids = identity_text(names, indices)
    return f"""
Draw ONE standalone full-page black-and-white coloring-book illustration.
DETAILED DESCRIPTION:
{description}

Featured character(s): {who}
TARGET AGE: {age} ({age_label(age)})
AGE-APPROPRIATE ART GUIDANCE:
{age_guidance(age)}

ENVIRONMENT GUIDANCE:
{environment_guidance(age)}

CREATIVE PAGE BRIEF:
{scene_brief}

UNIQUE PAGE RECIPE FOR THIS BOOK:
Action archetype: {book_dna["page_recipes"][page_index - 1]["action"]}
Composition cue: {book_dna["page_recipes"][page_index - 1]["composition"]}
Energy: {book_dna["page_recipes"][page_index - 1]["energy"]}
Recurring motif for the overall book: {book_dna["recurring_motif"]}. Use it only if it fits naturally on this page.

{ids}
The setting must be recognizable, but TARGET-AGE SIMPLICITY OVERRIDES environmental richness. For very young children, simplify or omit any scene-brief detail that would create clutter, tiny spaces, dense texture, or difficult coloring areas.

This page must feel individually illustrated. Use a different natural facial expression, head angle, body pose, and composition from repeated stock portraits. Keep the action immediately understandable. For preschool pages, prioritize one clear action and a few large shapes over cinematic complexity.

Coloring-book requirements: black-and-white line art on white paper; bold clean black outlines; no gray shading; no color; no words; no captions; no page number. Complexity, line density, number of objects, and size of coloring regions MUST follow the target-age guidance. For ages 3–4, use extra-thick outlines, huge open spaces, very few objects, almost no texture lines, minimal overlaps, and generous blank white space. Single full-page composition only. Absolutely no grids, contact sheets, montages, comic panels, or multiple scenes within the image. Keep important faces, hands, props, and environmental features away from the extreme edges.
{COPYRIGHT_SAFETY}
""".strip()


def generate_real_job(job_id: str):
    job = get_job(job_id)
    job_dir = Path(job["job_dir"])
    names = job["names"]
    refs = [Path(p) for p in job["reference_paths"]]
    try:
        assignments = page_assignments(names)
        set_job(job_id, assignments=assignments, status="working", progress=3, message="Planning creative scenes…")
        book_dna = job["book_dna"]
        scene_plan = plan_scene_briefs(names, job["title"], job["description"], assignments, job["age"], book_dna)
        set_job(job_id, scene_plan=scene_plan, progress=8, message="Generating high-quality cover…")
        cover = openai_edit(refs, cover_prompt(names, job["title"], job["description"], scene_plan["cover_brief"], job["age"], book_dna), "high")
        cover_path = job_dir / "cover.png"
        cover.save(cover_path, "PNG")

        for i, assignment in enumerate(assignments, start=1):
            pct = 12 + int((i - 1) / 8 * 74)
            actors = [names[x] for x in assignment["indices"]]
            set_job(job_id, progress=pct, message=f"Generating coloring page {i} of 8 — {', '.join(actors)}…")
            selected_refs = [refs[x] for x in assignment["indices"]]
            page_brief = scene_plan["pages"][i - 1]["brief"]
            img = openai_edit(selected_refs, interior_prompt(names, job["description"], i, assignment, page_brief, job["age"], book_dna), "low")
            img.save(job_dir / f"page_{i}.png", "PNG", optimize=True)

        set_job(job_id, progress=90, message="Building print-ready PDF…")
        pdf = build_pdf(job_dir, job["title"])
        set_job(job_id, status="done", progress=100, message="Book ready for review.", pdf=str(pdf))
    except Exception as exc:
        set_job(job_id, status="error", progress=0, message="Generation stopped.", error=str(exc))


def build_preset_demo_pdf(preset_key: str, job_dir: Path) -> Path:
    preset = DEMO_PRESETS[preset_key]
    source_dir = DEMO_PRESETS_DIR / preset_key
    output = job_dir / f"{safe_slug(preset['title'])}_demo.pdf"
    c = canvas.Canvas(str(output), pagesize=letter)
    pw, ph = letter

    ordered: list[Optional[Path]] = [source_dir / "cover.jpg", None]
    ordered += [source_dir / f"page_{i}.jpg" for i in range(1, preset["interior_pages"] + 1)]
    ordered += [None, None]

    expected = preset["pdf_pages"]
    if len(ordered) != expected:
        raise RuntimeError(f"Demo page plan has {len(ordered)} pages but preset expects {expected}.")

    for path in ordered:
        if path is not None:
            if not path.exists():
                raise RuntimeError(f"Missing demo asset: {path.name}")
            with Image.open(path) as im:
                iw, ih = im.size
            scale = min(pw / iw, ph / ih)
            w, h = iw * scale, ih * scale
            x, y = (pw - w) / 2, (ph - h) / 2
            c.drawImage(ImageReader(str(path)), x, y, width=w, height=h, preserveAspectRatio=True, mask="auto")
        c.showPage()
    c.save()
    return output


def generate_preset_demo_job(job_id: str):
    job = get_job(job_id)
    preset = DEMO_PRESETS[job["preset"]]
    job_dir = Path(job["job_dir"])
    try:
        total = preset["interior_pages"]
        set_job(job_id, status="working", progress=5, message="Loading pre-generated demo artwork - no API calls...")
        time.sleep(0.15)
        for i in range(1, total + 1):
            progress = 8 + int(i / total * 78)
            set_job(job_id, progress=progress, message=f"Preparing demo page {i} of {total}...")
            time.sleep(0.05)
        set_job(job_id, progress=90, message=f"Building {preset['pdf_pages']}-page demo PDF...")
        pdf = build_preset_demo_pdf(job["preset"], job_dir)
        set_job(job_id, status="done", progress=100, message=f"{preset['label']} demo ready. No API credit used.", pdf=str(pdf))
    except Exception as exc:
        set_job(job_id, status="error", progress=0, message="Demo failed.", error=str(exc))


def randomized_creative_direction(description: str, names: list[str], book_dna: dict) -> str:
    who = names[0] if len(names) == 1 else " and ".join(names)
    return (
        f"Create a completely new visual approach for {who} based on this Detailed Description: '{description}'. "
        f"Use this story structure: {book_dna['story_structure']}. Begin from this opening idea: {book_dna['opening_situation']}. "
        f"Emphasize {book_dna['activity_emphasis']}. Use {book_dna['recurring_motif']} as an occasional visual thread. "
        f"The pacing should follow: {book_dna['pacing_pattern']}. The overall mood should be {book_dna['mood']}. "
        f"For the cover, {book_dna['cover_composition']} Deliberately choose different expressions, poses, props, "
        "foreground/background arrangements, and scene compositions from any previous attempt."
    )


def manual_prompt_1(names: list[str], title: str, description: str, direction: str, age: int, book_dna: dict) -> str:
    char_lines = []
    for i, name in enumerate(names, start=1):
        char_lines.append(f"Person {i}: {name}\nUse {name}'s uploaded original photo only as {name}'s identity reference.")
    characters = "\n\n".join(char_lines)

    if len(names) == 1:
        distribution = f"All 20 interior pages should feature {names[0]}, with substantial variation in expression, pose, viewpoint, activity, props, and environment."
    else:
        joined = " and ".join(names)
        distribution = f"""Distribute the 20 interior illustrations as a balanced, INTERLEAVED mix of:
- solo scenes featuring individual characters
- shared scenes featuring ALL characters together

Do NOT cluster all solo scenes first and all shared scenes later. The early, middle, and late portions of the book must each contain a mix of solo and shared scenes. Make sure every character appears throughout the book and is represented fairly.

When a page features one person, make that person the clear identity focus. When a page features {joined} together, keep each person's identity separate and consistent with their corresponding uploaded photo. Do not blend, merge, swap, average, or confuse identities."""

    return f"""START A BRAND-NEW CHATGPT CONVERSATION FOR THIS REQUEST.

Upload the ORIGINAL source photograph(s) again before pasting this prompt.

Do not upload or reference artwork generated during any previous attempt.

CREATE A COMPLETELY FRESH PERSONALIZED COLORING-BOOK DESIGN.

BOOK DETAILS
Title: \"{title}\"
Detailed Description:
{description}

CHARACTERS

{characters}

If multiple people are provided, keep each person visually distinct and matched to their own uploaded photo. Do NOT blend, merge, confuse, or swap their identities.

FRESH REDESIGN REQUIREMENT

Treat this as a completely new visual concept created from scratch.

Use ONLY the newly uploaded ORIGINAL photographs as identity references.

Do NOT use, imitate, continue, revise, trace, or closely reproduce any previously generated AI artwork, including previous covers, poses, expressions, scene layouts, backgrounds, camera angles, props, title treatments, costumes, compositions, or coloring pages.

Previous AI-generated artwork must NOT be treated as a visual reference.

Preserve the recognizable identity and physical characteristics of each person in their original photograph, but redesign everything else from scratch.

CREATIVE DIRECTION FOR THIS ATTEMPT

{direction}

Use this direction as inspiration for a genuinely new design. Do not merely make a small variation of a previous composition.

UNIQUE BOOK DNA — REQUIRED

The website generated the following hidden creative fingerprint specifically for THIS book request. Treat it as a required creative constraint. It exists to ensure that another customer who enters the same title, age, characters, and Detailed Description can still receive a materially different book.

{book_dna_text(book_dna, include_recipes=True)}

Do not replace these choices with generic defaults. Build the 20-page sequence around this fingerprint. The exact settings and activities must still come from the user's Detailed Description, but the Book DNA must noticeably influence the story structure, scene order, activity emphasis, pacing, composition, recurring visual motif, supporting-character use, and ending.

AGE-APPROPRIATE DETAIL LEVEL

{age_guidance(age)}

{environment_guidance(age)}

These age rules have higher priority than requests for environmental richness. For preschool ages, a recognizable but sparse setting is correct; do NOT fill the page with detail merely because the Detailed Description contains many possible objects or locations.

DETAILED DESCRIPTION / ENVIRONMENT REQUIREMENT

Treat the Detailed Description as a visual specification for the entire book, not merely a loose theme. Use it as the main source for:
- settings and locations
- rooms, structures, landscapes, or other sub-settings
- activities and actions
- props and important objects
- mood and atmosphere
- supporting creatures or characters
- environmental decorations and visual details

Before creating the artwork, plan a varied sequence of scenes so the book explores different locations, rooms, areas, activities, and visual details described by the user. Spread these throughout the beginning, middle, and end of the book.

Every interior page must clearly show WHERE the action is happening. Do not create pages that only show the person and a creature/object against an empty or generic background. Each page should include a meaningful environmental setting, but its density must match the target age. For ages 3–4, use only a few large location-specific elements and plenty of blank white space; do not force multiple layers of detail.

ARTWORK TO CREATE

Create exactly:
- 1 standalone full-color cover
- 20 standalone black-and-white coloring-book illustrations

These are artwork assets only. DO NOT create the PDF yet. I will review the artwork first.

COVER

Create one full-color cover featuring all listed characters together in an original scene that clearly depicts the Detailed Description.

The cover must contain the exact title:
\"{title}\"

Keep every person recognizable from their own uploaded original photograph. Use a distinctive composition appropriate to the Creative Direction above.

20 COLORING PAGES

Create 20 different scenes based on the Detailed Description above.

Every coloring page must be its OWN SEPARATE, STANDALONE IMAGE.

ABSOLUTELY DO NOT:
- create grids
- create contact sheets
- create montages
- create comic panels containing several scenes
- combine multiple coloring pages into one generated image

ONE IMAGE = ONE COLORING-BOOK PAGE.

If image generation must happen in multiple batches, continue making separate standalone images until all 20 coloring pages exist.

MULTI-PERSON / CHARACTER DISTRIBUTION

{distribution}

VARIATION REQUIREMENT

Every page should feel individually illustrated. Deliberately vary facial expression, head angle, body position, pose, viewing angle, distance from the viewer, activity, props, and surrounding environment. Do not copy and paste the same head, expression, or pose from one page to another.

Follow the 20 Book DNA page recipes above in order. A page recipe controls the broad action archetype, composition, and energy; adapt it intelligently to the Detailed Description rather than ignoring it. Avoid the most obvious repeated stock sequence for the theme. If another book used the same customer description with different Book DNA, the two finished books should have clearly different scene sequences and visual rhythms.

COLORING-BOOK STYLE

Every interior image must have:\n- black-and-white line art only\n- white paper with a fully drawn environmental line-art setting\n- bold, clean outlines\n- age-appropriate coloring spaces and complexity\n- for ages 3–4: extra-thick outlines, huge open shapes, very few objects, minimal overlap, almost no texture lines, and generous blank white space\n- progressively more detail for older children and teens\n- no tiny decorative detail for preschool pages\n- no grayscale shading
- no colored elements
- no captions
- no story text
- no page numbers
- no empty or generic backgrounds; each page must visibly establish its location with setting details from the Detailed Description

PAGE COMPOSITION

Compose every cover and coloring page vertically for a US Letter portrait page with an 8.5:11 aspect ratio. Keep important artwork away from the extreme edges so it can later be placed safely onto an 8.5 × 11 inch print page without cropping the subject.

COPYRIGHT SAFETY

Use only original, generic imagery appropriate to the Detailed Description. Do not include copyrighted characters, recognizable franchise designs, logos, branded costumes, professional team logos, trademarked mascot designs, or direct recreations of copyrighted artwork.

FINAL INSTRUCTION

Complete the cover and all 20 separate coloring-page images.

DO NOT assemble a PDF yet.

STOP once the artwork is complete so I can review it before creating the final print-ready file."""


def manual_prompt_2() -> str:
    return """I am satisfied with the artwork created above.

Now use the EXISTING APPROVED cover and 20 coloring-book images from this conversation to create the finished print-ready coloring book PDF.

Do not redesign or regenerate the artwork unless an image is technically missing or unusable.

The individual images are now source assets for the final file.

FINAL BOOK STRUCTURE

Create exactly 24 pages in this order:

Page 1:
The existing approved full-color cover

Page 2:
Completely blank white page

Pages 3–22:
The existing 20 approved coloring-book images, in their original sequence, one image per page

Pages 23–24:
Completely blank white pages

FINAL PAGE SIZE

Every PDF page must be TRUE US Letter size:
8.5 × 11 inches
Portrait orientation
612 × 792 PDF points

When preparing raster artwork for printing, an 8.5 × 11 inch canvas equivalent to 2550 × 3300 pixels at 300 DPI may be used.

Do not stretch or distort any image.

If an image does not perfectly match the Letter-page aspect ratio:
- preserve its proportions
- center it on a white US Letter canvas
- scale it as large as practical
- do not crop important parts of the person or scene

BLANK PAGES

Create pages 2, 23, and 24 locally as completely white pages. Do not use image generation to make the blank pages.

PDF ASSEMBLY

Assemble the existing approved artwork and blank pages into ONE downloadable PDF. Do not stop after describing how the PDF would be created. Actually create the file.

VERIFY BEFORE FINISHING

Programmatically verify that:
- the PDF file exists
- the PDF contains exactly 24 pages
- every page measures exactly 8.5 × 11 inches
- page 1 contains the approved color cover
- page 2 is completely blank
- pages 3–22 contain the 20 approved coloring pages
- each coloring image occupies its own individual page
- pages 23 and 24 are completely blank
- no artwork has been stretched or distorted

If a technical formatting problem is found, correct it before returning the file.

FINAL RESPONSE REQUIREMENT

The task is complete ONLY after the verified PDF has been created.

Your final response must provide the finished downloadable print-ready PDF file."""


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/", response_class=HTMLResponse)
def home():
    return (STATIC_DIR / "index.html").read_text(encoding="utf-8")


@app.get("/api/config")
def config():
    return {
        "api_configured": bool(OPENAI_API_KEY),
        "model": IMAGE_MODEL,
        "planner_model": TEXT_MODEL,
        "live_pages": 8,
        "live_pdf_pages": 12,
        "manual_pdf_pages": 24,
        "book_dna_enabled": True,
        "version": APP_VERSION,
    }


@app.get("/api/demo-presets")
def demo_presets():
    return {
        key: {
            "label": value["label"],
            "title": value["title"],
            "name": value["name"],
            "age": value["age"],
            "description": value["description"],
            "interior_pages": value["interior_pages"],
            "pdf_pages": value["pdf_pages"],
        }
        for key, value in DEMO_PRESETS.items()
    }


@app.post("/api/demo-jobs")
async def create_demo_job(request: Request):
    cleanup_old_jobs()
    body = await request.json()
    preset_key = str(body.get("preset", "")).strip()
    if preset_key not in DEMO_PRESETS:
        raise HTTPException(400, "Choose a valid demo preset.")
    preset = DEMO_PRESETS[preset_key]
    job_id = uuid.uuid4().hex[:12]
    job_dir = JOBS_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    jobs[job_id] = {
        "id": job_id,
        "created": time.time(),
        "status": "queued",
        "progress": 1,
        "message": "Starting demo...",
        "kind": "preset_demo",
        "preset": preset_key,
        "title": preset["title"],
        "job_dir": str(job_dir),
        "pdf": None,
    }
    threading.Thread(target=generate_preset_demo_job, args=(job_id,), daemon=True).start()
    return {"id": job_id}


@app.post("/api/random-book-idea")
async def random_book_idea(request: Request):
    body = await request.json()
    name = str(body.get("name", "") or "").strip()
    subject = str(body.get("subject", "") or "").strip()
    tone = str(body.get("tone", "") or "").strip()
    age_raw = str(body.get("age", "") or "").strip()
    age: Optional[int] = None
    if age_raw:
        try:
            age = int(age_raw)
        except ValueError:
            raise HTTPException(400, "Target age must be a whole number between 3 and 17.")
        if age < 3 or age > 17:
            raise HTTPException(400, "Target age must be between 3 and 17.")
    return generate_random_book_idea(name=name, age=age, subject=subject, tone=tone)


@app.post("/api/manual-prompts")
async def make_manual_prompts(request: Request):
    body = await request.json()
    names = [str(x).strip() for x in body.get("names", []) if str(x).strip()]
    title = str(body.get("title", "")).strip()
    description = str(body.get("description", "")).strip()
    age = int(body.get("age", 8) or 8)
    if not names or not title or not description:
        raise HTTPException(400, "Names, title, a target age, and a detailed description are required.")
    if age < 3 or age > 17:
        raise HTTPException(400, "Target age must be between 3 and 17.")
    book_dna = generate_book_dna(age, 20)
    direction = randomized_creative_direction(description, names, book_dna)
    return {
        "prompt1": manual_prompt_1(names, title, description, direction, age, book_dna),
        "prompt2": manual_prompt_2(),
        "creative_direction": direction,
        "book_dna_id": book_dna["id"],
    }


@app.post("/api/jobs")
async def create_job(
    title: str = Form(...),
    description: str = Form(...),
    age: int = Form(...),
    character_names: list[str] = Form(...),
    photos: list[UploadFile] = File(...),
):
    cleanup_old_jobs()
    title = title.strip()
    description = description.strip()
    names = [n.strip() for n in character_names if n.strip()]
    if not title or not description:
        raise HTTPException(400, "Book title, target age, and a detailed description are required.")
    if age < 3 or age > 17:
        raise HTTPException(400, "Target age must be between 3 and 17.")
    if not 1 <= len(names) <= 4:
        raise HTTPException(400, "Add between 1 and 4 people.")
    clean_photos = [p for p in photos if p and getattr(p, "filename", "")]
    if len(names) != len(clean_photos):
        raise HTTPException(400, "Every person needs exactly one photo.")
    if not OPENAI_API_KEY:
        raise HTTPException(400, "Live generation is not available until OPENAI_API_KEY is configured.")

    job_id = uuid.uuid4().hex[:12]
    job_dir = JOBS_DIR / job_id
    job_dir.mkdir(parents=True)
    refs = []
    try:
        for i, upload in enumerate(clean_photos, start=1):
            data = await upload.read()
            image = read_and_normalize_upload(data)
            ref = job_dir / f"reference_{i}.jpg"
            save_reference(image, ref)
            refs.append(str(ref))
    except ValueError as exc:
        shutil.rmtree(job_dir, ignore_errors=True)
        raise HTTPException(400, str(exc))

    jobs[job_id] = {
        "id": job_id,
        "created": time.time(),
        "status": "queued",
        "progress": 1,
        "message": "Starting...",
        "kind": "live",
        "title": title,
        "description": description,
        "age": age,
        "names": names,
        "reference_paths": refs,
        "job_dir": str(job_dir),
        "pdf": None,
        "assignments": page_assignments(names),
        "book_dna": generate_book_dna(age, 8),
        "scene_plan": None,
    }
    threading.Thread(target=generate_real_job, args=(job_id,), daemon=True).start()
    return {"id": job_id}


@app.get("/api/jobs/{job_id}")
def job_status(job_id: str):
    job = get_job(job_id)
    payload = {
        "id": job_id,
        "status": job["status"],
        "progress": job.get("progress", 0),
        "message": job.get("message", ""),
        "error": job.get("error"),
        "kind": job.get("kind", "live"),
    }
    if job["status"] == "done":
        payload["download"] = f"/api/jobs/{job_id}/download"
        if job.get("kind") == "preset_demo":
            preset = DEMO_PRESETS[job["preset"]]
            payload["pdf_pages"] = preset["pdf_pages"]
            payload["images"] = [
                {"label": "Cover", "url": f"/api/jobs/{job_id}/image/cover", "retry": False, "quality": "Sample"},
                *[
                    {"label": f"Coloring page {i}", "url": f"/api/jobs/{job_id}/image/{i}", "retry": False, "quality": "Sample"}
                    for i in range(1, preset["interior_pages"] + 1)
                ],
            ]
        else:
            payload["pdf_pages"] = 12
            payload["images"] = [
                {"label": "Cover", "url": f"/api/jobs/{job_id}/image/cover", "retry": False, "quality": "High"},
                *[
                    {"label": f"Coloring page {i}", "url": f"/api/jobs/{job_id}/image/{i}", "retry": True, "quality": "Low"}
                    for i in range(1, 9)
                ],
            ]
    return payload


@app.get("/api/jobs/{job_id}/image/{page}")
def job_image(job_id: str, page: str):
    job = get_job(job_id)
    filename = ("cover.jpg" if job.get("kind") == "preset_demo" else "cover.png") if page == "cover" else (f"page_{int(page)}.jpg" if job.get("kind") == "preset_demo" else f"page_{int(page)}.png")
    if job.get("kind") == "preset_demo":
        path = DEMO_PRESETS_DIR / job["preset"] / filename
    else:
        path = Path(job["job_dir"]) / filename
    if not path.exists():
        raise HTTPException(404, "Image not ready.")
    return FileResponse(path, media_type=("image/jpeg" if path.suffix.lower() in {".jpg", ".jpeg"} else "image/png"), headers={"Cache-Control": "no-store"})


@app.get("/api/jobs/{job_id}/download")
def download(job_id: str):
    job = get_job(job_id)
    if job.get("status") != "done" or not job.get("pdf"):
        raise HTTPException(409, "PDF is not ready yet.")
    path = Path(job["pdf"])
    return FileResponse(path, media_type="application/pdf", filename=path.name)


@app.post("/api/jobs/{job_id}/retry/{page_num}")
def retry_page(job_id: str, page_num: int):
    job = get_job(job_id)
    if job.get("kind") != "live":
        raise HTTPException(400, "Demo pages are fixed samples and cannot be retried.")
    if not 1 <= page_num <= 8:
        raise HTTPException(400, "Page must be between 1 and 8.")
    if job.get("status") not in {"done", "error"}:
        raise HTTPException(409, "Wait until generation finishes before retrying a page.")
    if not OPENAI_API_KEY:
        raise HTTPException(400, "OPENAI_API_KEY is not configured.")

    assignment = job["assignments"][page_num - 1]
    refs = [Path(p) for p in job["reference_paths"]]
    selected_refs = [refs[x] for x in assignment["indices"]]
    book_dna = job.get("book_dna") or generate_book_dna(job["age"], 8)
    scene_plan = job.get("scene_plan") or fallback_scene_plan(job["names"], job["description"], job["assignments"], job["age"], book_dna)
    page_brief = scene_plan["pages"][page_num - 1]["brief"]
    try:
        img = openai_edit(selected_refs, interior_prompt(job["names"], job["description"], page_num, assignment, page_brief, job["age"], book_dna), "medium")
        img.save(Path(job["job_dir"]) / f"page_{page_num}.png", "PNG", optimize=True)
        pdf = build_pdf(Path(job["job_dir"]), job["title"])
        set_job(job_id, status="done", progress=100, message=f"Page {page_num} regenerated at medium quality.", pdf=str(pdf))
        return {"ok": True, "message": f"Page {page_num} regenerated at medium quality."}
    except Exception as exc:
        raise HTTPException(500, str(exc))
