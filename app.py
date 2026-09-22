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
DEMO_ASSETS = ROOT / "demo_assets"
JOBS_DIR.mkdir(exist_ok=True)

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
IMAGE_MODEL = os.getenv("IMAGE_MODEL", "gpt-image-2").strip() or "gpt-image-2"
SITE_PASSWORD = os.getenv("SITE_PASSWORD", "").strip()
JOB_TTL_HOURS = float(os.getenv("JOB_TTL_HOURS", "6") or 6)

app = FastAPI(title="Personalized Coloring Book Demo")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

jobs: dict[str, dict] = {}
jobs_lock = threading.Lock()

COPYRIGHT_SAFETY = (
    "Use only original, generic imagery. Do not include or closely imitate copyrighted characters, "
    "recognizable franchise designs, team logos, branded costumes, company logos, trademarked mascots, "
    "or other protected fictional designs."
)

DEMO_INTERIORS = [
    "waving_astronaut_on_the_moon.png",
    "smiling_astronaut_rover_adventure.png",
    "mustached_astronaut_s_rocket_adventure.png",
    "cheerful_spacewalk_over_earth.png",
    "astronaut_and_alien_moon_adventure.png",
    "jovial_astronaut_floating_among_stars.png",
    "guitar_playing_astronaut_on_an_asteroid.png",
    "moon_mission_with_a_happy_space_dog.png",
]

SCENE_DIRECTIONS = [
    "an arrival or first-discovery moment, with the character actively entering the themed setting",
    "a hands-on fundamentals or learning moment, using a prop naturally related to the theme",
    "an energetic action scene with clear body movement and a noticeably different camera angle",
    "a curious close-to-medium view interacting with an interesting feature of the environment",
    "a skill-practice scene with a focused expression and different stance from earlier pages",
    "a playful or surprising moment with an expressive reaction and a distinct background",
    "a teamwork or accomplishment scene that feels warm and celebratory",
    "a final adventurous scene with a proud or delighted expression and a strong full-page composition",
]

