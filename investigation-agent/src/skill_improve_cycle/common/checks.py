"""Static checks that a candidate program must pass before it can be activated.

These checks do not execute the program. They do not replace regression tests.
"""

import ast

ALLOWED_TOOLS = frozenset({
    "gmail_GMAIL_FETCH_EMAILS",
    "gmail_GMAIL_FETCH_MESSAGE_BY_MESSAGE_ID",
    "gmail_GMAIL_GET_PROFILE",
    "logfire_query_run",
    "logfire_query_schema_reference",
    "mongo_find",
    "notion_NOTION_FETCH_DATABASE",
    "notion_NOTION_FETCH_ROW",
    "notion_NOTION_INSERT_ROW_DATABASE",
    "notion_NOTION_QUERY_DATABASE_WITH_FILTER",
    "notion_NOTION_SEARCH_NOTION_PAGE",
    "notion_NOTION_UPDATE_PAGE",
})
TOOL_PREFIXES = ("gmail_", "logfire_", "mongo_", "notion_")
ALLOWED_IMPORTS = frozenset({"asyncio", "json", "re", "base64", "datetime", "typing"})
FORBIDDEN_CALLS = frozenset({
    "getattr", "setattr", "next", "eval", "exec", "compile", "open", "__import__", "globals", "locals",
})


def check_program(source):
    """Return a list of problems; an empty list means the program passed."""
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return [f"Syntax error at line {exc.lineno}: {exc.msg}"]
    problems = []

    body = list(tree.body)
    if body and isinstance(body[0], ast.Expr) and isinstance(getattr(body[0], "value", None), ast.Constant):
        body = body[1:]
    entry = [n for n in body if isinstance(n, ast.AsyncFunctionDef) and n.name == "run_investigation"]
    if len(entry) != 1 or [a.arg for a in entry[0].args.args] != ["params"]:
        problems.append("The file must define exactly one `async def run_investigation(params)`")
    for node in body:
        if node not in entry:
            problems.append(f"Line {node.lineno}: top-level statement outside run_investigation")

    defined = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            defined.add(node.name)
            defined.update(a.arg for a in node.args.args + node.args.kwonlyargs)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            defined.add(node.id)

    for node in ast.walk(tree):
        line = getattr(node, "lineno", "?")
        if isinstance(node, (ast.Yield, ast.YieldFrom)):
            problems.append(f"Line {line}: yield is not supported by the runtime")
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            modules = [node.module or ""] if isinstance(node, ast.ImportFrom) else [a.name for a in node.names]
            for module in modules:
                if module.split(".")[0] not in ALLOWED_IMPORTS:
                    problems.append(f"Line {line}: import of `{module}` is not allowed")
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in FORBIDDEN_CALLS:
            problems.append(f"Line {line}: call to `{node.func.id}` is not allowed")
        elif (isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)
              and node.id.startswith(TOOL_PREFIXES)
              and node.id not in ALLOWED_TOOLS and node.id not in defined):
            problems.append(f"Line {line}: tool `{node.id}` is not in the skill's allowed tools")
    return problems
