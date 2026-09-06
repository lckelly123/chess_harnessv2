# LangSmith Studio

Studio runs the same node and edge definitions as the match runner. The only
Studio-specific node is `prepare_turn`, which converts a public turn input into
the internal serializable graph state.

## Setup

Run Studio from the host so it can reach LM Studio on localhost. From `backend`:

```powershell
python -m pip install -r requirements-dev.txt
langgraph dev
```

The command reads `backend/langgraph.json`, loads secrets and tracing settings
from the repository-root `.env`, and opens Studio. `LMSTUDIO_STUDIO_BASE_URL`
defaults to `http://127.0.0.1:1234/v1`; it is separate from the Docker backend's
`LMSTUDIO_BASE_URL`.

Set `LANGSMITH_TRACING=true` and provide `LANGSMITH_API_KEY` in `.env` to retain
runs in the configured `LANGSMITH_PROJECT`. A blank `LMSTUDIO_MODEL` selects the
only model loaded in LM Studio; configure an exact ID if multiple models are
loaded.

## Run a turn

Select `agent_player_1` or `baseline` in Studio's Graph mode and submit:

```json
{
  "game_id": "studio-smoke-test",
  "fen": "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
  "pgn": "*",
  "side": "white",
  "ply": 0
}
```

The Agent Server runs separately at `http://127.0.0.1:2024`; it does not replace
the FastAPI server or the React frontend.
