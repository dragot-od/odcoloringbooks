# Personalized Coloring Book Studio

Three-section proof-of-concept website:

1. **Pure Demo** - four pre-generated sample books (Dinosaurs, Superhero, Pyramids, Petting Zoo). No API calls.
2. **Live Generator** - real OpenAI image generation with age-adaptive detail, scene planning, multiple people, per-page medium retries, and a 12-page PDF.
3. **Manual GPT** - two-prompt workflow for a full 24-page ChatGPT-generated book.

## Render

Build command:

```text
pip install -r requirements.txt
```

Start command:

```text
uvicorn app:app --host 0.0.0.0 --port $PORT
```

Required environment variable for Live Generator:

```text
OPENAI_API_KEY=...
```

Optional:

```text
SITE_PASSWORD=...
IMAGE_MODEL=gpt-image-2
TEXT_MODEL=gpt-4.1-mini
```

If `SITE_PASSWORD` is set, use username `demo` and that password.