COVER_COMPOSITIONS = [
    "Use a lively three-quarter composition with the characters in the foreground and the themed world opening behind them. Integrate the title naturally near the top of the composition with clear readable storybook lettering.",
    "Use a dynamic low-angle storybook composition with the characters caught in an active moment rather than posing. Include a clear readable title near the top, integrated into the cover design.",
    "Use a warm cinematic wide composition with foreground props framing the characters and a clear themed landmark behind them. Integrate readable title text naturally into the upper part of the cover.",
    "Use an inviting close-to-medium composition centered on the characters discovering something together, with layered scenery creating depth. Make the upper area suitable for readable integrated title lettering.",
    "Use an asymmetrical adventure-poster composition with the characters offset from center and a strong environmental feature balancing the scene. Design the upper area so the title can appear clearly as part of the illustration.",
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


def add_cover_title(image_path: Path, title: str):
    im = Image.open(image_path).convert("RGB")
    draw = ImageDraw.Draw(im)
    max_width = int(im.width * 0.84)
    title_font = font(max(44, int(im.width * 0.07)), bold=True)
    lines = wrap_text(draw, title, title_font, max_width)
    line_h = int(title_font.size * 1.12) if hasattr(title_font, "size") else 64
    total_h = line_h * len(lines)
    y = max(36, int(im.height * 0.055))
    pad = 22
    # subtle light panel for guaranteed legibility
    widest = max(draw.textbbox((0, 0), line, font=title_font)[2] for line in lines)
    x0 = (im.width - widest) // 2 - pad
    x1 = (im.width + widest) // 2 + pad
    draw.rounded_rectangle((x0, y-pad, x1, y+total_h+pad), radius=18, fill=(255,255,255,225), outline=(0,0,0), width=3)
    for line in lines:
        box = draw.textbbox((0, 0), line, font=title_font)
        x = (im.width - (box[2] - box[0])) // 2
        draw.text((x, y), line, font=title_font, fill="black")
        y += line_h
    im.save(image_path, "PNG", optimize=True)


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


def openai_edit(reference_paths: list[Path], prompt: str, quality: str) -> Image.Image:
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY is not configured. Use Demo Mode or add the key in Render.")

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


def cover_prompt(names: list[str], title: str, theme: str) -> str:
    people = ", ".join(names)
    ids = identity_text(names, list(range(len(names))))
    return f"""
Draw a polished full-color personalized coloring-book COVER illustration.
Theme: {theme}
Characters who must all appear: {people}
{ids}
Render the exact book title "{title}" exactly once, clearly and legibly, integrated naturally into the cover design near the top. Use playful children's-book typography that feels part of the artwork itself. Do NOT place the title inside a plain white rectangular box. Do NOT add any other words, captions, labels, logos, or stray text.
Create a warm, appealing, original scene that clearly communicates the theme. Use a fresh composition, natural poses, expressive faces, and a family-friendly storybook aesthetic. Keep key faces and bodies safely away from page edges. Single full-page portrait composition only; no panels, grids, contact sheets, borders of mini-scenes, or collage layouts.
{COPYRIGHT_SAFETY}
""".strip()


def interior_prompt(names: list[str], theme: str, page_index: int, assignment: dict) -> str:
    indices = assignment["indices"]
    selected = [names[i] for i in indices]
    who = selected[0] if len(selected) == 1 else " and ".join(selected)
    ids = identity_text(names, indices)
    scene = SCENE_DIRECTIONS[page_index - 1]
    return f"""
Draw ONE standalone full-page black-and-white coloring-book illustration.
Theme: {theme}
Featured character(s): {who}
Scene direction: {scene}.
{ids}
This page must feel individually illustrated. Use a facial expression, head angle, body pose, camera/viewing angle, and composition that are noticeably different from a repeated stock portrait. Make the action visually clear and appropriate to the theme.
Coloring-book requirements: pure white background; bold clean black outlines; large colorable spaces; simple readable forms; minimal tiny detail; no gray shading; no color; no words; no captions; no page number. Single full-page composition only. Absolutely no grids, contact sheets, montages, comic panels, or multiple scenes within the image. Keep important faces, hands, and props away from the extreme edges.
{COPYRIGHT_SAFETY}
""".strip()


def generate_real_job(job_id: str):
    job = get_job(job_id)
    job_dir = Path(job["job_dir"])
    names = job["names"]
    refs = [Path(p) for p in job["reference_paths"]]
    try:
        set_job(job_id, status="working", progress=3, message="Generating high-quality cover…")
        cover = openai_edit(refs, cover_prompt(names, job["title"], job["theme"]), "high")
        cover_path = job_dir / "cover.png"
        cover.save(cover_path, "PNG")

        assignments = page_assignments(names)
        set_job(job_id, assignments=assignments)
        for i, assignment in enumerate(assignments, start=1):
            pct = 8 + int((i - 1) / 8 * 78)
            actors = [names[x] for x in assignment["indices"]]
            set_job(job_id, progress=pct, message=f"Generating coloring page {i} of 8 — {', '.join(actors)}…")
            selected_refs = [refs[x] for x in assignment["indices"]]
            img = openai_edit(selected_refs, interior_prompt(names, job["theme"], i, assignment), "low")
            img.save(job_dir / f"page_{i}.png", "PNG", optimize=True)

        set_job(job_id, progress=90, message="Building print-ready PDF…")
        pdf = build_pdf(job_dir, job["title"])
        set_job(job_id, status="done", progress=100, message="Book ready for review.", pdf=str(pdf))
    except Exception as exc:
        set_job(job_id, status="error", progress=0, message="Generation stopped.", error=str(exc))


def generate_demo_job(job_id: str):
    job = get_job(job_id)
    job_dir = Path(job["job_dir"])
    try:
        set_job(job_id, status="working", progress=10, message="Loading pre-generated demo artwork — no API calls…")
        shutil.copy2(DEMO_ASSETS / "cover.png", job_dir / "cover.png")
        for i, filename in enumerate(DEMO_INTERIORS, start=1):
            shutil.copy2(DEMO_ASSETS / filename, job_dir / f"page_{i}.png")
            set_job(job_id, progress=10 + i * 9, message=f"Preparing demo page {i} of 8…")
            time.sleep(0.08)
        pdf = build_pdf(job_dir, job["title"])
        set_job(job_id, status="done", progress=100, message="Demo book ready. No API credit used.", pdf=str(pdf))
    except Exception as exc:
        set_job(job_id, status="error", progress=0, message="Demo failed.", error=str(exc))


def randomized_creative_direction(theme: str, names: list[str]) -> str:
    who = names[0] if len(names) == 1 else " and ".join(names)
    return (
        f"Create a completely new visual approach for {who} within the theme '{theme}'. "
        f"{random.choice(COVER_COMPOSITIONS)} The overall mood should be {random.choice(MOODS)}. "
        f"Across the interior artwork, {random.choice(VIEWPOINTS)}. Deliberately choose different expressions, poses, props, "
        "foreground/background arrangements, and scene compositions from any previous attempt."
    )


def manual_prompt_1(names: list[str], title: str, theme: str, direction: str) -> str:
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
Theme: {theme}

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

ARTWORK TO CREATE

Create exactly:
- 1 standalone full-color cover
- 20 standalone black-and-white coloring-book illustrations

These are artwork assets only. DO NOT create the PDF yet. I will review the artwork first.

COVER

Create one full-color cover featuring all listed characters together in an original scene appropriate to the theme.

The cover must contain the exact title:
\"{title}\"

Keep every person recognizable from their own uploaded original photograph. Use a distinctive composition appropriate to the Creative Direction above.

20 COLORING PAGES

Create 20 different scenes related to the theme: {theme}

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

Every interior image must have:
- black-and-white line art only
- pure white background
- bold, clean outlines
- large areas suitable for coloring
- relatively simple forms
- minimal tiny detail
- no grayscale shading
- no colored elements
- no captions
- no story text
- no page numbers

PAGE COMPOSITION

Compose every cover and coloring page vertically for a US Letter portrait page with an 8.5:11 aspect ratio. Keep important artwork away from the extreme edges so it can later be placed safely onto an 8.5 × 11 inch print page without cropping the subject.

COPYRIGHT SAFETY

Use only original, generic imagery appropriate to the theme. Do not include copyrighted characters, recognizable franchise designs, logos, branded costumes, professional team logos, trademarked mascot designs, or direct recreations of copyrighted artwork.

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
        "auto_pages": 8,
        "auto_pdf_pages": 12,
        "manual_pdf_pages": 24,
    }


