"""Manual connectivity check for the watsonx.ai client wrapper.

Run this after setting WATSONX_API_KEY / WATSONX_PROJECT_ID in a local
`.env` (repo root, see `.env.example`) to confirm both the Granite
embedding model and the instruct model (with its failover model) are
reachable with live credentials, before wiring them into any endpoint.

    cd backend
    python -m scripts.check_watsonx

Not a pytest test on purpose: it makes real, billable watsonx.ai calls, so
it should not run in CI or on every `pytest` invocation. The automated
suite (added Aug 22 per the dev plan) exercises this module against a
mocked watsonx response instead.
"""

import sys

from app.services.watsonx import get_embedding_model, get_instruct_model


def _instruct_model_ids(instruct) -> str:
    """Best-effort description of the primary (+ fallback) model id(s)."""
    primary_id = getattr(instruct, "model_id", None)
    if primary_id:
        return primary_id
    # RunnableWithFallbacks: primary is `.runnable`, fallbacks in `.fallbacks`.
    primary = getattr(instruct, "runnable", None)
    fallbacks = list(getattr(instruct, "fallbacks", []) or [])
    ids = [getattr(primary, "model_id", "unknown")] + [
        getattr(fb, "model_id", "unknown") for fb in fallbacks
    ]
    return " -> ".join(ids) + " (primary -> failover)"


def main() -> int:
    print("Checking watsonx.ai connectivity...")

    print("\n[1/2] Granite embedding model")
    try:
        embeddings = get_embedding_model()
        vector = embeddings.embed_query("The North Star mission console")
        print(f"  OK — {embeddings.model_id}, embedding dimension {len(vector)}")
    except Exception as exc:  # noqa: BLE001 - top-level diagnostic script
        print(f"  FAILED — {exc}")
        return 1

    print("\n[2/2] Instruct model (with failover)")
    try:
        instruct = get_instruct_model()
        response = instruct.invoke(
            "In one short sentence, what is your role as an AI model?"
        )
        reply = getattr(response, "content", response)
        print(f"  OK — {_instruct_model_ids(instruct)}, reply: {reply!r}")
    except Exception as exc:  # noqa: BLE001 - top-level diagnostic script
        print(f"  FAILED — {exc}")
        return 1

    print("\nBoth watsonx.ai clients reached their models successfully.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
