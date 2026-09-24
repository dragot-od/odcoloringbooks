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


## v9 Book DNA uniqueness
Each live generation now receives a hidden randomized creative fingerprint that changes story structure, opening situation, activity emphasis, recurring motif, pacing, supporting-character dynamics, ending, cover composition, and page-by-page action/composition/energy recipes. The Manual GPT Prompt 1 includes its own 20-page Book DNA each time prompts are generated.


## v9.1 update
- Added a Random Idea Helper under the Live Generator.
- Optional inputs: name, target age, and subject.
- Works even if some or all helper fields are blank.
- Auto-fills the live title, target age, Detailed Description, and first character name.
- Manual GPT prompt section now explicitly uses fields filled by the Random Idea Helper.

## v9.2 update
- Added a Tone selector to the Random Idea Helper.
- Choices: Surprise Me, Funny, Adventurous, Cute & Gentle, Educational, Magical, Mysterious, Calm & Cozy, and Action-Packed.
- Surprise Me chooses a new tone automatically.
- The selected tone is woven directly into the generated Detailed Description, so it also carries into the Manual GPT prompt workflow.


## v9.3 update
- Moved the Random Idea Helper below the normal Live Generator fields.
- Simplified helper labels to Name (optional), Target age (optional), Subject (optional), and Tone (optional).
- Blank-field behavior is explained once in the helper instructions instead of repeated in field labels.


## v9.4 update
- Live Generator now begins with People (name + photo) before title, age, and description.
- Optional Idea Generator visually separated in its own highlighted panel.
- Idea Generator mirrors the number of people added to the main form with one optional name field per person.
- Blank helper names are randomized individually; entered names are preserved.
- Multi-person random ideas combine all names naturally in the generated title and description.
- Subject, age, and tone can still be supplied or left blank for randomization.
- Manual GPT prompts continue to use the final live fields, including all generated character names.

## v9.5 update
- Live Generator now starts with exactly one person by default.
- Additional people are added only with + Add Another Person.
- Added a small Clear Fields button beside Generate Random Idea.
- Clear Fields resets only the Idea Generator helper values (names, target age, subject, and tone) so the next random generation can be a fresh roll without disturbing the main live form or uploaded photos.
