# Golf Mini App (FastAPI + SQLite)

A minimal golf scoring web app. Create matches, add players, and record scores per hole. Leaderboard sums strokes per player.

## Requirements
- Python 3.10+

## Setup

```bash
cd /workspace
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Open http://localhost:8000 in your browser.

## API
- POST `/api/matches` { name, num_holes }
- GET `/api/matches`
- GET `/api/matches/{match_id}`
- POST `/api/matches/{match_id}/players` { name }
- GET `/api/matches/{match_id}/players`
- POST `/api/matches/{match_id}/scores` { player_id, hole_number, strokes }
- GET `/api/matches/{match_id}/leaderboard`

## Notes
- SQLite DB file: `golf.db` in project root
- Idempotent per-hole scoring: re-posting updates the existing score for that hole

