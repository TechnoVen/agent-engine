#!/usr/bin/env python3

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = ROOT / "configs"
OUTPUT_DIR = ROOT / "generated" / "configs"

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

templates = {
    "mcp_vscode_config.template.json": "mcp_vscode_config.json",
    "goose_extension.template.yaml": "goose_extension.yaml",
}

for template_name, output_name in templates.items():
    source = CONFIG_DIR / template_name
    target = OUTPUT_DIR / output_name

    content = source.read_text().replace(
        "@AGENT_ENGINE_ROOT@",
        str(ROOT),
    )

    target.write_text(content)
    print(f"Generated {target}")
