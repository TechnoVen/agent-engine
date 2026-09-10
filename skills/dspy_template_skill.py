# skills/dspy_template_skill.py
# OpenClaw Dynamic Skill Adapter
# Enables OpenClaw omnichannel bots (Telegram, WhatsApp, Slack) to execute
# arbitrary declarative JSON templates without writing custom Python modules.

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# Ensure project root is accessible
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.router import ModelRouter
from core.templates import TemplateManager


def execute_template_skill(
    template_id: str, payload: Dict[str, Any], provider: Optional[str] = None
) -> Dict[str, Any]:
    """
    Execute a skill template dynamically on behalf of an OpenClaw bot or automation pipeline.

    Args:
        template_id: Unique slug ID of the template in configs/templates/
        payload: Input dictionary matching the template's declared inputs
        provider: Optional LLM provider override ('ollama', 'llamacpp', 'gemini', etc.)

    Returns:
        Dictionary containing execution results, agent metadata, and status.
    """
    template = TemplateManager.get_template(template_id)
    if not template:
        raise ValueError(
            f"OpenClaw skill template '{template_id}' was not found in configs/templates/."
        )

    # Configure router if an explicit provider is requested
    if provider:
        router = ModelRouter()
        router.initialize_and_configure(force_provider=provider)

    agent = template.create_agent()
    prediction = agent(**payload)

    result_dict = prediction.toDict() if hasattr(prediction, "toDict") else dict(prediction)
    return {
        "status": "success",
        "template_id": template.id,
        "template_name": template.name,
        "inputs": payload,
        "results": result_dict,
    }


def list_available_skills() -> List[Dict[str, Any]]:
    """Return catalog of all discovered skill templates ready for OpenClaw routing."""
    templates = TemplateManager.list_templates()
    return [
        {
            "id": t.id,
            "name": t.name,
            "category": t.category,
            "description": t.description,
            "inputs": list(t.inputs.keys()) if isinstance(t.inputs, dict) else t.inputs,
            "outputs": list(t.outputs.keys()) if isinstance(t.outputs, dict) else t.outputs,
            "sample_inputs": t.sample_inputs,
        }
        for t in templates
    ]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="OpenClaw Dynamic Template Skill Runner")
    parser.add_argument("--list", action="store_true", help="List all available skill templates")
    parser.add_argument("--template", type=str, help="Template ID to execute")
    parser.add_argument("--payload", type=str, help="JSON string of input parameters")
    parser.add_argument("--provider", type=str, default=None, help="Force specific LLM provider")
    args = parser.parse_args()

    if args.list:
        skills = list_available_skills()
        print(json.dumps(skills, indent=2))
    elif args.template:
        inputs = json.loads(args.payload) if args.payload else {}
        # If payload is empty, use sample inputs if available
        if not inputs:
            tmpl = TemplateManager.get_template(args.template)
            if tmpl and tmpl.sample_inputs:
                inputs = tmpl.sample_inputs
                print(f"[*] Using default sample inputs for '{args.template}'...")

        res = execute_template_skill(args.template, inputs, provider=args.provider)
        print(json.dumps(res, indent=2))
    else:
        parser.print_help()
