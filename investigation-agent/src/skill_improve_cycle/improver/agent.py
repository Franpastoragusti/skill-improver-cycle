"""Generate and refine an investigation program; never publish it into the skill."""

from pydantic_ai import Agent

from skill_improve_cycle.common.composition import build_capabilities
from skill_improve_cycle.common.models import Diagnosis


IMPROVER_INSTRUCTIONS = """Use Code Mode to complete the loaded skill with as few
run_code invocations and model round trips as practical, ideally one program after
necessary tool discovery. Do not trade correctness or verification for fewer calls.

Before running the investigation, discover the tools needed for its expected path
and alternative branches, and inspect their signatures. Independent search_tools
calls may be issued together; keep each search focused because results are limited.
Do not call tools that have not been discovered or guess their arguments.

Inside the program, pass actual tool results directly into dependent calls. Use
variables, loops and conditions to handle response envelopes, pagination, empty
results, existing records and create/update branches. Inspect returned schemas and
construct subsequent queries from them within the program when possible, instead
of stopping merely to show an intermediate schema or identifier to the model.
Keep independent reads concurrent as described by the skill and the runtime.

For this investigation, do not deliberately split a successful execution into an
"evidence collection" program and a later "Notion write" program. Include both in
the initial program: derive the status with the skill's current-order rules, build
a factual diagnosis from observed errors and traces, then execute the applicable
create/update/reuse branch and verify it. Prepare these conditional branches before
running; unknown IDs and values should become variables filled by earlier calls,
not a reason to return intermediate datasets to the model. Return early only for
an actual blocker or a legitimate early exit defined by the skill.

Complete evidence gathering, the permitted write and its readback before returning
the final result. Return a compact summary with exact observed identifiers, evidence,
verification results and any unresolved blocker as the final top-level expression;
do not leave the only result expression inside a conditional. Do not return entire
raw datasets when a summary preserves the evidence needed for the diagnosis.

Use another program if an unavailable tool, unexpected schema or execution error
requires discovery or correction. After partial execution, inspect the actual state
before retrying writes; do not blindly replay a program that may have created a record.
Report incomplete work honestly. Generate the program for this request using its
inputs and observed data; do not hardcode identifiers or outcomes from earlier runs.

Runtime compatibility (Monty is a Python subset, not CPython):
- Prefer a straightforward readable program with a few focused helpers. One program
  does not mean minified code or a generic framework for every hypothetical response.
- Call each discovered MCP function directly with explicit keyword arguments. Do not
  pass tool functions as values to wrappers, and do not unpack mixed-type **kwargs.
- For dynamic JSON arguments (filters, properties, lists of properties or blocks),
  use json.loads(json.dumps(value)) at the call boundary. Native open-object schemas
  can appear as closed TypedDicts to the type checker. Keep the actual payload valid
  against the discovered schema; this does not remove service-side validation.
  Normalize union-shaped responses the same way before inspecting their shape.
- Use explicit loops or list comprehensions. Avoid yield, generator expressions,
  next, map, getattr, asyncio.create_task and asyncio.wait. Use asyncio.gather with
  positional awaitables for independent calls, as the runtime describes.
- Use datetime.fromisoformat, datetime.fromtimestamp with timezone.utc, timestamp,
  timedelta and strftime for dates. Do not use date.toordinal or implement calendar
  arithmetic manually. Validate missing values before conversion, preserve timezone
  information and normalize epoch milliseconds to seconds where applicable.
- For heterogeneous mutable state, use an explicit dict[str, Any] annotation
  (from typing import Any), or separate variables for verification, blockers and
  results. An unannotated dict containing lists, dicts and None can cause invalid
  union-type assignments when updating nested fields. Validate external data before
  adding it to that state; typing annotations are not response validation.
- Validate required IDs and strings before calls; do not turn missing values into
  the literal string 'None'. Do not guess missing response shapes or hide errors.
- Keep written reports concise, with plain text in separate bounded blocks. Do not
  dump raw schemas, entire trace payloads or heavily formatted documents into a
  single external write. Respect the destination's payload limits.
"""



def build_improver(model, capabilities):
    return Agent(
        model,
        name="investigation-script-improver",
        instructions=[
            "You develop an executable program for the investigate-incident skill. "
            "Load that skill, generate a program for the supplied reference case, execute "
            "it and correct recoverable errors using the actual execution results. "
            "Your test runs use real MCP tools and may write the incident permitted by "
            "the skill. Verify those effects before reporting completion. "
            "The generated code and execution evidence are candidates for later review; "
            "do not publish or replace the skill. One successful case does not prove "
            "general applicability. Write the final diagnosis in English.",
            IMPROVER_INSTRUCTIONS,
        ],
        capabilities=build_capabilities(capabilities, code_mode=True),
        output_type=Diagnosis,
    )
