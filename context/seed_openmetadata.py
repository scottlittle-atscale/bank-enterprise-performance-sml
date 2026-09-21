#!/usr/bin/env python3
"""
seed_openmetadata.py
====================

Load the Bank enterprise catalog fixture into a running OpenMetadata
instance via its REST API, so the demo can pull *real* catalog metadata
(not a JSON file) when generating the SML model.

What it creates, in dependency order:

  1. A database service           (type: BigQuery, name from fixture)
  2. A database                   (the fixture "database")
  3. A database schema            (the fixture "schema")
  4. Each table                   (7 dimensions + 4 facts) with typed columns,
                                   table descriptions, and column descriptions
  5. A classification + tags      (Fact, Dimension, Conformed, Snapshot, PII,
                                   Confidential, Measure, semi-additive, ratio,
                                   additive, additive-flow, Dimension-Key, ...)
  6. A glossary + glossary terms  (the 25 curated business terms)
  7. Bindings                     (tags on tables/columns; glossary terms on
                                   columns) via PATCH

It is **idempotent-ish**: it treats "already exists" (409/PUT) as success, so
you can re-run it. Use --wipe to delete the service first for a clean reset.

Auth: reads the JWT from the OM_JWT environment variable. Never pass the token
on the command line (it would leak into shell history / process list).

Usage:
    export OM_JWT='...'
    python3 seed_openmetadata.py --input bank_enterprise_fixture.json
    python3 seed_openmetadata.py --input bank_enterprise_fixture.json --wipe
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Optional

try:
    import requests
except ImportError:
    sys.exit("requests is required: pip install requests --break-system-packages")


# --- BigQuery-ish type -> OpenMetadata column dataType -----------------------
_OM_TYPE = {
    "DATE": "DATE", "DATETIME": "DATETIME", "TIMESTAMP": "TIMESTAMP",
    "INT64": "BIGINT", "INT": "INT", "BIGINT": "BIGINT",
    "NUMERIC": "NUMERIC", "FLOAT64": "DOUBLE", "FLOAT": "FLOAT",
    "STRING": "VARCHAR", "BOOL": "BOOLEAN", "BOOLEAN": "BOOLEAN",
}


def om_type(raw: str) -> str:
    return _OM_TYPE.get(raw.strip().upper(), "VARCHAR")


class OM:
    """Thin OpenMetadata REST client."""

    def __init__(self, base: str, token: str):
        self.base = base.rstrip("/")
        self.s = requests.Session()
        self.s.headers.update({
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        })

    def _url(self, path: str) -> str:
        return f"{self.base}{path}"

    def put(self, path: str, body: dict) -> dict:
        """PUT = create-or-update in OpenMetadata; the idempotent workhorse."""
        r = self.s.put(self._url(path), json=body, timeout=30)
        if r.status_code >= 400:
            raise RuntimeError(f"PUT {path} -> {r.status_code}: {r.text[:400]}")
        return r.json()

    def patch(self, path: str, ops: list[dict]) -> dict:
        r = self.s.patch(
            self._url(path), data=json.dumps(ops),
            headers={"Content-Type": "application/json-patch+json"},
            timeout=30)
        if r.status_code >= 400:
            raise RuntimeError(f"PATCH {path} -> {r.status_code}: {r.text[:400]}")
        return r.json()

    def get(self, path: str) -> Optional[dict]:
        r = self.s.get(self._url(path), timeout=30)
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.json()

    def delete(self, path: str) -> None:
        self.s.delete(self._url(path), timeout=30)


# ---------------------------------------------------------------------------
# Tag taxonomy the fixture uses. Grouped into one classification.
# ---------------------------------------------------------------------------
CLASSIFICATION = "BankGovernance"
TAGS = [
    ("Fact", "Fact table."),
    ("Dimension", "Dimension table."),
    ("Conformed", "Conformed dimension shared across fact tables."),
    ("Snapshot", "Point-in-time snapshot fact."),
    ("Transaction", "Transaction-grain fact."),
    ("Monthly", "Monthly-aggregate fact."),
    ("PII", "Contains personally identifiable information."),
    ("Confidential", "Confidential data class."),
    ("Measure", "Numeric measure column."),
    ("Dimension-Key", "Key column used for joins / dimension anchoring."),
    ("semi-additive", "Semi-additive measure: never sum across time; read as-of snapshot."),
    ("ratio", "Ratio measure: aggregate with average, never sum."),
    ("additive", "Additive measure: safe to sum across all dimensions."),
    ("additive-flow", "Additive period-flow measure."),
]


def ensure_classification_and_tags(om: OM) -> None:
    om.put("/v1/classifications", {
        "name": CLASSIFICATION,
        "description": "Governance, semantics, and additivity tags for the "
                       "Bank enterprise performance model.",
        "mutuallyExclusive": False,
    })
    for name, desc in TAGS:
        om.put("/v1/tags", {
            "name": name,
            "description": desc,
            "classification": CLASSIFICATION,
        })
    print(f"  tags: classification '{CLASSIFICATION}' + {len(TAGS)} tags")


def tag_fqn(tag: str) -> str:
    return f"{CLASSIFICATION}.{tag}"


# ---------------------------------------------------------------------------
# Glossary
# ---------------------------------------------------------------------------
GLOSSARY = "BankBusinessGlossary"


def safe_term_name(name: str) -> str:
    """OpenMetadata glossary-term names reject some punctuation (parentheses,
    slashes). Keep a filesystem/URL-safe name; the original stays as
    displayName. Binding uses this same transform so FQNs line up."""
    out = []
    for ch in name:
        if ch.isalnum() or ch in " -_":
            out.append(ch)
        else:
            out.append(" ")
    # collapse whitespace to single spaces, strip
    return " ".join("".join(out).split())


def ensure_glossary(om: OM, terms: dict[str, str]) -> None:
    om.put("/v1/glossaries", {
        "name": GLOSSARY,
        "displayName": "Bank Business Glossary",
        "description": "Curated business definitions for the Bank enterprise "
                       "performance model.",
    })
    for name, definition in terms.items():
        om.put("/v1/glossaryTerms", {
            "glossary": GLOSSARY,
            "name": safe_term_name(name),
            "displayName": name,
            "description": definition or name,
        })
    print(f"  glossary: '{GLOSSARY}' + {len(terms)} terms")


def glossary_tag_fqn(term: str) -> str:
    safe = safe_term_name(term)
    # OpenMetadata FQNs quote any component containing spaces or dots.
    if " " in safe or "." in safe:
        return f'{GLOSSARY}.{safe}'
    return f"{GLOSSARY}.{safe}"


# ---------------------------------------------------------------------------
# Service / database / schema / tables
# ---------------------------------------------------------------------------

def ensure_service(om: OM, service: str) -> None:
    om.put("/v1/services/databaseServices", {
        "name": service,
        "serviceType": "BigQuery",
        "connection": {"config": {
            "type": "BigQuery",
            # Minimal placeholder connection; we are not ingesting, just
            # registering metadata objects under this service.
            "credentials": {"gcpConfig": {"type": "service_account",
                                          "projectId": service}},
        }},
    })
    print(f"  service: {service} (BigQuery)")


def ensure_database(om: OM, service: str, database: str) -> str:
    om.put("/v1/databases", {
        "name": database,
        "service": service,
    })
    return f"{service}.{database}"


def ensure_schema(om: OM, db_fqn: str, schema: str) -> str:
    om.put("/v1/databaseSchemas", {
        "name": schema,
        "database": db_fqn,
    })
    return f"{db_fqn}.{schema}"


def build_columns(tbl: dict) -> list[dict]:
    cols = []
    for c in tbl["columns"]:
        col: dict[str, Any] = {
            "name": c["name"],
            "dataType": om_type(c["type"]),
        }
        if col["dataType"] == "VARCHAR":
            col["dataLength"] = 256
        if c.get("description"):
            col["description"] = c["description"]
        cols.append(col)
    return cols


def create_table(om: OM, schema_fqn: str, tbl: dict) -> str:
    body = {
        "name": tbl["name"],
        "databaseSchema": schema_fqn,
        "columns": build_columns(tbl),
    }
    if tbl.get("description"):
        body["description"] = tbl["description"]
    om.put("/v1/tables", body)
    return f"{schema_fqn}.{tbl['name']}"


# ---------------------------------------------------------------------------
# Binding tags + glossary terms after tables exist
# ---------------------------------------------------------------------------

def _tag_label(fqn: str, source: str) -> dict:
    return {"tagFQN": fqn, "source": source,
            "labelType": "Manual", "state": "Confirmed"}


def bind_table_tags(om: OM, table_fqn: str, tbl: dict) -> None:
    tags = [_tag_label(tag_fqn(t), "Classification") for t in tbl.get("tags", [])]
    if not tags:
        return
    tbl_obj = om.get(f"/v1/tables/name/{table_fqn}")
    if not tbl_obj:
        return
    om.patch(f"/v1/tables/{tbl_obj['id']}",
             [{"op": "add", "path": "/tags", "value": tags}])


def bind_column_metadata(om: OM, table_fqn: str, tbl: dict) -> int:
    """Attach classification tags + glossary terms to each column via PATCH."""
    tbl_obj = om.get(f"/v1/tables/name/{table_fqn}")
    if not tbl_obj:
        return 0
    # Build the full replacement column list with tags, preserving order.
    existing = {c["name"]: c for c in tbl_obj["columns"]}
    bound = 0
    new_cols = []
    for c in tbl["columns"]:
        oc = dict(existing.get(c["name"], {"name": c["name"]}))
        labels = [_tag_label(tag_fqn(t), "Classification")
                  for t in c.get("tags", [])]
        if c.get("glossary_term"):
            labels.append(_tag_label(glossary_tag_fqn(c["glossary_term"]),
                                     "Glossary"))
        if labels:
            oc["tags"] = labels
            bound += 1
        new_cols.append(oc)
    if bound:
        om.patch(f"/v1/tables/{tbl_obj['id']}",
                 [{"op": "add", "path": "/columns", "value": new_cols}])
    return bound


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Seed OpenMetadata from the Bank fixture.")
    p.add_argument("--input", required=True)
    p.add_argument("--om-url", default="http://localhost:8585/api")
    p.add_argument("--wipe", action="store_true",
                   help="Delete the database service first for a clean reload.")
    args = p.parse_args(argv)

    token = os.environ.get("OM_JWT")
    if not token:
        sys.exit("Set the OM_JWT environment variable with your OpenMetadata token.")

    with open(args.input, "r", encoding="utf-8") as fh:
        fx = json.load(fh)

    service = fx["database"]           # e.g. atscale-sales-demo
    database = fx["schema"]            # we nest the demo dataset as the database
    schema = "public"                 # single schema bucket for the demo
    # NOTE: OpenMetadata's hierarchy is service>database>schema>table. The
    # fixture's BigQuery "dataset" (BANK_DEMO) maps cleanly to an OM database.

    om = OM(args.om_url, token)

    # sanity check auth up front with a cheap call
    ver = om.get("/v1/system/version")
    if ver is None:
        sys.exit("Could not reach OpenMetadata or token rejected. Check OM_JWT and --om-url.")
    print(f"Connected to OpenMetadata {ver.get('version', '?')}")

    if args.wipe:
        print(f"Wiping service '{service}' (recursive)...")
        svc = om.get(f"/v1/services/databaseServices/name/{service}")
        if svc:
            om.delete(f"/v1/services/databaseServices/{svc['id']}"
                      f"?recursive=true&hardDelete=true")

    print("Seeding governance tags...")
    ensure_classification_and_tags(om)

    print("Seeding business glossary...")
    glossary_terms = {g["name"]: g.get("definition", "")
                      for g in fx.get("glossary", [])}
    ensure_glossary(om, glossary_terms)

    print("Seeding service / database / schema...")
    ensure_service(om, service)
    db_fqn = ensure_database(om, service, database)
    schema_fqn = ensure_schema(om, db_fqn, schema)
    print(f"  schema fqn: {schema_fqn}")

    print("Creating tables...")
    table_fqns = {}
    for tbl in fx["tables"]:
        fqn = create_table(om, schema_fqn, tbl)
        table_fqns[tbl["name"]] = fqn
        print(f"  table: {tbl['name']} ({len(tbl['columns'])} cols)")

    print("Binding table tags...")
    for tbl in fx["tables"]:
        bind_table_tags(om, table_fqns[tbl["name"]], tbl)

    print("Binding column tags + glossary terms...")
    total = 0
    for tbl in fx["tables"]:
        total += bind_column_metadata(om, table_fqns[tbl["name"]], tbl)
    print(f"  columns with bound metadata: {total}")

    print("\nDone. Explore at:", args.om_url.replace("/api", ""))
    print(f"  service={service}  database={database}  schema={schema}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
