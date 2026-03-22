from fastapi import FastAPI, UploadFile, File, HTTPException, Body, Form
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
import asyncio
import os
import sys
from pathlib import Path
import uuid
import tempfile
import json
import time
import collections
import re
import math
import numpy as np
from deep_translator import GoogleTranslator
from langdetect import DetectorFactory, detect
from langdetect.lang_detect_exception import LangDetectException
from datetime import datetime, timezone
from typing import Dict, Any
from statistics import median, quantiles
from dotenv import load_dotenv

# Ensure `backend/services` is importable as top-level `services` regardless of
# the current working directory (e.g., running via `uvicorn backend.main:app`).
_BACKEND_DIR = Path(__file__).resolve().parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

# Import services
from services.pdf_processor import LegislativeProcessor
from services.vector_store import VectorService
from services.ai_engine import AIExplanationEngine
from services.cross_ref import CrossReferenceDetector
from services.document_registry import DocumentRegistry
from services.hallucination_verifier import HallucinationVerifier
from services.information_density import InformationDensityEvaluator
from services.query_benchmark_registry import QueryBenchmarkRegistry
from services.policy_ingestion import PolicyIngestionService

load_dotenv()
DetectorFactory.seed = 0

app = FastAPI(
    title="AI Legislative Analyzer",
    description="Analyze complex Indian legislative documents with token optimization.",
    version="1.0.0"
)

# Initialize Services
processor = LegislativeProcessor()
vector_store = VectorService()
ai_engine = AIExplanationEngine(provider=os.getenv("AI_PROVIDER", "google"))
ref_detector = CrossReferenceDetector()
document_registry = DocumentRegistry()
density_evaluator = InformationDensityEvaluator()
query_benchmark_registry = QueryBenchmarkRegistry()
policy_ingestion = PolicyIngestionService(processor, vector_store, document_registry)
hallucination_verifier = HallucinationVerifier(
    model_name=os.getenv("NLI_MODEL_NAME", "cross-encoder/nli-deberta-v3-base"),
    entailment_threshold=float(os.getenv("NLI_ENTAILMENT_THRESHOLD", "0.4")),
)

# Token Optimization Caching
answer_cache = {}

# Semantic Similarity Caching (rolling window of last 100 queries with embeddings)
semantic_cache = collections.deque(maxlen=100)  # (query_embedding, cache_key, document_id, language_code, response)
embedding_model = vector_store.openai_ef  # Use the same embedding function as vector store
SEMANTIC_SIMILARITY_THRESHOLD = 0.92

# Query Latency Tracking (rolling window of last 100 queries)
query_latencies = collections.deque(maxlen=100)
real_query_latencies = collections.deque(maxlen=1000)
LATENCY_REPORT_PATH = os.path.join(os.path.dirname(__file__), "latency_report.json")
LLM_TIMEOUT_SECONDS = float(os.getenv("LLM_TIMEOUT_SECONDS", "20.0"))
NLI_TIMEOUT_SECONDS = float(os.getenv("NLI_TIMEOUT_SECONDS", "1.5"))

# Citation validation settings
# Defaults are intentionally permissive to avoid returning a non-answer when
# the model misses a citation on a small number of sentences.
CITATION_HARD_BLOCK_THRESHOLD = float(os.getenv("CITATION_HARD_BLOCK_THRESHOLD", "0.2"))
CITATION_RETRY_THRESHOLD = float(os.getenv("CITATION_RETRY_THRESHOLD", "0.6"))
CITATION_BLOCK_MESSAGE = "Could not generate a fully cited answer from the available clauses."
TRUST_SCORE_BLOCK_THRESHOLD = 0.6
INSUFFICIENT_EVIDENCE_MESSAGE = (
    "Insufficient verified evidence found in this bill to answer your question confidently. "
    "Please consult the original document."
)
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")
_CLAUSE_CITATION_RE = re.compile(
    r"\[(?:Section|Article|Chapter|Context)\s+[^\[\]]+\]",
    re.IGNORECASE,
)


def compute_citation_coverage(answer_text: str) -> Dict[str, Any]:
    normalized_text = re.sub(r"\s+", " ", (answer_text or "").strip())
    if not normalized_text:
        return {
            "coverage": 0.0,
            "cited_sentences": 0,
            "total_sentences": 0,
        }

    sentences = [
        sentence.strip()
        for sentence in _SENTENCE_SPLIT_RE.split(normalized_text)
        if sentence.strip()
    ]
    if not sentences:
        sentences = [normalized_text]

    cited_sentences = sum(1 for sentence in sentences if _CLAUSE_CITATION_RE.search(sentence))
    coverage = round(cited_sentences / len(sentences), 4)

    return {
        "coverage": coverage,
        "cited_sentences": cited_sentences,
        "total_sentences": len(sentences),
    }


