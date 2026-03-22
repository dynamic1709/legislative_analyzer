import asyncio
import hashlib
import os
import re
import uuid
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Dict, List
from urllib import request as urllib_request
from xml.etree import ElementTree as ET

from .token_utils import normalize_whitespace


class PolicyIngestionService:
    def __init__(self, processor, vector_store, document_registry):
        self.processor = processor
        self.vector_store = vector_store
        self.document_registry = document_registry

        self.poll_interval_seconds = int(os.getenv("POLICY_POLL_INTERVAL_SECONDS", "900"))
        self.max_items_per_cycle = int(os.getenv("POLICY_MAX_ITEMS_PER_CYCLE", "3"))
        self.enabled = os.getenv("ENABLE_POLICY_INGESTION", "true").lower() in {"1", "true", "yes"}
        self.sources = self._load_sources()

        self._task: asyncio.Task | None = None
        self._lock = asyncio.Lock()
        self._status: Dict[str, Any] = {
            "enabled": self.enabled,
            "is_running": False,
            "poll_interval_seconds": self.poll_interval_seconds,
            "source_count": len(self.sources),
            "last_run_at": None,
            "last_success_at": None,
            "last_error": None,
            "last_ingested_count": 0,
            "total_ingested_count": 0,
            "active_sources": [source["name"] for source in self.sources],
        }

    async def start_background_polling(self) -> None:
        if not self.enabled or self._task is not None:
            return

        self._task = asyncio.create_task(self._poll_loop())

    async def stop_background_polling(self) -> None:
        if self._task is None:
            return

        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        finally:
            self._task = None
            self._status["is_running"] = False

    async def trigger_ingestion(self, trigger: str = "manual") -> Dict[str, Any]:
        if not self.enabled:
            return {
                "trigger": trigger,
                "ingested_count": 0,
                "sources_checked": 0,
                "error_count": 0,
                "errors": ["Policy ingestion is disabled."],
                "document_ids": [],
            }

        async with self._lock:
            self._status["is_running"] = True
            self._status["last_run_at"] = datetime.now(timezone.utc).isoformat()

            ingested_documents = []
            errors = []

            for source in self.sources:
                try:
                    feed_items = await asyncio.to_thread(self._fetch_feed_items, source)
                except Exception as exc:  # noqa: PERF203
                    errors.append(f"{source['name']}: {exc}")
                    continue

                for item in feed_items[: self.max_items_per_cycle]:
                    try:
                        ingested = self._ingest_item(source, item, trigger)
                        if ingested:
                            ingested_documents.append(ingested)
                    except Exception as exc:  # noqa: PERF203
                        item_label = item.get("title") or item.get("external_id")
                        errors.append(f"{source['name']} - {item_label}: {exc}")

            if errors:
                self._status["last_error"] = errors[0]
            else:
                self._status["last_error"] = None

            if ingested_documents:
                self._status["last_success_at"] = datetime.now(timezone.utc).isoformat()

            ingested_count = len(ingested_documents)
            self._status["last_ingested_count"] = ingested_count
            self._status["total_ingested_count"] = self._status.get("total_ingested_count", 0) + ingested_count
            self._status["is_running"] = False

            return {
                "trigger": trigger,
                "ingested_count": ingested_count,
                "sources_checked": len(self.sources),
                "error_count": len(errors),
                "errors": errors,
                "document_ids": [document["document_id"] for document in ingested_documents],
            }

    def get_status(self) -> Dict[str, Any]:
        return {
            **self._status,
            "enabled": self.enabled,
            "source_count": len(self.sources),
            "poll_interval_seconds": self.poll_interval_seconds,
        }

    async def _poll_loop(self) -> None:
        while True:
            await self.trigger_ingestion(trigger="scheduled")
            await asyncio.sleep(self.poll_interval_seconds)

    def _load_sources(self) -> List[Dict[str, str]]:
        configured = os.getenv("POLICY_FEED_URLS", "").strip()
        if not configured:
            return [
                {
                    "name": "PRS Legislative Research",
                    "url": "https://prsindia.org/billtrack/feed",
                },
                {
                    "name": "Press Information Bureau",
                    "url": "https://www.pib.gov.in/rss.aspx",
                },
            ]

        sources = []
        for raw_entry in configured.split(";"):
            entry = raw_entry.strip()
            if not entry:
                continue

            if "|" in entry:
                name, url = entry.split("|", 1)
                source_name = name.strip() or "Government Feed"
                source_url = url.strip()
            else:
                source_name = "Government Feed"
                source_url = entry

            if source_url:
                sources.append({"name": source_name, "url": source_url})

        return sources

    def _fetch_feed_items(self, source: Dict[str, str]) -> List[Dict[str, Any]]:
        req = urllib_request.Request(
            source["url"],
            headers={"User-Agent": "ai-legislative-analyzer/1.0"},
            method="GET",
        )
        with urllib_request.urlopen(req, timeout=20) as response:  # noqa: S310
            payload = response.read()

        return self._parse_feed_payload(payload, source)

    def _parse_feed_payload(self, payload: bytes, source: Dict[str, str]) -> List[Dict[str, Any]]:
        xml_text = payload.decode("utf-8", errors="ignore")
        root = ET.fromstring(xml_text)

        items: List[Dict[str, Any]] = []
        rss_items = root.findall(".//item")
        atom_items = root.findall(".//{http://www.w3.org/2005/Atom}entry")

        if rss_items:
            for item in rss_items:
                parsed = self._parse_rss_item(item, source)
                if parsed:
                    items.append(parsed)
        elif atom_items:
            for item in atom_items:
                parsed = self._parse_atom_item(item, source)
                if parsed:
                    items.append(parsed)

        return items

    def _parse_rss_item(self, item, source: Dict[str, str]) -> Dict[str, Any] | None:
        title = self._clean_html(item.findtext("title", default=""))
        summary = self._clean_html(item.findtext("description", default=""))
        link = normalize_whitespace(item.findtext("link", default=""))
        guid = normalize_whitespace(item.findtext("guid", default=""))
        published_raw = normalize_whitespace(item.findtext("pubDate", default=""))

        if not title and not summary:
            return None

        external_id_seed = f"{source['url']}|{guid or link or title}"
        external_id = hashlib.sha1(external_id_seed.encode("utf-8")).hexdigest()
        return {
            "external_id": external_id,
            "title": title or "Policy Update",
            "summary": summary,
            "link": link,
            "published_at": self._normalize_datetime(published_raw),
        }

    def _parse_atom_item(self, item, source: Dict[str, str]) -> Dict[str, Any] | None:
        ns = "{http://www.w3.org/2005/Atom}"
        title = self._clean_html(item.findtext(f"{ns}title", default=""))
        summary = self._clean_html(item.findtext(f"{ns}summary", default=""))
        item_id = normalize_whitespace(item.findtext(f"{ns}id", default=""))
        updated_raw = normalize_whitespace(item.findtext(f"{ns}updated", default=""))

        link = ""
        link_node = item.find(f"{ns}link")
        if link_node is not None:
            link = normalize_whitespace(link_node.attrib.get("href", ""))

        if not title and not summary:
            return None

        external_id_seed = f"{source['url']}|{item_id or link or title}"
        external_id = hashlib.sha1(external_id_seed.encode("utf-8")).hexdigest()
        return {
            "external_id": external_id,
            "title": title or "Policy Update",
            "summary": summary,
            "link": link,
            "published_at": self._normalize_datetime(updated_raw),
        }

    def _ingest_item(self, source: Dict[str, str], item: Dict[str, Any], trigger: str) -> Dict[str, Any] | None:
        existing = self.document_registry.find_by_external_id(item["external_id"])
        if existing:
            return None

        source_text = self._build_source_text(item)
        chunks = self.processor.chunk_by_structure(source_text)
        compressed_payload = self.processor.compress_context(
            chunks,
            filename=item["title"],
        )

        if not compressed_payload["chunks"]:
            return None

        document_id = str(uuid.uuid4())
        self.vector_store.add_to_store(
            compressed_payload["chunks"],
            document_id,
            source["name"],
        )

        document_record = {
            "document_id": document_id,
            "title": item["title"],
            "filename": item.get("link") or source["name"],
            "uploaded_at": datetime.now(timezone.utc).isoformat(),
            "summary_card": compressed_payload["summary_card"],
            "metrics": compressed_payload["metrics"],
            "chunk_count": len(compressed_payload["chunks"]),
            "ingestion_type": "auto-feed",
            "source": {
                "name": source["name"],
                "feed_url": source["url"],
                "item_url": item.get("link"),
                "published_at": item.get("published_at"),
                "external_id": item["external_id"],
                "trigger": trigger,
            },
        }
        self.document_registry.upsert_document(document_record)
        return document_record

    def _build_source_text(self, item: Dict[str, Any]) -> str:
        sections = [
            f"CHAPTER I Policy Update",
            f"1. Title: {item.get('title', 'Policy Update')}",
            f"2. Summary: {item.get('summary', '')}",
        ]
        if item.get("link"):
            sections.append(f"3. Source Link: {item['link']}")
        if item.get("published_at"):
            sections.append(f"4. Published: {item['published_at']}")
        return "\n".join(sections)

    def _clean_html(self, text: str) -> str:
        stripped = re.sub(r"<[^>]+>", " ", text or "")
        return normalize_whitespace(stripped)

    def _normalize_datetime(self, raw_value: str) -> str:
        if not raw_value:
            return datetime.now(timezone.utc).isoformat()

        try:
            parsed = parsedate_to_datetime(raw_value)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc).isoformat()
        except (TypeError, ValueError):
            pass

        try:
            parsed = datetime.fromisoformat(raw_value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc).isoformat()
        except ValueError:
            return datetime.now(timezone.utc).isoformat()