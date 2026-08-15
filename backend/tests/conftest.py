"""Shared test doubles for mocking watsonx.ai without live credentials.

`_FakeDocument`, `_FakeMessage`, and `_FakeInstructModel` were previously
copy-pasted identically into `test_crisis.py`, `test_telemetry.py`,
`test_triage.py`, and `test_rationing.py`. They live here now so every
endpoint test file shares one mock watsonx response shape instead of four
duplicate copies. Each file still defines its own `_FakeVectorStore`
locally: the four endpoints query the store differently (plain
`similarity_search` vs `similarity_search_with_relevance_scores` vs, for
`/triage`, both), so that class isn't a drop-in shared shape the way the
other three are.
"""


class _FakeDocument:
    """Stand-in for a langchain `Document` hit from retrieval."""

    def __init__(self, page_content: str, metadata: dict):
        self.page_content = page_content
        self.metadata = metadata


class _FakeMessage:
    """Stand-in for the `AIMessage` a `ChatWatsonx` runnable's `invoke` returns."""

    def __init__(self, content: str):
        self.content = content


class _FakeInstructModel:
    """Records whether/how it was invoked and returns a fixed message."""

    def __init__(self, content: str):
        self.content = content
        self.invoked_with: list[str] = []

    def invoke(self, prompt):
        self.invoked_with.append(prompt)
        return _FakeMessage(self.content)
