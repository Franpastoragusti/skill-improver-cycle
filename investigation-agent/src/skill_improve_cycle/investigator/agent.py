"""Execute the saved investigation skill with Code Mode."""

from pydantic_ai import Agent

from skill_improve_cycle.common.composition import build_capabilities
from skill_improve_cycle.common.models import Diagnosis


def build_agent(model, capabilities):
    return Agent(
        model,
        name="orders-investigator",
        instructions="Load the investigate-incident skill and follow it to complete the requested investigation. Write the final diagnosis in English.",
        capabilities=build_capabilities(capabilities),
        output_type=Diagnosis,
    )
