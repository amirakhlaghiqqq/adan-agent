from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    field_validator,
    model_validator,
)


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class QueryRequest(Contract):
    question: str = Field(min_length=1, max_length=8000)
    input_context: list[str] = Field(default_factory=list, max_length=30)

    @field_validator("question")
    @classmethod
    def nonempty(cls, value):
        if not value.strip():
            raise ValueError("Question must not be blank")
        return value.strip()

    @field_validator("input_context")
    @classmethod
    def bound_context(cls, value):
        if sum(map(len, value)) > 20000:
            raise ValueError("Input context exceeds 20000 characters")
        return value


class RoutingDecision(Contract):
    needs_docs: StrictBool
    needs_db: StrictBool


class SearchPlan(Contract):
    queries: list[str] = Field(min_length=1, max_length=3)


class SQLRequest(Contract):
    request: str


class SQLStatement(Contract):
    sql: str
    parameters: dict[str, str | int | float | None] = Field(default_factory=dict)


class Verdict(Contract):
    passed: StrictBool
    feedback: str


class SubmitAnswer(Contract):
    """Submit the supported answer after acquiring evidence and calculating required values."""

    answer: str = Field(min_length=1)
    citation_ids: list[str] = Field(
        description="Exact retrieved chunk_id values; never document/section labels. "
        "Use [] when no document is cited."
    )
    status: Literal["complete", "partial", "insufficient_evidence"]
    missing_information: list[str]


class SearchDocuments(Contract):
    """Search the supplied policy PDFs, including after discovering account details."""

    query: str = Field(min_length=1, max_length=2000)


class QueryDatabase(Contract):
    """Ask for additional raw customer, subscription or incident facts (read-only)."""

    request: str = Field(min_length=1, max_length=2000)


class Calculate(Contract):
    """Perform exact arithmetic or calendar operations; use returned values for calculations."""

    operation: Literal["evaluate", "month_minutes", "date_difference"]
    expression: str | None = None
    year: StrictInt | None = None
    month: StrictInt | None = None
    start_date: str | None = Field(
        None,
        pattern=r"^\d{4}-\d{2}-\d{2}$",
        description="For date_difference: a YYYY-MM-DD calendar date, without a time component.",
    )
    end_date: str | None = Field(
        None,
        pattern=r"^\d{4}-\d{2}-\d{2}$",
        description="For date_difference: a YYYY-MM-DD calendar date, without a time component.",
    )

    @model_validator(mode="after")
    def required_operands(self):
        required = {
            "evaluate": ("expression",),
            "month_minutes": ("year", "month"),
            "date_difference": ("start_date", "end_date"),
        }[self.operation]
        missing = [name for name in required if getattr(self, name) is None]
        if missing:
            raise ValueError(self.operation + " requires " + ", ".join(missing))
        return self


class RunTimings(Contract):
    started_at: str
    finished_at: str
    duration_ms: float


class RunUsage(Contract):
    """Attempt counts and model totals; null means at least one attempt is unreported."""

    model_calls: int
    tool_calls: int
    generator_turns: int
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None
    cost: float | None


class QueryResponse(Contract):
    schema_version: Literal["1.0"]
    mode: Literal["end_to_end"]
    run_id: str
    question: str
    input_context: list[str]
    answer: str
    status: Literal["complete", "partial", "insufficient_evidence", "error"]
    stop_reason: str
    missing_information: list[str]
    citations: list[dict]
    route: dict
    retrieval_calls: list[dict]
    database_calls: list[dict]
    retrieved_document_chunks: list[dict]
    database_results: list[dict]
    calculator_trace: list[dict]
    aggregation_artifacts: list[dict]
    generator_contexts: list[dict]
    tool_calls: list[dict]
    guardrail_history: list[dict]
    execution_trace: list[dict]
    failures: list[dict]
    timings: RunTimings
    usage: RunUsage
    effective_limits: dict
    index_fingerprint: str
