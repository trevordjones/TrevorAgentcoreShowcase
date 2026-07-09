import sqlglot
from strands import tool


@tool
def validate_sql(sql: str, dialect: str = "") -> dict:
    """Validate SQL syntax. Returns a dict with 'valid' (bool) and 'errors' (list of strings)."""
    try:
        sqlglot.parse(sql, dialect=dialect or None, error_level=sqlglot.ErrorLevel.RAISE)
        return {"valid": True, "errors": []}
    except sqlglot.errors.SqlglotError as e:
        return {"valid": False, "errors": [str(e)]}


@tool
def format_sql(sql: str) -> str:
    """Prettify a SQL string with consistent casing and indentation."""
    return sqlglot.transpile(sql, pretty=True)[0]
