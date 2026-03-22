import os
import time
import tracemalloc
import unittest
import uuid

from services.pdf_processor import LegislativeProcessor
from services.token_utils import estimate_tokens


class CompressionPipelineTests(unittest.TestCase):
    def test_chunk_compression_reduces_prompt_footprint(self):
        processor = LegislativeProcessor()
        sentence = (
            "Every company shall publish a compliance register within 30 days and "
            "is liable to a financial penalty if it fails to do so."
        )
        chapter_body = "\n".join(f"{index}. {sentence}" for index in range(1, 120))
        source_text = f"CHAPTER I Compliance\n{chapter_body}\nCHAPTER II Appeals\n{chapter_body}"

        chunks = processor.chunk_by_structure(source_text)
        payload = processor.compress_context(chunks, max_tokens_per_chunk=80, filename="Long Act Draft.pdf")

        self.assertGreater(payload["metrics"]["original_tokens"], 0)
        self.assertLessEqual(
            payload["metrics"]["compressed_tokens"],
            payload["metrics"]["original_tokens"],
        )
        self.assertLessEqual(payload["metrics"]["max_chunk_tokens"], 80)
        self.assertEqual(payload["metrics"]["compression_method"], "extractive_sentence_ranking")
        self.assertTrue(payload["summary_card"]["key_points"])

    def _build_synthetic_document_exact_tokens(self, target_tokens: int = 150_000) -> tuple[str, str]:
        chapter_header = "CHAPTER I Synthetic Legislative Stress Framework"
        lines = [chapter_header]
        current_tokens = estimate_tokens(chapter_header)

        section_index = 1
        base_terms = [
            "entity",
            "shall",
            "maintain",
            "compliance",
            "register",
            "within",
            "thirty",
            "days",
            "and",
            "report",
            "to",
            "authority",
            "for",
            "audit",
            "review",
            "with",
            "documented",
            "safeguards",
            "for",
            "citizen",
            "rights",
            "and",
            "data",
            "security",
        ]

        while current_tokens < target_tokens:
            remaining = target_tokens - current_tokens

            # If the remainder is very small, append plain filler tokens exactly.
            if remaining <= 6:
                filler_tokens = [f"tail_{section_index}_{index}" for index in range(remaining)]
                filler_line = " ".join(filler_tokens)
                lines.append(filler_line)
                current_tokens += estimate_tokens(filler_line)
                break

            # Keep sections moderately sized while leaving room for section marker tokens.
            desired_word_count = min(140, max(1, remaining - 2))

            while desired_word_count > 0:
                words = [
                    f"{base_terms[index % len(base_terms)]}_{section_index}_{index}"
                    for index in range(desired_word_count)
                ]
                section_line = f"{section_index}. {' '.join(words)}"
                line_tokens = estimate_tokens(section_line)

                if line_tokens <= remaining:
                    lines.append(section_line)
                    current_tokens += line_tokens
                    section_index += 1
                    break

                desired_word_count -= 1
            else:
                filler_tokens = [f"tail_{section_index}_{index}" for index in range(remaining)]
                filler_line = " ".join(filler_tokens)
                lines.append(filler_line)
                current_tokens += estimate_tokens(filler_line)
                break

        synthetic_document = "\n".join(lines)
        self.assertEqual(
            estimate_tokens(synthetic_document),
            target_tokens,
            "Synthetic stress document must be exactly 150,000 tokens.",
        )
        return synthetic_document, chapter_header

    @unittest.skipUnless(
        os.getenv("RUN_STRESS_TESTS") == "1",
        "Set RUN_STRESS_TESTS=1 to run the 150k-token ingestion stress test.",
    )
    def test_ingestion_pipeline_handles_150k_tokens_without_truncation(self):
        target_tokens = 150_000
        processor = LegislativeProcessor()
        from services.vector_store import VectorService

        synthetic_document, chapter_header = self._build_synthetic_document_exact_tokens(target_tokens)
        expected_chunk_tokens = target_tokens - estimate_tokens(chapter_header)

        collection_name = f"stress_ingestion_{uuid.uuid4().hex}"
        document_id = f"stress_doc_{uuid.uuid4().hex}"
        vector_store = VectorService(collection_name=collection_name)

        elapsed_seconds = 0.0
        peak_memory_mb = 0.0
        chunk_count = 0
        compressed_chunk_count = 0
        chunked_tokens = 0
        max_compressed_chunk_tokens = 0
        compressed_metrics = {}

        tracemalloc.start()
        start_time = time.perf_counter()
        try:
            # Full ingestion pipeline under stress volume.
            chunks = processor.chunk_by_structure(synthetic_document)
            chunk_count = len(chunks)
            chunked_tokens = sum(estimate_tokens(chunk["content"]) for chunk in chunks)

            compressed_payload = processor.compress_context(
                chunks,
                max_tokens_per_chunk=500,
                filename="Synthetic_150k_Stress_Test.pdf",
            )
            compressed_metrics = compressed_payload["metrics"]
            compressed_chunks = compressed_payload["chunks"]
            compressed_chunk_count = len(compressed_chunks)

            self.assertTrue(compressed_chunks, "Compression produced no chunks for stress document.")

            max_compressed_chunk_tokens = max(
                estimate_tokens(chunk["content"])
                for chunk in compressed_chunks
            )

            # Vector store indexing stage.
            vector_store.add_to_store(
                compressed_chunks,
                document_id=document_id,
                document_name="Synthetic_150k_Stress_Test.pdf",
            )

            elapsed_seconds = time.perf_counter() - start_time
            _, peak_bytes = tracemalloc.get_traced_memory()
            peak_memory_mb = peak_bytes / (1024 * 1024)
        finally:
            tracemalloc.stop()
            try:
                vector_store.client.delete_collection(vector_store.collection.name)
            except Exception:
                # Best-effort cleanup for stress collections.
                pass

        # Assertions proving >100k token handling and no truncation in chunking stage.
        self.assertEqual(
            chunked_tokens,
            expected_chunk_tokens,
            "chunk_by_structure truncated or dropped tokens unexpectedly.",
        )
        self.assertGreaterEqual(chunked_tokens, 100_000)

        # Safety assertion for chunks that can eventually reach prompt assembly.
        self.assertLessEqual(
            max_compressed_chunk_tokens,
            500,
            "A compressed chunk exceeded the 500-token prompt safety limit.",
        )

        self.assertEqual(
            compressed_metrics.get("original_tokens"),
            expected_chunk_tokens,
            "Compression original token count does not match chunked input tokens.",
        )
        self.assertLessEqual(
            compressed_metrics.get("compressed_tokens", 0),
            compressed_metrics.get("original_tokens", 0),
        )

        print("\n=== 150K TOKEN INGESTION STRESS REPORT ===")
        print(f"Target synthetic tokens: {target_tokens}")
        print(f"Chunked tokens (post chapter split): {chunked_tokens}")
        print(f"Chunk count: {chunk_count}")
        print(f"Compressed chunk count: {compressed_chunk_count}")
        print(f"Compression original tokens: {compressed_metrics.get('original_tokens', 0)}")
        print(f"Compression output tokens: {compressed_metrics.get('compressed_tokens', 0)}")
        print(f"Compression reduction: {compressed_metrics.get('compression_percentage', 0)}%")
        print(f"Max compressed chunk tokens: {max_compressed_chunk_tokens}")
        print(f"Total ingestion time (s): {elapsed_seconds:.3f}")
        print(f"Peak Python memory (MB): {peak_memory_mb:.2f}")
        print("=== END STRESS REPORT ===")


if __name__ == "__main__":
    unittest.main()
