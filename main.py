from __future__ import annotations

import json
import sys
from pathlib import Path

from src.docx_extractor import extract_section6_tables
from src.ai_workflow import workflow_from_rows_rule_based, workflow_from_rows_with_ai
from src.bpmn_generator import generate_process_assets
from src.vsdx_converter import convert_to_vsdx


def run_pipeline(docx_path: str | Path, use_ai: bool = False) -> dict:
    output_dir = Path("outputs")
    output_dir.mkdir(exist_ok=True)

    extracted = extract_section6_tables(docx_path)

    if use_ai:
        workflow = workflow_from_rows_with_ai(extracted["title"], extracted["rows"])
    else:
        workflow = workflow_from_rows_rule_based(extracted["title"], extracted["rows"])

    workflow_path = output_dir / "workflow.json"
    workflow_path.write_text(json.dumps(workflow, ensure_ascii=False, indent=2), encoding="utf-8")

    assets = generate_process_assets(workflow, output_dir)
    vsdx_path = convert_to_vsdx(assets["bpmn"], output_dir)

    return {
        "workflow": workflow_path,
        "png": assets["png"],
        "bpmn": assets["bpmn"],
        "vsdx": vsdx_path,
    }


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit('Usage: python main.py "path/to/procedure.docx" [--ai]')

    docx = sys.argv[1]
    use_ai = "--ai" in sys.argv

    result = run_pipeline(docx, use_ai=use_ai)

    print("Generated files:")
    for key, path in result.items():
        print(f"{key}: {path}")
