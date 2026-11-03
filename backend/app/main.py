from fastapi import FastAPI

app = FastAPI(title="Norvia RAG")


@app.get("/health/live")
def live() -> dict[str, str]:
    """El proceso responde. La comprobación de BD y Redis vive en /health/ready (T18)."""
    return {"status": "ok"}