@app.post("/api/manual-prompts")
async def make_manual_prompts(request: Request):
    body = await request.json()
    names = [str(x).strip() for x in body.get("names", []) if str(x).strip()]
    title = str(body.get("title", "")).strip()
    theme = str(body.get("theme", "")).strip()
    if not names or not title or not theme:
        raise HTTPException(400, "Names, title, and theme are required.")
    direction = randomized_creative_direction(theme, names)
    return {"prompt1": manual_prompt_1(names, title, theme, direction), "prompt2": manual_prompt_2(), "creative_direction": direction}


@app.post("/api/jobs")
async def create_job(
    mode: str = Form("demo"),
    title: str = Form(...),
    theme: str = Form(...),
    character_names: list[str] = Form(...),
    photos: list[UploadFile] = File(...),
):
    cleanup_old_jobs()
    title = title.strip()
    theme = theme.strip()
    names = [n.strip() for n in character_names if n.strip()]
    if not title or not theme:
        raise HTTPException(400, "Book title and theme are required.")
    if not 1 <= len(names) <= 4:
        raise HTTPException(400, "Add between 1 and 4 people.")
    if len(names) != len(photos):
        raise HTTPException(400, "Every person needs exactly one photo.")
    if mode == "real" and not OPENAI_API_KEY:
        raise HTTPException(400, "Real generation is not available until OPENAI_API_KEY is configured.")
    if mode not in {"demo", "real"}:
        raise HTTPException(400, "Invalid generation mode.")

    job_id = uuid.uuid4().hex[:12]
    job_dir = JOBS_DIR / job_id
    job_dir.mkdir(parents=True)
    refs = []
    try:
        for i, upload in enumerate(photos, start=1):
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
        "message": "Starting…",
        "mode": mode,
        "title": title,
        "theme": theme,
        "names": names,
        "reference_paths": refs,
        "job_dir": str(job_dir),
        "pdf": None,
        "assignments": page_assignments(names),
    }
    target = generate_demo_job if mode == "demo" else generate_real_job
    threading.Thread(target=target, args=(job_id,), daemon=True).start()
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
    }
    if job["status"] == "done":
        payload["download"] = f"/api/jobs/{job_id}/download"
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
    path = Path(job["job_dir"]) / ("cover.png" if page == "cover" else f"page_{int(page)}.png")
    if not path.exists():
        raise HTTPException(404, "Image not ready.")
    return FileResponse(path, media_type="image/png", headers={"Cache-Control": "no-store"})


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
    if not 1 <= page_num <= 8:
        raise HTTPException(400, "Page must be between 1 and 8.")
    if job.get("status") not in {"done", "error"}:
        raise HTTPException(409, "Wait until generation finishes before retrying a page.")
    if job["mode"] == "demo":
        # Free simulation: rotate to another pre-generated sample image.
        src = DEMO_ASSETS / DEMO_INTERIORS[(page_num + 2) % len(DEMO_INTERIORS)]
        shutil.copy2(src, Path(job["job_dir"]) / f"page_{page_num}.png")
        pdf = build_pdf(Path(job["job_dir"]), job["title"])
        set_job(job_id, status="done", progress=100, message=f"Demo retry simulated for page {page_num}. No API credit used.", pdf=str(pdf))
        return {"ok": True, "message": "Demo retry simulated — no API call."}

    if not OPENAI_API_KEY:
        raise HTTPException(400, "OPENAI_API_KEY is not configured.")

    assignment = job["assignments"][page_num - 1]
    refs = [Path(p) for p in job["reference_paths"]]
    selected_refs = [refs[x] for x in assignment["indices"]]
    try:
        img = openai_edit(selected_refs, interior_prompt(job["names"], job["theme"], page_num, assignment), "medium")
        img.save(Path(job["job_dir"]) / f"page_{page_num}.png", "PNG", optimize=True)
        pdf = build_pdf(Path(job["job_dir"]), job["title"])
        set_job(job_id, status="done", progress=100, message=f"Page {page_num} regenerated at medium quality.", pdf=str(pdf))
        return {"ok": True, "message": f"Page {page_num} regenerated at medium quality."}
    except Exception as exc:
        raise HTTPException(500, str(exc))
