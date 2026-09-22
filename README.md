# Personalized Coloring Book Demo

A temporary corporate-proof-of-concept website for personalized coloring books.

## What it does

### Automatic mode
- Upload 1–4 people, one original photo per person.
- Enter a book title and theme.
- Generates **1 high-quality color cover + 8 low-quality coloring pages** with `gpt-image-2`.
- Multi-person books use an interleaved plan: solo pages and everyone-together pages are spread through the book.
- Any interior page can be retried individually at **medium** quality.
- Builds a **12-page true US Letter PDF** locally: cover, blank, 8 coloring pages, 2 blanks.
- Blank pages and PDF assembly do not use the image API.

### Demo Mode
- Uses packaged pre-generated sample artwork.
- Makes **zero OpenAI API calls**.
- Lets you demonstrate generation, page review, retry behavior, and PDF download without spending credits.

### Manual ChatGPT fallback
- Generates **Prompt 1** for the artwork: 1 cover + 20 separate coloring-page images.
- Fresh redesigns explicitly require a **brand-new ChatGPT conversation** and re-uploading the original source photos only.
- Each new Prompt 1 receives a newly randomized creative direction.
- Generates **Prompt 2** to assemble approved artwork into a **24-page print-ready PDF**: cover, blank, 20 coloring pages, 2 blanks.

## Privacy / storage
Uploaded photos and generated assets are stored only in the local job directory on the server and are automatically eligible for cleanup after `JOB_TTL_HOURS` (default 6 hours). Render's normal ephemeral filesystem behavior also applies. There is no database or user-account system in this demo.

## Deploy on Render

1. Create a new GitHub repository.
2. Upload **the contents of this folder** to the repository (not the containing ZIP itself).
3. In Render, choose **New → Web Service** and connect the GitHub repository.
4. Render can read `render.yaml`, or configure manually:
   - Build command: `pip install -r requirements.txt`
   - Start command: `uvicorn app:app --host 0.0.0.0 --port $PORT`
5. Add the environment variable:
   - `OPENAI_API_KEY` = your OpenAI API key
6. Optional but recommended for a temporary public demo:
   - `SITE_PASSWORD` = a password you choose. The browser will ask for HTTP Basic credentials. Username is always `demo`.
7. Deploy.

**Never commit your API key to GitHub.** Put it only in Render's Environment Variables / Secrets area.

## Run locally

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Put your API key in .env only if you want real generation.
uvicorn app:app --reload
```

Open http://127.0.0.1:8000

## OpenAI configuration

The code uses `gpt-image-2`, the `/v1/images/edits` endpoint, one or more reference images, `1088x1408` output (exact 8.5:11 aspect ratio), and PNG output. The high/low/medium quality settings are intentionally explicit so you can change them later in `app.py` without redesigning the application.

## Cost behavior

Real automatic generation requests:
- Cover: 1 image at `high`
- Interiors: 8 images at `low`
- Retry: only the selected interior page at `medium`

Actual billing also includes input image and prompt tokens. Demo Mode makes no API calls.

## Important demo limitation

This is intentionally a lightweight proof of concept: no accounts, payments, database, permanent gallery, or production-grade queue. If corporate wants to pursue it, those can be added later.
