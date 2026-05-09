"""
Correction Memory — Dual-Memory Storage Engine
================================================

SQLite for structured correction records.
ChromaDB for semantic retrieval of similar fixes.

Stores successful fixes, failed fixes, and partial corrections.
Retrieval prioritizes render_success=true, validation_passed=true.

Each entry includes:
  - failure_hash for deduplication / cache lookup
  - code_diff for repair delta storage
  - retrieval_text for ChromaDB embedding (NOT full scripts)
"""

import os
import json
import uuid
import sqlite3
import difflib
import logging
from dataclasses import dataclass, asdict
from typing import List, Optional, Dict, Any
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class CorrectionEntry:
    """A single correction record."""
    id: str = ""
    timestamp: str = ""
    model_used: str = ""
    scene_id: str = ""
    original_script: str = ""
    error_traceback: str = ""
    error_type: str = ""
    failing_line: str = ""
    corrected_script: str = ""
    validation_passed: bool = False
    render_success: bool = False
    retry_count: int = 0
    semantic_notes: str = ""
    fix_summary: str = ""
    retrieval_text: str = ""
    embedding_id: str = ""
    failure_hash: str = ""
    code_diff: str = ""


def generate_code_diff(original: str, corrected: str) -> str:
    """Generate unified diff between original and corrected scripts."""
    if not original or not corrected:
        return ""
    original_lines = original.splitlines(keepends=True)
    corrected_lines = corrected.splitlines(keepends=True)
    diff = difflib.unified_diff(
        original_lines, corrected_lines,
        fromfile="original.py", tofile="corrected.py",
        n=3,
    )
    return "".join(diff)


def generate_retrieval_text(entry: CorrectionEntry) -> str:
    """
    Build the semantic text that gets embedded into ChromaDB.
    Combines error type + traceback summary + failing API + fix explanation.
    NOT the full script — keeps retrieval quality high.
    """
    parts = []

    if entry.error_type:
        parts.append(f"Error: {entry.error_type}")

    # Truncate traceback to last 3 lines (the actual error)
    if entry.error_traceback:
        tb_lines = entry.error_traceback.strip().splitlines()
        summary = "\n".join(tb_lines[-3:]) if len(tb_lines) > 3 else entry.error_traceback
        parts.append(f"Traceback: {summary[:500]}")

    if entry.failing_line:
        parts.append(f"Failing code: {entry.failing_line[:200]}")

    if entry.fix_summary:
        parts.append(f"Fix: {entry.fix_summary}")

    if entry.semantic_notes:
        parts.append(f"Context: {entry.semantic_notes[:200]}")

    return " | ".join(parts)


