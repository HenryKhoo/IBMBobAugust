"""Mock fixtures for local development without live watsonx/Pinecone credentials.

Populated per endpoint as each one is built (telemetry, crisis, triage,
rationing, ingest, query). Empty for now — only BACKEND_MODE=mock's effect
on /health depends on this module existing.
"""