def sanitize_user_response(payload: Dict[str, Any]) -> Dict[str, Any]:
    sanitized_payload = dict(payload or {})
    sanitized_payload.pop("flagged_sentences", None)
    return sanitized_payload


def normalize_language_code(language_code: str) -> str:
    normalized_code = (language_code or "en").strip().lower().replace("_", "-")
    if not normalized_code:
        return "en"
    if "-" in normalized_code:
        normalized_code = normalized_code.split("-", 1)[0]
    return normalized_code or "en"


def _calculate_p95(latencies: list[float]) -> float:
    if not latencies:
        return 0.0

    sorted_latencies = sorted(latencies)
    p95_index = max(0, min(len(sorted_latencies) - 1, math.ceil(0.95 * len(sorted_latencies)) - 1))
    return round(sorted_latencies[p95_index], 2)


def _write_latency_report_if_ready() -> None:
    sample_count = len(real_query_latencies)
    if sample_count < 10:
        return

    latencies = list(real_query_latencies)
    report_payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sample_count": sample_count,
        "window": f"last {sample_count} real queries",
        "unit": "milliseconds",
        "target_ms": 10000,
        "latency_ms": {
            "p95": _calculate_p95(latencies),
            "min": round(min(latencies), 2),
            "max": round(max(latencies), 2),
            "avg": round(sum(latencies) / sample_count, 2),
        },
    }
    report_payload["under_10s_target"] = report_payload["latency_ms"]["p95"] < 10000

    try:
        with open(LATENCY_REPORT_PATH, "w", encoding="utf-8") as report_file:
            json.dump(report_payload, report_file, indent=2, ensure_ascii=True)
    except OSError:
        # Do not fail request flow if report write fails.
        pass


def record_real_query_latency(elapsed_ms: float) -> None:
    query_latencies.append(elapsed_ms)
    real_query_latencies.append(elapsed_ms)
    _write_latency_report_if_ready()

# Enable CORS for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
async def root():
    return {"message": "Welcome to AI Legislative Analyzer API"}


@app.on_event("startup")
async def startup_event():
    await policy_ingestion.start_background_polling()


@app.on_event("shutdown")
async def shutdown_event():
    await policy_ingestion.stop_background_polling()


@app.get("/documents")
async def list_documents(limit: int = 10):
    return {
        "documents": document_registry.list_documents(limit=limit),
        "stats": document_registry.build_stats(),
    }


@app.get("/documents/{document_id}")
async def get_document(document_id: str):
    document = document_registry.get_document(document_id)
    if not document:
        raise HTTPException(status_code=404, detail="Document not found.")
    return document


@app.get("/ingestion/status")
async def ingestion_status():
    return policy_ingestion.get_status()


@app.post("/ingestion/run")
async def run_ingestion_now():
    result = await policy_ingestion.trigger_ingestion(trigger="manual")
    return {
        "result": result,
        "status": policy_ingestion.get_status(),
    }


@app.get("/benchmarks/information-density")
async def get_information_density_benchmark(limit: int = 20, window: int = 100, document_id: str = None):
    return {
        "summary": query_benchmark_registry.build_benchmark(document_id=document_id, window=window),
        "recent_queries": query_benchmark_registry.list_recent(limit=limit, document_id=document_id),
    }


@app.get("/languages")
async def list_supported_languages():
    return {
        "languages": ai_engine.get_supported_languages(),
    }

