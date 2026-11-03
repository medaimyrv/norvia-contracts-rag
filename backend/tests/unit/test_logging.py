"""Logs JSON sin datos sensibles [S4]."""

import json
import logging

from app.logging_config import JsonFormatter
from app.observability import tracer
from tests.unit.test_chat import VALID, ScriptedLLM, run, service


def test_json_line_with_extras_and_trace_id() -> None:
    record = logging.makeLogRecord(
        {"msg": "document ingested", "levelname": "INFO", "name": "x", "document_id": "abc"}
    )
    with tracer.start_as_current_span("test"):
        entry = json.loads(JsonFormatter().format(record))
    assert entry["msg"] == "document ingested" and entry["document_id"] == "abc"
    assert len(entry["trace_id"]) == 32


async def test_chat_never_logs_question_or_answer(caplog) -> None:
    caplog.set_level(logging.DEBUG)
    await run(service(ScriptedLLM(VALID)), question="¿Plazo confidencial con Cóndor Andino?")
    formatter = JsonFormatter()
    logged = "\n".join(formatter.format(r) for r in caplog.records)
    assert "confidencial" not in logged
    assert "diez días" not in logged  # texto de la respuesta
