"""LangGraph 2-stage processing pipeline for SID."""
from __future__ import annotations

import logging
from typing import TypedDict, Optional, List

from langgraph.graph import StateGraph, END

from shared.schemas.models import RawChunk, Stage1Output, Stage2Output, MemoryEntry

logger = logging.getLogger("sid.processing.pipeline")


class PipelineState(TypedDict):
    chunk: RawChunk
    stage1: Optional[Stage1Output]
    context_items: List[dict]   # [{thought_id, text, score}, ...]
    stage2: Optional[Stage2Output]
    entry: Optional[MemoryEntry]


def _route_after_stage1(state: PipelineState) -> str:
    """Skip deep extraction when Stage 1 is too unconfident — saves the deep-model
    pass on noise, filler, or near-empty chunks."""
    from config.settings import get_settings
    threshold = get_settings().stage1_confidence_threshold
    stage1 = state.get("stage1")
    if stage1 is None or stage1.confidence < threshold:
        logger.info(
            "Stage 1 low-confidence (%.2f < %.2f) for chunk %s — skipping Stage 2",
            stage1.confidence if stage1 else 0.0,
            threshold,
            state["chunk"].chunk_id,
        )
        return "assemble"
    return "load_context"


def _build_graph():
    from services.processing.pipeline.nodes.fast_classifier import fast_classify
    from services.processing.pipeline.nodes.context_loader import load_context
    from services.processing.pipeline.nodes.deep_extractor import deep_extract
    from services.processing.pipeline.nodes.assembler import assemble
    from services.processing.pipeline.nodes.writer import write

    g = StateGraph(PipelineState)
    g.add_node("fast_classify", fast_classify)
    g.add_node("load_context", load_context)
    g.add_node("deep_extract", deep_extract)
    g.add_node("assemble", assemble)
    g.add_node("write", write)

    g.set_entry_point("fast_classify")
    g.add_conditional_edges(
        "fast_classify",
        _route_after_stage1,
        {"load_context": "load_context", "assemble": "assemble"},
    )
    g.add_edge("load_context", "deep_extract")
    g.add_edge("deep_extract", "assemble")
    g.add_edge("assemble", "write")
    g.add_edge("write", END)

    return g.compile()


_graph = None


def _get_graph():
    global _graph
    if _graph is None:
        _graph = _build_graph()
    return _graph


async def run_pipeline(chunk: RawChunk) -> Optional[MemoryEntry]:
    state: PipelineState = {
        "chunk": chunk,
        "stage1": None,
        "context_items": [],
        "stage2": None,
        "entry": None,
    }
    logger.info("Pipeline started for chunk %s", chunk.chunk_id)
    result = await _get_graph().ainvoke(state)
    logger.info("Pipeline completed for chunk %s", chunk.chunk_id)
    return result.get("entry")