@app.post("/upload")
async def upload_document(
    file: UploadFile = File(...),
    user_profile_json: str = Form(default=""),
):
    if not file.filename.endswith('.pdf'):
        raise HTTPException(status_code=400, detail="Only PDF files are supported.")
    
    temp_path = None
    bytes_written = 0

    try:
        file_descriptor, temp_path = tempfile.mkstemp(suffix=".pdf")
        with os.fdopen(file_descriptor, "wb") as temp_file:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                temp_file.write(chunk)
                bytes_written += len(chunk)

        if bytes_written == 0:
            raise HTTPException(status_code=400, detail="Uploaded PDF is empty.")

        document_id = str(uuid.uuid4())

        text = processor.extract_text_from_path(temp_path)
        chunks = processor.chunk_by_structure(text)

        compressed_payload = processor.compress_context(chunks, filename=file.filename)
        compressed_chunks = compressed_payload["chunks"]

        vector_store.add_to_store(compressed_chunks, document_id, file.filename)

        document_record = {
            "document_id": document_id,
            "title": compressed_payload["summary_card"]["title"],
            "filename": file.filename,
            "uploaded_at": datetime.now(timezone.utc).isoformat(),
            "summary_card": compressed_payload["summary_card"],
            "metrics": compressed_payload["metrics"],
            "chunk_count": len(compressed_chunks),
            "upload_size_bytes": bytes_written,
            "ingestion_type": "manual-upload",
        }

        if user_profile_json:
            try:
                parsed_profile = json.loads(user_profile_json)
                document_record["uploaded_for_profile"] = {
                    "profession": parsed_profile.get("profession"),
                    "educationLevel": parsed_profile.get("educationLevel"),
                    "industry": parsed_profile.get("industry"),
                    "region": parsed_profile.get("region"),
                }
            except (json.JSONDecodeError, AttributeError):
                # Ignore malformed profile metadata and continue upload flow.
                pass

        document_registry.upsert_document(document_record)
        
        return {
            "message": "Document processed successfully",
            "document": document_record,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        await file.close()
        if temp_path and os.path.exists(temp_path):
            os.remove(temp_path)

@app.post("/query")
async def query_legislature(
    user_query: str = Body(..., embed=True),
    document_id: str = Body(None, embed=True),
    user_profile: Dict[str, Any] = Body(default=None, embed=True),
    output_language: str = Body(default="en", embed=True),
):
    # ========== START TIMING INSTRUMENTATION ==========
    query_start_time = time.time()
    # ========== END TIMING INSTRUMENTATION ==========
    
    try:
        normalized_query = (user_query or "").strip()
        if not normalized_query:
            raise HTTPException(status_code=400, detail="Query cannot be empty.")

        # Preserve compatibility for older clients sending output_language.
        _ = output_language

        detected_language_code = "en"
        try:
            detected_language_code = normalize_language_code(detect(normalized_query))
        except LangDetectException:
            detected_language_code = "en"
        except Exception:
            detected_language_code = "en"

        language_code = detected_language_code
        output_language_name = (
            ai_engine.get_language_name(language_code)
            if ai_engine.is_supported_language(language_code)
            else language_code
        )

        # Retrieval and LLM generation always run in English.
        query_for_retrieval = normalized_query
        if detected_language_code != "en":
            try:
                translated_query = GoogleTranslator(source="auto", target="en").translate(normalized_query)
                query_for_retrieval = translated_query or normalized_query
            except Exception:
                query_for_retrieval = normalized_query

        def translate_from_english_if_required(text: str) -> str:
            if detected_language_code == "en":
                return text
            try:
                translated_text = GoogleTranslator(source="en", target=detected_language_code).translate(text)
                return translated_text or text
            except Exception:
                return text

        profile_data = user_profile or {}

        active_document = (
            document_registry.get_document(document_id)
            if document_id
            else document_registry.get_latest_document()
        )

        if not active_document:
            # ========== RECORD LATENCY ON EARLY EXIT ==========
            elapsed_ms = (time.time() - query_start_time) * 1000
            query_latencies.append(elapsed_ms)
            # ========== END LATENCY RECORDING ==========
            return {
                "explanation": "Upload a legislative document before asking questions.",
                "cached": False,
            }

        active_document_id = active_document["document_id"]
        profile_signature = json.dumps(profile_data, sort_keys=True, ensure_ascii=True)
        cache_key = (
            f"{active_document_id}:{normalized_query.lower()}:{language_code}:{profile_signature}"
        )
        if cache_key in answer_cache:
            cached_payload = sanitize_user_response(answer_cache[cache_key])
            cached_citation_coverage = float(cached_payload.get("citation_coverage", 0.0) or 0.0)
            if cached_citation_coverage >= CITATION_RETRY_THRESHOLD:
                return {**cached_payload, "cached": True}

            # Drop stale cache entries that do not meet strict citation requirements.
            answer_cache.pop(cache_key, None)

        # ========== SEMANTIC SIMILARITY CACHE CHECK ==========
        query_embedding = (await asyncio.to_thread(embedding_model, [normalized_query]))[0]
        for cached_embedding, cached_key, cached_doc_id, cached_lang in semantic_cache:
            if cached_doc_id != active_document_id or cached_lang != language_code:
                continue
            similarity = np.dot(query_embedding, cached_embedding)
            if similarity >= SEMANTIC_SIMILARITY_THRESHOLD:
                cached_response = answer_cache.get(cached_key)
                if cached_response:
                    cached_payload = sanitize_user_response(cached_response)
                    cached_citation_coverage = float(cached_payload.get("citation_coverage", 0.0) or 0.0)
                    if cached_citation_coverage < CITATION_RETRY_THRESHOLD:
                        answer_cache.pop(cached_key, None)
                        continue

                    return {
                        **cached_payload,
                        "cached": True,
                        "semantic_similarity": round(float(similarity), 4),
                    }
        # ========== END SEMANTIC SIMILARITY CACHE CHECK ==========

        context = await asyncio.to_thread(
            vector_store.hybrid_query,
            query_for_retrieval,
            4,
            active_document_id,
            12,
            12,
            60,
        )
        
        if not context:
            # ========== RECORD LATENCY ON EARLY EXIT ==========
            elapsed_ms = (time.time() - query_start_time) * 1000
            query_latencies.append(elapsed_ms)
            # ========== END LATENCY RECORDING ==========
            return {"explanation": "I couldn't find any relevant sections in the indexed documents for your query."}

        retrieval_compression = await asyncio.to_thread(
            processor.compress_retrieved_chunks_for_prompt,
            context,
            10.0,
        )
        prompt_context = retrieval_compression["chunks"] or context

        fallback_clauses = [
            {
                "chapter": item.get("metadata", {}).get("chapter"),
                "document_name": item.get("metadata", {}).get("document_name"),
                "chunk_index": item.get("metadata", {}).get("chunk_index"),
                "content": item.get("content", ""),
            }
            for item in prompt_context
        ]
        fallback_explanation = "\n\n".join(
            f"[{clause['chapter']}] {clause['content']}" if clause.get("chapter") else clause.get("content", "")
            for clause in fallback_clauses
            if clause.get("content")
        )

        def build_generation_fallback_response(*, reason: str, error_detail: str | None = None) -> Dict[str, Any]:
            translated_notice = translate_from_english_if_required(
                reason
                + (
                    f" ({error_detail})"
                    if error_detail
                    else ""
                )
            )

            return {
                "query": normalized_query,
                "document_id": active_document_id,
                "document_title": active_document.get("title", active_document.get("filename", "")),
                "explanation": translate_from_english_if_required(
                    fallback_explanation or "No compressed clauses available."
                ),
                "output_language": language_code,
                "output_language_name": output_language_name,
                "detected_language": detected_language_code,
                "clauses": fallback_clauses,
                "retrieval_compression": retrieval_compression["metrics"],
                "fallback": True,
                "cached": False,
                "warning": translated_notice,
            }

        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(
                    ai_engine.generate_explanation,
                    query_for_retrieval,
                    prompt_context,
                    document_title=active_document.get("title", active_document.get("filename", "")),
                    user_profile=profile_data,
                ),
                timeout=LLM_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            fallback_response = {
                "query": normalized_query,
                "document_id": active_document_id,
                "document_title": active_document.get("title", active_document.get("filename", "")),
                "explanation": translate_from_english_if_required(
                    fallback_explanation or "No compressed clauses available."
                ),
                "output_language": language_code,
                "output_language_name": output_language_name,
                "detected_language": detected_language_code,
                "clauses": fallback_clauses,
                "retrieval_compression": retrieval_compression["metrics"],
                "fallback": True,
                "cached": False,
                "timeout_seconds": LLM_TIMEOUT_SECONDS,
            }

            elapsed_ms = (time.time() - query_start_time) * 1000
            record_real_query_latency(elapsed_ms)
            fallback_response["latency_ms"] = round(elapsed_ms, 2)
            return sanitize_user_response(fallback_response)
        except Exception as generation_error:
            fallback_response = build_generation_fallback_response(
                reason=(
                    "AI generation is unavailable right now; showing the most relevant clauses instead. "
                    "Check AI_PROVIDER and API key configuration if you want full explanations."
                ),
                error_detail=type(generation_error).__name__,
            )

            elapsed_ms = (time.time() - query_start_time) * 1000
            record_real_query_latency(elapsed_ms)
            fallback_response["latency_ms"] = round(elapsed_ms, 2)
            return sanitize_user_response(fallback_response)

        explanation_english = result["explanation"]

        citation_check = compute_citation_coverage(explanation_english)
        citation_retry_triggered = False

        if citation_check["coverage"] < CITATION_RETRY_THRESHOLD:
            citation_retry_triggered = True
            retry_query = (
                f"{query_for_retrieval}\n\n"
                "CITATION RETRY REQUIRED: The previous answer failed citation coverage requirements. "
                "Rewrite the answer using ONLY the provided context. Every factual sentence MUST end with "
                "a valid [Section X] or [Article X] citation. Omit any claim that cannot be cited."
            )
            try:
                retry_result = await asyncio.wait_for(
                    asyncio.to_thread(
                        ai_engine.generate_explanation,
                        retry_query,
                        prompt_context,
                        document_title=active_document.get("title", active_document.get("filename", "")),
                        user_profile=profile_data,
                    ),
                    timeout=LLM_TIMEOUT_SECONDS,
                )
            except asyncio.TimeoutError:
                fallback_response = {
                    "query": normalized_query,
                    "document_id": active_document_id,
                    "document_title": active_document.get("title", active_document.get("filename", "")),
                    "explanation": translate_from_english_if_required(
                        fallback_explanation or "No compressed clauses available."
                    ),
                    "output_language": language_code,
                    "output_language_name": output_language_name,
                    "detected_language": detected_language_code,
                    "clauses": fallback_clauses,
                    "retrieval_compression": retrieval_compression["metrics"],
                    "fallback": True,
                    "cached": False,
                    "timeout_seconds": LLM_TIMEOUT_SECONDS,
                }

                elapsed_ms = (time.time() - query_start_time) * 1000
                record_real_query_latency(elapsed_ms)
                fallback_response["latency_ms"] = round(elapsed_ms, 2)
                return sanitize_user_response(fallback_response)
            except Exception as retry_generation_error:
                fallback_response = build_generation_fallback_response(
                    reason=(
                        "AI generation is unavailable right now; showing the most relevant clauses instead. "
                        "Check AI_PROVIDER and API key configuration if you want full explanations."
                    ),
                    error_detail=type(retry_generation_error).__name__,
                )

                elapsed_ms = (time.time() - query_start_time) * 1000
                record_real_query_latency(elapsed_ms)
                fallback_response["latency_ms"] = round(elapsed_ms, 2)
                return sanitize_user_response(fallback_response)

            explanation_english = retry_result["explanation"]
            result = retry_result
            citation_check = compute_citation_coverage(explanation_english)

        citation_hard_failure = citation_check["coverage"] < CITATION_HARD_BLOCK_THRESHOLD
        citation_unverified = citation_check["coverage"] < CITATION_RETRY_THRESHOLD
        citation_warning = None

        if citation_unverified:
            if citation_hard_failure:
                fallback_response = build_generation_fallback_response(
                    reason=(
                        "Citations were too incomplete to show a generated explanation; "
                        "showing the most relevant clauses instead."
                    ),
                )
                fallback_response["citation_coverage"] = citation_check["coverage"]
                fallback_response["citation_stats"] = {
                    "cited_sentences": citation_check["cited_sentences"],
                    "total_sentences": citation_check["total_sentences"],
                    "minimum_required": CITATION_RETRY_THRESHOLD,
                    "hard_block_threshold": CITATION_HARD_BLOCK_THRESHOLD,
                    "retry_triggered": citation_retry_triggered,
                    "hard_block_triggered": citation_hard_failure,
                }
                fallback_response["verification_status"] = "fallback_incomplete_citations"

                elapsed_ms = (time.time() - query_start_time) * 1000
                record_real_query_latency(elapsed_ms)
                fallback_response["latency_ms"] = round(elapsed_ms, 2)
                return sanitize_user_response(fallback_response)

            citation_warning = translate_from_english_if_required(
                "Some sentences could not be fully cited. Treat this as a best-effort summary and verify in the source clauses."
            )

        verification: Dict[str, Any] = {}
        verification_status = "verified"
        try:
            verification = await asyncio.wait_for(
                asyncio.to_thread(
                    hallucination_verifier.verify,
                    explanation_english,
                    prompt_context,
                ),
                timeout=NLI_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            verification_status = "verification_skipped_timeout"
            verification = {"trust_score": 1.0, "flagged_sentences": []}
        except Exception:
            verification_status = "verification_skipped_error"
            verification = {"trust_score": 1.0, "flagged_sentences": []}

        trust_score = float(verification.get("trust_score", 0.0) or 0.0)

        if trust_score < TRUST_SCORE_BLOCK_THRESHOLD:
            translated_insufficient_evidence_message = translate_from_english_if_required(INSUFFICIENT_EVIDENCE_MESSAGE)
            blocked_response = {
                "query": normalized_query,
                "document_id": active_document_id,
                "document_title": active_document.get("title", active_document.get("filename", "")),
                "explanation": translated_insufficient_evidence_message,
                "explanation_english": INSUFFICIENT_EVIDENCE_MESSAGE,
                "output_language": language_code,
                "output_language_name": output_language_name,
                "detected_language": detected_language_code,
                "detected_references": [],
                "references": [],
                "citations": [],
                "confidence": 0.0,
                "cached": False,
                "token_metrics": result.get("token_metrics", {}),
                "document_metrics": active_document.get("metrics", {}),
                "retrieval_compression": retrieval_compression["metrics"],
                "trust_score": round(trust_score, 4),
                "citation_coverage": citation_check["coverage"],
                "citation_stats": {
                    "cited_sentences": citation_check["cited_sentences"],
                    "total_sentences": citation_check["total_sentences"],
                    "minimum_required": CITATION_RETRY_THRESHOLD,
                    "hard_block_threshold": CITATION_HARD_BLOCK_THRESHOLD,
                    "retry_triggered": citation_retry_triggered,
                },
                "verification_status": "blocked_insufficient_evidence",
                "warning": translated_insufficient_evidence_message,
            }

            blocked_information_density = density_evaluator.evaluate(
                explanation=INSUFFICIENT_EVIDENCE_MESSAGE,
                token_metrics=blocked_response["token_metrics"],
                detected_references=[],
                citations=[],
            )
            blocked_response["information_density"] = blocked_information_density

            query_benchmark_registry.append_record({
                "document_id": active_document_id,
                "document_title": blocked_response["document_title"],
                "query": normalized_query,
                "confidence": blocked_response["confidence"],
                "cached": False,
                "token_metrics": blocked_response["token_metrics"],
                "information_density": blocked_information_density,
                "verification_status": "blocked_insufficient_evidence",
                "trust_score": blocked_response["trust_score"],
                "citation_coverage": blocked_response["citation_coverage"],
                "retrieved_original_tokens": retrieval_compression["metrics"].get("original_tokens", 0),
                "retrieved_compressed_tokens": retrieval_compression["metrics"].get("compressed_tokens", 0),
                "retrieved_compression_ratio": retrieval_compression["metrics"].get("achieved_ratio", 1.0),
            })

            elapsed_ms = (time.time() - query_start_time) * 1000
            record_real_query_latency(elapsed_ms)
            blocked_response["latency_ms"] = round(elapsed_ms, 2)

            return sanitize_user_response(blocked_response)

        translated_explanation = translate_from_english_if_required(explanation_english)
        
        all_refs = ref_detector.detect_references(explanation_english)
        chapter_references = list(dict.fromkeys(c["metadata"]["chapter"] for c in prompt_context))
        
        response_data = {
            "query": normalized_query,
            "document_id": active_document_id,
            "document_title": active_document.get("title", active_document.get("filename", "")),
            "explanation": translated_explanation,
            "explanation_english": explanation_english,
            "output_language": language_code,
            "output_language_name": output_language_name,
            "detected_language": detected_language_code,
            "detected_references": all_refs,
            "references": chapter_references,
            "citations": [
                {
                    "chapter": item["metadata"].get("chapter"),
                    "document_name": item["metadata"].get("document_name"),
                    "chunk_index": item["metadata"].get("chunk_index"),
                    "preview": item["content"],
                    "distance": item.get("distance", 0),
                }
                for item in prompt_context
            ],
            "confidence": 1.0 - (context[0]["distance"] if context[0].get("distance") else 0),
            "cached": False,
            "token_metrics": result.get("token_metrics", {}),
            "document_metrics": active_document.get("metrics", {}),
            "retrieval_compression": retrieval_compression["metrics"],
            "trust_score": round(trust_score, 4),
            "citation_coverage": citation_check["coverage"],
            "citation_warning": bool(citation_warning),
            "citation_stats": {
                "cited_sentences": citation_check["cited_sentences"],
                "total_sentences": citation_check["total_sentences"],
                "minimum_required": CITATION_RETRY_THRESHOLD,
                "hard_block_threshold": CITATION_HARD_BLOCK_THRESHOLD,
                "retry_triggered": citation_retry_triggered,
            },
            "verification_status": verification_status,
        }

        if citation_warning:
            response_data["warning"] = citation_warning

        information_density = density_evaluator.evaluate(
            explanation=explanation_english,
            token_metrics=response_data["token_metrics"],
            detected_references=all_refs,
            citations=response_data["citations"],
        )
        response_data["information_density"] = information_density

        query_benchmark_registry.append_record({
            "document_id": active_document_id,
            "document_title": response_data["document_title"],
            "query": normalized_query,
            "confidence": response_data["confidence"],
            "cached": False,
            "token_metrics": response_data["token_metrics"],
            "information_density": information_density,
            "retrieved_original_tokens": retrieval_compression["metrics"].get("original_tokens", 0),
            "retrieved_compressed_tokens": retrieval_compression["metrics"].get("compressed_tokens", 0),
            "retrieved_compression_ratio": retrieval_compression["metrics"].get("achieved_ratio", 1.0),
        })

        response_data = sanitize_user_response(response_data)
        answer_cache[cache_key] = response_data
        
        # ========== SEMANTIC SIMILARITY CACHE WRITE ==========
        semantic_cache.append((
            query_embedding,
            cache_key,
            active_document_id,
            language_code,
        ))
        # ========== END SEMANTIC SIMILARITY CACHE WRITE ==========
        
        # ========== RECORD LATENCY ON SUCCESSFUL COMPLETION ==========
        elapsed_ms = (time.time() - query_start_time) * 1000
        record_real_query_latency(elapsed_ms)
        response_data["latency_ms"] = round(elapsed_ms, 2)
        # ========== END LATENCY RECORDING ==========
        
        return response_data
    except HTTPException:
        raise
    except Exception as e:
        # ========== RECORD LATENCY ON ERROR ==========
        elapsed_ms = (time.time() - query_start_time) * 1000
        query_latencies.append(elapsed_ms)
        # ========== END LATENCY RECORDING ==========
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/translate")
async def translate_output_text(
    text: str = Body(..., embed=True),
    target_language: str = Body(default="en", embed=True),
    source_language: str = Body(default="en", embed=True),
):
    if not (text or "").strip():
        raise HTTPException(status_code=400, detail="Text cannot be empty.")

    language_code = (target_language or "en").strip().lower()
    if not ai_engine.is_supported_language(language_code):
        raise HTTPException(status_code=400, detail=f"Unsupported target language: {language_code}")

    translated_text = text
    if language_code != "en":
        try:
            translated_text = GoogleTranslator(
                source=(source_language or "auto"),
                target=language_code,
            ).translate(text)
        except Exception:
            translated_text = text

    return {
        "translated_text": translated_text,
        "target_language": language_code,
        "target_language_name": ai_engine.get_language_name(language_code),
        "source_language": source_language,
    }

@app.get("/health")
async def health_check():
    return {"status": "healthy"}


# ========== LATENCY METRICS ENDPOINT ==========
@app.get("/metrics/latency")
async def get_latency_metrics():
    """
    Returns latency statistics for the last 100 queries.
    Metrics include: p50, p95, p99, max, and min latency in milliseconds.
    """
    if not query_latencies:
        return {
            "message": "No query latency data available yet.",
            "sample_count": 0,
            "metrics": None,
        }
    
    latencies_list = sorted(list(query_latencies))
    sample_count = len(latencies_list)
    
    metrics = {
        "p50": round(median(latencies_list), 2),
        "p95": round(quantiles(latencies_list, n=20)[18], 2) if sample_count >= 20 else round(max(latencies_list), 2),
        "p99": round(quantiles(latencies_list, n=100)[98], 2) if sample_count >= 100 else round(max(latencies_list), 2),
        "max": round(max(latencies_list), 2),
        "min": round(min(latencies_list), 2),
    }
    
    return {
        "sample_count": sample_count,
        "unit": "milliseconds",
        "metrics": metrics,
        "window": "last 100 queries",
    }
# ========== END LATENCY METRICS ENDPOINT ==========

if __name__ == "__main__":
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=int(os.getenv("PORT", "8000")),
        reload=False,
    )