class CorrectionMemory:
    """
    Dual-memory storage: SQLite (structured) + ChromaDB (semantic).
    
    SQLite stores complete correction records.
    ChromaDB stores embeddings of retrieval_text for similarity search.
    """

    # Retrieval limits
    MAX_RETRIEVAL_RESULTS = 3
    MAX_RETRIEVAL_CHARS = 2000
    SIMILARITY_THRESHOLD = 0.65  # Below this = irrelevant

    def __init__(
        self,
        db_path: str = "data/correction_memory/corrections.db",
        chroma_path: str = "data/correction_memory/chroma",
    ):
        self.db_path = db_path
        self.chroma_path = chroma_path
        self._chroma_collection = None
        self._chroma_client = None

        # Ensure directories exist
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        Path(chroma_path).mkdir(parents=True, exist_ok=True)

        # Initialize SQLite
        self._init_sqlite()

        # Initialize ChromaDB (lazy — first access)
        logger.info(
            f"✅ CorrectionMemory initialized: "
            f"SQLite={db_path}, ChromaDB={chroma_path}"
        )

    def _init_sqlite(self):
        """Create SQLite tables if they don't exist."""
        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS corrections (
                id TEXT PRIMARY KEY,
                timestamp TEXT NOT NULL,
                model_used TEXT NOT NULL,
                scene_id TEXT,
                original_script TEXT NOT NULL,
                error_traceback TEXT NOT NULL,
                error_type TEXT NOT NULL,
                failing_line TEXT,
                corrected_script TEXT,
                validation_passed BOOLEAN DEFAULT 0,
                render_success BOOLEAN DEFAULT 0,
                retry_count INTEGER DEFAULT 0,
                semantic_notes TEXT,
                fix_summary TEXT,
                retrieval_text TEXT,
                embedding_id TEXT,
                failure_hash TEXT,
                code_diff TEXT
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_error_type ON corrections(error_type)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_render_success ON corrections(render_success)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_failure_hash ON corrections(failure_hash)")
        conn.commit()
        conn.close()

    def _get_chroma_collection(self):
        """Lazy-init ChromaDB collection."""
        if self._chroma_collection is not None:
            return self._chroma_collection

        try:
            import chromadb
            self._chroma_client = chromadb.PersistentClient(path=self.chroma_path)
            self._chroma_collection = self._chroma_client.get_or_create_collection(
                name="manim_correction_memory",
                metadata={"hnsw:space": "cosine"},
            )
            logger.info(
                f"✅ ChromaDB collection ready: "
                f"{self._chroma_collection.count()} entries"
            )
        except ImportError:
            logger.warning("⚠️ chromadb not installed — retrieval disabled")
            return None
        except Exception as e:
            logger.warning(f"⚠️ ChromaDB init failed: {e} — retrieval disabled")
            return None

        return self._chroma_collection

    def store_correction(self, entry: CorrectionEntry) -> str:
        """
        Store a correction entry into both SQLite and ChromaDB.
        
        Returns the entry ID.
        """
        from datetime import datetime

        # Generate ID and timestamp if missing
        if not entry.id:
            entry.id = str(uuid.uuid4())
        if not entry.timestamp:
            entry.timestamp = datetime.utcnow().isoformat()

        # Generate code_diff if we have both scripts
        if not entry.code_diff and entry.original_script and entry.corrected_script:
            entry.code_diff = generate_code_diff(
                entry.original_script, entry.corrected_script
            )

        # Generate retrieval_text if missing
        if not entry.retrieval_text:
            entry.retrieval_text = generate_retrieval_text(entry)

        # Store in SQLite
        try:
            conn = sqlite3.connect(self.db_path)
            conn.execute("""
                INSERT OR REPLACE INTO corrections
                (id, timestamp, model_used, scene_id, original_script,
                 error_traceback, error_type, failing_line, corrected_script,
                 validation_passed, render_success, retry_count, semantic_notes,
                 fix_summary, retrieval_text, embedding_id, failure_hash, code_diff)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                entry.id, entry.timestamp, entry.model_used, entry.scene_id,
                entry.original_script, entry.error_traceback, entry.error_type,
                entry.failing_line, entry.corrected_script,
                entry.validation_passed, entry.render_success, entry.retry_count,
                entry.semantic_notes, entry.fix_summary, entry.retrieval_text,
                entry.embedding_id, entry.failure_hash, entry.code_diff,
            ))
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"❌ SQLite store failed: {e}")

        # Store embedding in ChromaDB
        if entry.retrieval_text:
            try:
                collection = self._get_chroma_collection()
                if collection is not None:
                    entry.embedding_id = entry.id
                    collection.upsert(
                        ids=[entry.id],
                        documents=[entry.retrieval_text[:self.MAX_RETRIEVAL_CHARS]],
                        metadatas=[{
                            "error_type": entry.error_type,
                            "render_success": entry.render_success,
                            "validation_passed": entry.validation_passed,
                            "failure_hash": entry.failure_hash or "",
                            "model_used": entry.model_used,
                        }],
                    )
            except Exception as e:
                logger.warning(f"⚠️ ChromaDB store failed: {e}")

        logger.debug(f"📦 Stored correction {entry.id[:8]}... ({entry.error_type})")
        return entry.id

    def retrieve_similar_fixes(
        self,
        error_type: str,
        traceback_summary: str,
        n_results: int = 3,
    ) -> List[CorrectionEntry]:
        """
        Retrieve similar successful fixes from ChromaDB.
        
        Prioritizes: render_success=true, validation_passed=true.
        Max results: 3. Similarity threshold: 0.65.
        """
        n_results = min(n_results, self.MAX_RETRIEVAL_RESULTS)
        collection = self._get_chroma_collection()
        if collection is None or collection.count() == 0:
            return []

        query_text = f"Error: {error_type} | Traceback: {traceback_summary[:500]}"

        try:
            # Primary: successful fixes within same error domain
            results = collection.query(
                query_texts=[query_text],
                n_results=n_results,
                where={
                    "$and": [
                        {"render_success": True},
                        {"error_type": error_type},
                    ]
                },
                include=["documents", "metadatas", "distances"],
            )

            # Fallback: any successful fix if domain-specific search empty
            if not results["ids"][0]:
                results = collection.query(
                    query_texts=[query_text],
                    n_results=n_results,
                    where={"render_success": True},
                    include=["documents", "metadatas", "distances"],
                )

            # Filter by similarity threshold (cosine distance)
            entries = []
            for i, doc_id in enumerate(results["ids"][0]):
                distance = results["distances"][0][i] if results["distances"] else 1.0
                similarity = 1.0 - distance  # cosine: distance 0 = identical

                if similarity < self.SIMILARITY_THRESHOLD:
                    continue

                # Fetch full record from SQLite
                entry = self._fetch_from_sqlite(doc_id)
                if entry:
                    entries.append(entry)

            if entries:
                logger.info(
                    f"🔍 Retrieved {len(entries)} similar fixes "
                    f"for {error_type} (top similarity: {1.0 - results['distances'][0][0]:.2f})"
                )
            else:
                logger.debug(f"🔍 No similar fixes found for {error_type}")

            return entries[:self.MAX_RETRIEVAL_RESULTS]

        except Exception as e:
            logger.warning(f"⚠️ ChromaDB retrieval failed: {e}")
            return []

    def lookup_by_hash(self, failure_hash: str) -> Optional[CorrectionEntry]:
        """
        Fast lookup: check if we've seen this exact failure before
        and have a successful fix for it.
        """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.execute("""
                SELECT * FROM corrections
                WHERE failure_hash = ? AND render_success = 1
                ORDER BY timestamp DESC LIMIT 1
            """, (failure_hash,))
            row = cursor.fetchone()
            conn.close()

            if row:
                entry = self._row_to_entry(row)
                logger.info(
                    f"⚡ Hash cache HIT: {failure_hash[:12]}... "
                    f"(fix from {entry.timestamp})"
                )
                return entry
        except Exception as e:
            logger.warning(f"⚠️ Hash lookup failed: {e}")

        return None

    def _fetch_from_sqlite(self, entry_id: str) -> Optional[CorrectionEntry]:
        """Fetch a full correction record from SQLite by ID."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.execute(
                "SELECT * FROM corrections WHERE id = ?", (entry_id,)
            )
            row = cursor.fetchone()
            conn.close()
            if row:
                return self._row_to_entry(row)
        except Exception as e:
            logger.warning(f"⚠️ SQLite fetch failed: {e}")
        return None

    def _row_to_entry(self, row) -> CorrectionEntry:
        """Convert a SQLite row tuple to CorrectionEntry."""
        return CorrectionEntry(
            id=row[0], timestamp=row[1], model_used=row[2], scene_id=row[3],
            original_script=row[4], error_traceback=row[5], error_type=row[6],
            failing_line=row[7], corrected_script=row[8],
            validation_passed=bool(row[9]), render_success=bool(row[10]),
            retry_count=row[11], semantic_notes=row[12], fix_summary=row[13],
            retrieval_text=row[14], embedding_id=row[15],
            failure_hash=row[16], code_diff=row[17],
        )

    def get_stats(self) -> dict:
        """Get correction memory statistics."""
        try:
            conn = sqlite3.connect(self.db_path)
            total = conn.execute("SELECT COUNT(*) FROM corrections").fetchone()[0]
            successful = conn.execute(
                "SELECT COUNT(*) FROM corrections WHERE render_success = 1"
            ).fetchone()[0]
            by_type = dict(conn.execute(
                "SELECT error_type, COUNT(*) FROM corrections GROUP BY error_type"
            ).fetchall())
            conn.close()

            chroma_count = 0
            collection = self._get_chroma_collection()
            if collection:
                chroma_count = collection.count()

            return {
                "total_corrections": total,
                "successful_fixes": successful,
                "success_rate": successful / max(total, 1),
                "by_error_type": by_type,
                "chroma_embeddings": chroma_count,
            }
        except Exception as e:
            logger.warning(f"⚠️ Stats fetch failed: {e}")
            return {"error": str(e)}
