"""Shared preflight and CLI helpers for the Story 2.2 commands. Never prints credentials."""

import argparse
import sys
from urllib.parse import urlparse

from pymongo import MongoClient
from pymongo.database import Database
from pymongo.errors import ConfigurationError, InvalidURI, OperationFailure, PyMongoError

from building_with_rag.settings import get_settings


class PrerequisiteError(Exception):
    """A missing prerequisite. The message is safe to print (no secrets)."""


def base_parser(description: str) -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=description)
    p.add_argument("--test-db", action="store_true", help="use MONGODB_TEST_DB_NAME")
    return p


def is_atlas(uri: str) -> bool:
    if uri.startswith("mongodb+srv://"):
        return True
    host = urlparse(uri).hostname or ""
    return host.endswith(".mongodb.net")


def preflight(test_db: bool, probe_collection: str | None = None) -> Database:
    """Connect, identify the deployment, and (optionally) check Atlas Search index management."""
    s = get_settings()
    if not s.mongodb_uri:
        raise PrerequisiteError(
            "MONGODB_URI is empty. Copy .env.example to .env and set MONGODB_URI to your "
            "Atlas free-tier (M0) connection string."
        )
    name = s.mongodb_test_db_name if test_db else s.mongodb_db_name
    try:
        client = MongoClient(s.mongodb_uri, serverSelectionTimeoutMS=15000)
    except (InvalidURI, ConfigurationError):
        raise PrerequisiteError(
            "MONGODB_URI is not a valid MongoDB connection string. It must start with "
            "mongodb+srv:// (Atlas), have no surrounding quotes or spaces, and have a "
            "URL-encoded password."
        ) from None
    try:
        info = client.admin.command("buildInfo")
    except PyMongoError as exc:
        raise PrerequisiteError(
            f"MongoDB is unavailable or rejected the credentials ({type(exc).__name__}). Check "
            "MONGODB_URI, the Atlas user and password, and that the Atlas IP access list "
            "allows this machine."
        ) from None
    if not is_atlas(s.mongodb_uri):
        raise PrerequisiteError(
            "MONGODB_URI is not an Atlas deployment. Story 2.2 needs MongoDB Atlas (free M0) for "
            "vectorSearch indexes; no other vector mechanism is used."
        )
    db = client[name]
    capability = ""
    if probe_collection:
        try:
            if probe_collection not in db.list_collection_names():
                db.create_collection(probe_collection)
            list(db[probe_collection].list_search_indexes())
        except OperationFailure as exc:
            raise PrerequisiteError(
                "Atlas Search index management is not available to this user "
                f"(error code {exc.code}). Give the database user a role that can manage "
                "search indexes on this database."
            ) from None
        capability = ", Atlas Search index management available"
    print(f"deployment: Atlas, server {info.get('version', '?')}, database '{name}'{capability}")
    return db


def run(main) -> None:
    try:
        sys.exit(main())
    except PrerequisiteError as exc:
        print(f"PREREQUISITE: {exc}", file=sys.stderr)
        sys.exit(2)
