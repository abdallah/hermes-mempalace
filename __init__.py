"""MemPalace memory plugin — MemoryProvider interface.

Local-first, no-API-key persistent memory via the MemPalace CLI.
Mines conversation turns into a profile-scoped palace and retrieves
context via semantic search and wake-up summaries.

Requires: mempalace CLI (pip install mempalace).

Palace lives at: $HERMES_HOME/mempalace/palace  (profile-scoped).
Conversation transcripts: $HERMES_HOME/mempalace/conversations/
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

from agent.memory_provider import MemoryProvider
from tools.registry import tool_error

logger = logging.getLogger(__name__)

_SEARCH_TIMEOUT = 15
_MINE_TIMEOUT = 120
_MIN_CONTENT_LEN = 10


def _resolve_mempalace() -> Optional[str]:
    return shutil.which("mempalace")


def _run_mempalace(
    args: List[str],
    *,
    palace: str = "",
    timeout: int = _SEARCH_TIMEOUT,
) -> dict:
    """Run a mempalace CLI command. Returns {success, output} or {success, error}."""
    cli = _resolve_mempalace()
    if not cli:
        return {
            "success": False,
            "error": "mempalace CLI not found. Install: pip install mempalace",
        }

    # --palace is a global option; must come before the subcommand.
    cmd = [cli]
    if palace:
        cmd += ["--palace", palace]
    cmd += args

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout
        )
        stdout = result.stdout.strip()
        stderr = result.stderr.strip()
        if result.returncode == 0:
            return {"success": True, "output": stdout}
        return {
            "success": False,
            "error": stderr or stdout or f"mempalace exited {result.returncode}",
        }
    except subprocess.TimeoutExpired:
        return {"success": False, "error": f"mempalace timed out after {timeout}s"}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ---------------------------------------------------------------------------
# Tool schemas
# ---------------------------------------------------------------------------

_SEARCH_SCHEMA = {
    "name": "mempalace_search",
    "description": (
        "Search MemPalace for relevant past context — conversations, decisions, "
        "project patterns, and knowledge from previous sessions. "
        "No API key required. Use whenever past context would help."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "What to search for."},
            "wing": {
                "type": "string",
                "description": "Limit search to a specific project wing (optional).",
            },
            "results": {
                "type": "integer",
                "description": "Number of results to return (default: 5).",
            },
        },
        "required": ["query"],
    },
}

_WAKE_UP_SCHEMA = {
    "name": "mempalace_wake_up",
    "description": (
        "Retrieve MemPalace wake-up context — a compact (~600-900 token) summary "
        "of L0 persistent facts and L1 recent highlights. "
        "Use at the start of a session to recall standing context."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "wing": {
                "type": "string",
                "description": "Limit wake-up to a specific project wing (optional).",
            },
        },
        "required": [],
    },
}

_STATUS_SCHEMA = {
    "name": "mempalace_status",
    "description": "Show what has been filed in MemPalace — room/wing counts and palace stats.",
    "parameters": {"type": "object", "properties": {}, "required": []},
}


# ---------------------------------------------------------------------------
# MemoryProvider implementation
# ---------------------------------------------------------------------------


class MemPalaceMemoryProvider(MemoryProvider):
    """MemPalace local-first persistent memory via the mempalace CLI."""

    def __init__(self) -> None:
        self._palace_path = ""
        self._session_id = ""
        self._conversations_dir: Optional[Path] = None
        self._session_turns: List[Dict[str, str]] = []
        self._sync_thread: Optional[threading.Thread] = None

    @property
    def name(self) -> str:
        return "mempalace"

    def is_available(self) -> bool:
        """Check if the mempalace CLI is installed. No network calls."""
        return _resolve_mempalace() is not None

    def get_config_schema(self) -> List[Dict[str, Any]]:
        return []  # local-first — no API key or secrets required

    def save_config(self, values: Dict[str, Any], hermes_home: str) -> None:
        pass  # nothing non-secret to persist

    def initialize(self, session_id: str, **kwargs) -> None:
        from hermes_constants import get_hermes_home

        hermes_home = kwargs.get("hermes_home", str(get_hermes_home()))
        palace_root = Path(hermes_home) / "mempalace"
        self._palace_path = str(palace_root / "palace")
        self._conversations_dir = palace_root / "conversations"
        self._session_id = session_id
        self._session_turns = []

        Path(self._palace_path).mkdir(parents=True, exist_ok=True)
        self._conversations_dir.mkdir(parents=True, exist_ok=True)

    def system_prompt_block(self) -> str:
        if not _resolve_mempalace():
            return ""
        return (
            "# MemPalace Memory\n"
            "Local-first persistent memory (no API key required).\n"
            "Use mempalace_search to recall past context, "
            "mempalace_wake_up for session start context, "
            "mempalace_status to see what's filed."
        )

    def prefetch(self, query: str, *, session_id: str = "") -> str:
        """Search the palace synchronously before the first LLM call."""
        if not query or len(query.strip()) < _MIN_CONTENT_LEN:
            return ""
        result = _run_mempalace(
            ["search", query.strip()[:2000]],
            palace=self._palace_path,
            timeout=_SEARCH_TIMEOUT,
        )
        if result["success"] and result.get("output"):
            output = result["output"].strip()
            if output:
                return f"## MemPalace Context\n{output}"
        return ""

    def sync_turn(
        self,
        user_content: str,
        assistant_content: str,
        *,
        session_id: str = "",
        messages: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        """Buffer the conversation turn for later mining (non-blocking)."""
        if not user_content.strip() and not assistant_content.strip():
            return
        self._session_turns.append(
            {
                "user": user_content[:4000],
                "assistant": assistant_content[:4000],
            }
        )

    def on_session_end(self, messages: List[Dict[str, Any]]) -> None:
        """Mine buffered turns into the palace when the session ends."""
        if self._session_turns:
            turns = self._session_turns[:]
            self._session_turns = []
            self._flush_turns_async(turns)

    def shutdown(self) -> None:
        """Flush any remaining buffered turns and wait for background mining."""
        if self._session_turns:
            turns = self._session_turns[:]
            self._session_turns = []
            self._flush_turns_async(turns)
        if self._sync_thread and self._sync_thread.is_alive():
            self._sync_thread.join(timeout=10.0)

    def get_tool_schemas(self) -> List[Dict[str, Any]]:
        return [_SEARCH_SCHEMA, _WAKE_UP_SCHEMA, _STATUS_SCHEMA]

    def handle_tool_call(self, tool_name: str, args: Dict[str, Any], **kwargs) -> str:
        if tool_name == "mempalace_search":
            return self._tool_search(args)
        if tool_name == "mempalace_wake_up":
            return self._tool_wake_up(args)
        if tool_name == "mempalace_status":
            return self._tool_status()
        return tool_error(f"Unknown tool: {tool_name}")

    # -- internal ------------------------------------------------------------

    def _flush_turns_async(self, turns: List[Dict[str, str]]) -> None:
        """Write turns to a markdown file and mine it in a background thread."""
        if self._sync_thread and self._sync_thread.is_alive():
            self._sync_thread.join(timeout=5.0)

        palace = self._palace_path
        conversations_dir = self._conversations_dir
        session_id = self._session_id

        def _mine() -> None:
            try:
                convo_file = conversations_dir / f"{session_id}.md"
                sections = []
                for t in turns:
                    sections.append(
                        f"**User:** {t['user']}\n\n**Assistant:** {t['assistant']}\n\n---"
                    )
                convo_file.write_text("\n\n".join(sections), encoding="utf-8")
                _run_mempalace(
                    ["mine", str(conversations_dir)],
                    palace=palace,
                    timeout=_MINE_TIMEOUT,
                )
            except Exception as e:
                logger.debug("MemPalace sync failed: %s", e)

        self._sync_thread = threading.Thread(
            target=_mine, daemon=True, name="mempalace-sync"
        )
        self._sync_thread.start()

    def _tool_search(self, args: Dict[str, Any]) -> str:
        query = args.get("query", "")
        if not query:
            return tool_error("query is required")

        cmd = ["search", query.strip()[:2000]]
        wing = args.get("wing", "")
        if wing:
            cmd += ["--wing", wing]
        n = args.get("results")
        if n:
            cmd += ["--results", str(int(n))]

        result = _run_mempalace(cmd, palace=self._palace_path, timeout=_SEARCH_TIMEOUT)
        if not result["success"]:
            return tool_error(result.get("error", "Search failed"))
        output = result.get("output", "").strip()
        if not output:
            return json.dumps({"result": "No results found."})
        return json.dumps({"result": output[:8000]})

    def _tool_wake_up(self, args: Dict[str, Any]) -> str:
        cmd = ["wake-up"]
        wing = args.get("wing", "")
        if wing:
            cmd += ["--wing", wing]
        result = _run_mempalace(cmd, palace=self._palace_path, timeout=_SEARCH_TIMEOUT)
        if not result["success"]:
            return tool_error(result.get("error", "Wake-up failed"))
        return json.dumps({"context": result.get("output", "")})

    def _tool_status(self) -> str:
        result = _run_mempalace(
            ["status"], palace=self._palace_path, timeout=15
        )
        if not result["success"]:
            return tool_error(result.get("error", "Status failed"))
        return json.dumps({"status": result.get("output", "")})


# ---------------------------------------------------------------------------
# Plugin entry point
# ---------------------------------------------------------------------------


def register(ctx) -> None:
    """Register MemPalace as a memory provider plugin."""
    ctx.register_memory_provider(MemPalaceMemoryProvider())
