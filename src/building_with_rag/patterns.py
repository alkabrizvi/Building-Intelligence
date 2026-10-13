from building_with_rag.contracts import QueryRequest, QueryResult


def run_pattern(request: QueryRequest) -> QueryResult:
    """Single entry point for every mode. All modes are placeholders for now."""
    return QueryResult(
        pattern=request.pattern,
        status="not_implemented",
        message=f"The '{request.pattern}' mode is not implemented yet.",
        trace={"caller_id": request.caller_id},
    )
