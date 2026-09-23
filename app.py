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

APP_VERSION = "three-section-pure-demo-v8.0"
TEXT_MODEL = os.getenv("TEXT_MODEL", "gpt-4.1-mini").strip() or "gpt-4.1-mini"

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


def fallback_scene_plan(names: list[str], description: str, assignments: list[dict], age: int) -> dict:
    people = ", ".join(names)
    cover_brief = (
        f"A highly creative personalized children's-book cover for {age_label(age)} showing {people} in a scene that clearly expresses this detailed description: {description}. "
        f"Use a fresh composition, strong sense of place, expressive faces, layered foreground/midground/background detail, and a clear family-friendly storybook feel."
    )
    pages = []
    for i, assignment in enumerate(assignments, start=1):
        selected = [names[x] for x in assignment["indices"]]
        who = selected[0] if len(selected) == 1 else " and ".join(selected)
        pages.append({
            "page": i,
            "brief": f"Page {i} should feature {who} in {SCENE_DIRECTIONS[i-1]}, strongly grounded in this detailed description: {description}. Show a specific location and clear action. Complexity must strictly suit {age_label(age)}; for preschool ages, use only a few large background elements and no decorative clutter."
        })
    return {"cover_brief": cover_brief, "pages": pages}


def plan_scene_briefs(names: list[str], title: str, description: str, assignments: list[dict], age: int) -> dict:
    if not OPENAI_API_KEY:
        return fallback_scene_plan(names, description, assignments, age)

    plan_lines = []
    for i, assignment in enumerate(assignments, start=1):
        selected = [names[x] for x in assignment["indices"]]
        label = selected[0] if len(selected) == 1 else " + ".join(selected)
        plan_lines.append(f"Page {i}: {'solo' if len(selected)==1 else 'group'} — {label}")
    plan_text = "\n".join(plan_lines)
    people = ", ".join(names)
    system = (
        "You are a creative art director for children's coloring books. "
        "Transform the user's description into distinct scene briefs for image generation. "
        "AGE APPROPRIATENESS HAS HIGHEST PRIORITY: for preschool ages, simplify aggressively and do not create visually dense scene briefs; for older children and teens, progressively allow more environmental richness. "
        "Use varied sub-locations and specific actions without exceeding the target-age complexity. Avoid generic repeated scenes. Return strict JSON only."
    )
    user = f"""Create an 8-page interior scene plan plus one cover scene brief for a personalized children's coloring book.

Book title: {title}
Characters: {people}
Target age: {age} ({age_label(age)})\nAge-specific art guidance: {age_guidance(age)}\nEnvironment guidance: {environment_guidance(age)}\n\nDetailed Description:\n{description}\n\nInterior page cast plan (must be followed):
{plan_text}

Requirements:
- Create one short but specific cover_brief for the cover image.
- Create exactly 8 page briefs, one for each page listed above.
- Each page brief must be visually distinct from the others.
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
        return fallback_scene_plan(names, description, assignments, age)
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
        return fallback_scene_plan(names, description, assignments, age)


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


def cover_prompt(names: list[str], title: str, description: str, scene_brief: str, age: int) -> str:
    people = ", ".join(names)
    ids = identity_text(names, list(range(len(names))))
    return f"""
Draw a polished full-color personalized coloring-book COVER illustration.
DETAILED DESCRIPTION:
{description}

TARGET AGE: {age} ({age_label(age)})\nAGE-APPROPRIATE ART GUIDANCE: {age_guidance(age)}\nENVIRONMENT GUIDANCE: {environment_guidance(age)}\n\nCREATIVE COVER BRIEF:\n{scene_brief}\n\nCharacters who must all appear: {people}
{ids}

TITLE — EXACT TEXT:
"{title}"

Render that title exactly once as decorative children's-book lettering DIRECTLY OVER THE ILLUSTRATED SCENE near the top of the cover. The title must feel hand-lettered and integrated into the artwork itself. The illustration/background must remain visible immediately behind, around, and between the letters. A subtle outline or drop shadow on the LETTERS is allowed only for readability.

ABSOLUTELY NO TITLE BACKDROP OR CONTAINER. Do not place the title on or inside any box, rectangle, rounded rectangle, white panel, solid panel, banner, ribbon, placard, sign, card, label, frame, speech bubble, cloud shape, plaque, or separate text area. Do not draw any border around the title. Do not reserve a blank white title block. The only title elements should be the letters themselves over the artwork.

Do NOT add any other words, captions, labels, logos, watermarks, or stray text.

