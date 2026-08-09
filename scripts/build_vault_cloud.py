#!/usr/bin/env python3
"""Retired compatibility shim.

The PlugICT vault already contains the canonical semantic-v3.0.0 chunks and
Chroma vectors. Do not re-chunk or re-embed it. Use:

    scripts/export_existing_vault.py --stage verify
    scripts/export_existing_vault.py --stage export
    scripts/export_existing_vault.py --stage upload

This file intentionally fails closed so the obsolete generic 900-character
re-embedding pipeline cannot be run by accident.
"""

raise SystemExit(
    "build_vault_cloud.py is retired; use scripts/export_existing_vault.py "
    "to migrate the existing vault index without re-embedding."
)
