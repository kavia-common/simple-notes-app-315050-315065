"""notes_backend FastAPI application.

Provides a simple REST API for a Notes app (no authentication):
- List notes
- Create a note
- Get a note by id
- Update a note
- Delete a note

Data is stored in a local SQLite database file from the notes_database container.
"""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime
from typing import List, Optional

from fastapi import FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# --- App metadata / tags for docs ---
openapi_tags = [
    {
        "name": "Health",
        "description": "Health and status endpoints.",
    },
    {
        "name": "Notes",
        "description": "CRUD operations for notes.",
    },
]


def _default_sqlite_path() -> str:
    """Return the default SQLite DB path used by the notes_database container."""
    # NOTE: This is the known location in this mono-workspace template.
    # If you move containers, set NOTES_DB_PATH env var accordingly.
    return "/home/kavia/workspace/code-generation/simple-notes-app-315050-315064/notes_database/myapp.db"


DB_PATH = os.getenv("NOTES_DB_PATH", _default_sqlite_path())


def _get_conn() -> sqlite3.Connection:
    """Create a SQLite connection with safe defaults."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _init_schema() -> None:
    """Ensure the notes table exists (idempotent)."""
    conn = _get_conn()
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_notes_updated_at
            ON notes(updated_at)
        """
        )
        conn.commit()
    finally:
        conn.close()


app = FastAPI(
    title="Simple Notes API",
    description="Backend API for a simple notes app (title + content). No authentication required.",
    version="0.1.0",
    openapi_tags=openapi_tags,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Template default; tighten in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def _startup() -> None:
    """Initialize required DB schema on startup."""
    _init_schema()


class Note(BaseModel):
    """A note as returned by the API."""

    id: int = Field(..., description="Unique note identifier.")
    title: str = Field(..., description="Note title.")
    content: str = Field(..., description="Note content/body.")
    created_at: str = Field(..., description="ISO timestamp when note was created.")
    updated_at: str = Field(..., description="ISO timestamp when note was last updated.")


class NoteCreate(BaseModel):
    """Payload to create a note."""

    title: str = Field(..., min_length=1, max_length=200, description="Note title.")
    content: str = Field(..., min_length=1, description="Note content/body.")


class NoteUpdate(BaseModel):
    """Payload to update a note (full update)."""

    title: str = Field(..., min_length=1, max_length=200, description="Note title.")
    content: str = Field(..., min_length=1, description="Note content/body.")


def _row_to_note(row: sqlite3.Row) -> Note:
    """Convert a SQLite row to a Note model."""
    return Note(
        id=int(row["id"]),
        title=str(row["title"]),
        content=str(row["content"]),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )


@app.get(
    "/",
    tags=["Health"],
    summary="Health check",
    description="Simple health endpoint to verify the service is running.",
    operation_id="health_check",
)
def health_check():
    """Health check.

    Returns:
        JSON object with a human-readable message.
    """
    return {"message": "Healthy"}


# PUBLIC_INTERFACE
@app.get(
    "/notes",
    response_model=List[Note],
    tags=["Notes"],
    summary="List notes",
    description="Returns all notes ordered by most recently updated first.",
    operation_id="list_notes",
)
def list_notes() -> List[Note]:
    """List all notes.

    Returns:
        List[Note]: All notes in descending updated_at order.
    """
    conn = _get_conn()
    try:
        rows = conn.execute(
            """
            SELECT id, title, content, created_at, updated_at
            FROM notes
            ORDER BY datetime(updated_at) DESC, id DESC
        """
        ).fetchall()
        return [_row_to_note(r) for r in rows]
    finally:
        conn.close()


# PUBLIC_INTERFACE
@app.post(
    "/notes",
    response_model=Note,
    status_code=201,
    tags=["Notes"],
    summary="Create note",
    description="Creates a new note with title and content.",
    operation_id="create_note",
)
def create_note(payload: NoteCreate) -> Note:
    """Create a note.

    Args:
        payload: NoteCreate payload with title and content.

    Returns:
        Note: Newly created note.
    """
    now = datetime.utcnow().isoformat(timespec="seconds") + "Z"
    conn = _get_conn()
    try:
        cur = conn.execute(
            """
            INSERT INTO notes (title, content, created_at, updated_at)
            VALUES (?, ?, ?, ?)
        """,
            (payload.title.strip(), payload.content, now, now),
        )
        conn.commit()

        row = conn.execute(
            """
            SELECT id, title, content, created_at, updated_at
            FROM notes
            WHERE id = ?
        """,
            (cur.lastrowid,),
        ).fetchone()
        return _row_to_note(row)
    finally:
        conn.close()


# PUBLIC_INTERFACE
@app.get(
    "/notes/{note_id}",
    response_model=Note,
    tags=["Notes"],
    summary="Get note",
    description="Fetch a single note by its id.",
    operation_id="get_note",
)
def get_note(note_id: int) -> Note:
    """Get a note by id.

    Args:
        note_id: Note identifier.

    Returns:
        Note: The note.

    Raises:
        HTTPException: 404 if note does not exist.
    """
    conn = _get_conn()
    try:
        row = conn.execute(
            """
            SELECT id, title, content, created_at, updated_at
            FROM notes
            WHERE id = ?
        """,
            (note_id,),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Note not found")
        return _row_to_note(row)
    finally:
        conn.close()


# PUBLIC_INTERFACE
@app.put(
    "/notes/{note_id}",
    response_model=Note,
    tags=["Notes"],
    summary="Update note",
    description="Updates title and content of an existing note (full update).",
    operation_id="update_note",
)
def update_note(note_id: int, payload: NoteUpdate) -> Note:
    """Update a note by id.

    Args:
        note_id: Note identifier.
        payload: New title + content.

    Returns:
        Note: Updated note.

    Raises:
        HTTPException: 404 if note does not exist.
    """
    now = datetime.utcnow().isoformat(timespec="seconds") + "Z"
    conn = _get_conn()
    try:
        cur = conn.execute(
            """
            UPDATE notes
            SET title = ?, content = ?, updated_at = ?
            WHERE id = ?
        """,
            (payload.title.strip(), payload.content, now, note_id),
        )
        conn.commit()
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Note not found")

        row = conn.execute(
            """
            SELECT id, title, content, created_at, updated_at
            FROM notes
            WHERE id = ?
        """,
            (note_id,),
        ).fetchone()
        return _row_to_note(row)
    finally:
        conn.close()


# PUBLIC_INTERFACE
@app.delete(
    "/notes/{note_id}",
    status_code=204,
    tags=["Notes"],
    summary="Delete note",
    description="Deletes a note by id.",
    operation_id="delete_note",
)
def delete_note(note_id: int) -> Response:
    """Delete a note by id.

    Args:
        note_id: Note identifier.

    Returns:
        204 No Content on success.

    Raises:
        HTTPException: 404 if note does not exist.
    """
    conn = _get_conn()
    try:
        cur = conn.execute("DELETE FROM notes WHERE id = ?", (note_id,))
        conn.commit()
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Note not found")
        return Response(status_code=204)
    finally:
        conn.close()