Treat the Detailed Description as a visual specification, not merely a loose theme. The cover must clearly show the described world or location through recognizable architecture, scenery, props, objects, and atmosphere. Do not reduce the scene to only the people and supporting creatures. Use a fresh composition, natural poses, expressive faces, and a family-friendly storybook aesthetic. The complexity of the drawing, environmental density, and amount of detail must match the target age guidance. Compose the upper background so it has enough visual simplicity for lettering while still remaining part of the illustrated scene. Keep key faces and bodies safely away from page edges. Single full-page portrait composition only; no panels, grids, contact sheets, borders of mini-scenes, or collage layouts.
{COPYRIGHT_SAFETY}
""".strip()


def interior_prompt(names: list[str], description: str, page_index: int, assignment: dict, scene_brief: str, age: int) -> str:
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
        scene_plan = plan_scene_briefs(names, job["title"], job["description"], assignments, job["age"])
        set_job(job_id, scene_plan=scene_plan, progress=8, message="Generating high-quality cover…")
        cover = openai_edit(refs, cover_prompt(names, job["title"], job["description"], scene_plan["cover_brief"], job["age"]), "high")
        cover_path = job_dir / "cover.png"
        cover.save(cover_path, "PNG")

        for i, assignment in enumerate(assignments, start=1):
            pct = 12 + int((i - 1) / 8 * 74)
            actors = [names[x] for x in assignment["indices"]]
            set_job(job_id, progress=pct, message=f"Generating coloring page {i} of 8 — {', '.join(actors)}…")
            selected_refs = [refs[x] for x in assignment["indices"]]
            page_brief = scene_plan["pages"][i - 1]["brief"]
            img = openai_edit(selected_refs, interior_prompt(names, job["description"], i, assignment, page_brief, job["age"]), "low")
            img.save(job_dir / f"page_{i}.png", "PNG", optimize=True)

        set_job(job_id, progress=90, message="Building print-ready PDF…")
        pdf = build_pdf(job_dir, job["title"])
        set_job(job_id, status="done", progress=100, message="Book ready for review.", pdf=str(pdf))
    except Exception as exc:
        set_job(job_id, status="error", progress=0, message="Generation stopped.", error=str(exc))


def generate_preset_demo_job(job_id: str):
    job = get_job(job_id)
    preset = DEMO_PRESETS[job["preset"]]
    try:
        total = preset["interior_pages"]
        set_job(job_id, status="working", progress=5, message="Loading pre-generated demo artwork - no API calls...")
        time.sleep(0.15)
        for i in range(1, total + 1):
            progress = 8 + int(i / total * 82)
            set_job(job_id, progress=progress, message=f"Preparing demo page {i} of {total}...")
            time.sleep(0.05)
        pdf = DEMO_PRESETS_DIR / job["preset"] / "book.pdf"
        set_job(job_id, status="done", progress=100, message=f"{preset['label']} demo ready. No API credit used.", pdf=str(pdf))
    except Exception as exc:
        set_job(job_id, status="error", progress=0, message="Demo failed.", error=str(exc))


def randomized_creative_direction(description: str, names: list[str]) -> str:
    who = names[0] if len(names) == 1 else " and ".join(names)
    return (
        f"Create a completely new visual approach for {who} based on this Detailed Description: '{description}'. "
        f"{random.choice(COVER_COMPOSITIONS)} The overall mood should be {random.choice(MOODS)}. "
        f"Across the interior artwork, {random.choice(VIEWPOINTS)}. Deliberately choose different expressions, poses, props, "
        "foreground/background arrangements, and scene compositions from any previous attempt."
    )


def manual_prompt_1(names: list[str], title: str, description: str, direction: str, age: int) -> str:
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
    jobs[job_id] = {
        "id": job_id,
        "created": time.time(),
        "status": "queued",
        "progress": 1,
        "message": "Starting demo...",
        "kind": "preset_demo",
        "preset": preset_key,
        "title": preset["title"],
        "pdf": None,
    }
    threading.Thread(target=generate_preset_demo_job, args=(job_id,), daemon=True).start()
    return {"id": job_id}


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
    direction = randomized_creative_direction(description, names)
    return {"prompt1": manual_prompt_1(names, title, description, direction, age), "prompt2": manual_prompt_2(), "creative_direction": direction}


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
    scene_plan = job.get("scene_plan") or fallback_scene_plan(job["names"], job["description"], job["assignments"], job["age"])
    page_brief = scene_plan["pages"][page_num - 1]["brief"]
    try:
        img = openai_edit(selected_refs, interior_prompt(job["names"], job["description"], page_num, assignment, page_brief, job["age"]), "medium")
        img.save(Path(job["job_dir"]) / f"page_{page_num}.png", "PNG", optimize=True)
        pdf = build_pdf(Path(job["job_dir"]), job["title"])
        set_job(job_id, status="done", progress=100, message=f"Page {page_num} regenerated at medium quality.", pdf=str(pdf))
        return {"ok": True, "message": f"Page {page_num} regenerated at medium quality."}
    except Exception as exc:
        raise HTTPException(500, str(exc))
