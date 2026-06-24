from __future__ import annotations
from dotenv import load_dotenv


import json
import os
import re
from typing import Any

from openai import OpenAI
load_dotenv()

SYSTEM_PROMPT = """
You convert Spanish procedure tables into normalized workflow JSON for BPMN generation.

Return ONLY valid JSON. No markdown.

Schema:
{
  "title": string,
  "lanes": [string],
  "nodes": [
    {
      "id": string,
      "type": "start" | "task" | "exclusiveGateway" | "end",
      "lane": string,
      "name": string
    }
  ],
  "flows": [
    {
      "source": string,
      "target": string,
      "name": string optional
    }
  ]
}

Rules:
- IDs must be valid XML IDs: start with a letter. Use START, END, A1, A2, G4_1, etc.
- Add START and END nodes.
- Use one lane per unique Responsable.
- Normal activities are "task".
- Questions/decisions are "exclusiveGateway".
- If description says "Sí: Ir a actividad 5" create a flow with name "Sí".
- If description says "No: Ir a actividad 6" create a flow with name "No".
- If description says "regresa a actividad 5", create a loopback flow to A5.
- If no explicit flow is described, connect activities in numeric order.
- Keep names short enough for a diagram box.
- Preserve Spanish labels.
"""


def workflow_from_rows_with_ai(title: str, rows: list[dict[str, str]], model: str = "gpt-4.1-mini") -> dict[str, Any]:
    client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

    user_payload = {
        "title": title,
        "procedure_rows": rows,
    }

    response = client.responses.create(
        model=model,
        input=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)}
        ],
    )

    text = response.output_text.strip()
    return _load_json(text)


def workflow_from_rows_rule_based(title: str, rows: list[dict[str, str]]) -> dict[str, Any]:
    """
    Fallback parser for tables like the sample procedure.
    Good enough for first tests; AI mode is better for messy docs.
    """
    def activity_id(no: str, is_gateway: bool = False) -> str:
        clean = re.sub(r"[^0-9A-Za-z_]+", "_", no.strip().strip(".")).strip("_")
        return ("G" if is_gateway else "A") + clean

    lanes = []
    for r in rows:
        lane = r["responsable"].strip().rstrip(".")
        if lane and lane not in lanes:
            lanes.append(lane)

    if not lanes:
        lanes = ["Responsable"]

    nodes = [{"id": "START", "type": "start", "lane": lanes[0], "name": "Inicio"}]

    no_to_id = {}
    for r in rows:
        no = r["no"].strip().strip(".")
        name = r["actividad"].strip()
        desc = r["descripcion"].strip()
        lane = r["responsable"].strip().rstrip(".") or lanes[0]
        is_gateway = name.startswith("¿") or "Si:" in desc or "Sí:" in desc or "No:" in desc
        nid = activity_id(no, is_gateway)
        no_to_id[no] = nid
        nodes.append({
            "id": nid,
            "type": "exclusiveGateway" if is_gateway else "task",
            "lane": lane,
            "name": name,
        })

    last_lane = rows[-1]["responsable"].strip().rstrip(".") or lanes[-1]
    nodes.append({"id": "END", "type": "end", "lane": last_lane, "name": "Fin"})

    flows = []
    ordered_ids = [no_to_id[r["no"].strip().strip(".")] for r in rows]

    flows.append({"source": "START", "target": ordered_ids[0]})

    explicit_sources = set()

    for idx, r in enumerate(rows):
        no = r["no"].strip().strip(".")
        src = no_to_id[no]
        desc = r["descripcion"]

        targets = re.findall(r"(Si|Sí|No)\s*:\s*Ir a actividad\s*([0-9]+(?:\.[0-9]+)?)", desc, flags=re.I)
        if targets:
            explicit_sources.add(src)
            for label, target_no in targets:
                target_no = target_no.strip().strip(".")
                if target_no in no_to_id:
                    flows.append({
                        "source": src,
                        "target": no_to_id[target_no],
                        "name": "Sí" if label.lower() in ["si", "sí"] else "No"
                    })
            continue

        loop = re.search(r"regresa a actividad\s*([0-9]+(?:\.[0-9]+)?)", desc, flags=re.I)
        if loop:
            target_no = loop.group(1).strip().strip(".")
            if target_no in no_to_id:
                flows.append({"source": src, "target": no_to_id[target_no]})

        # normal sequential connection unless next edge comes from explicit gateway logic
        if idx + 1 < len(ordered_ids):
            if src not in explicit_sources:
                flows.append({"source": src, "target": ordered_ids[idx + 1]})
        else:
            flows.append({"source": src, "target": "END"})

    # de-dupe
    seen = set()
    deduped = []
    for f in flows:
        key = (f.get("source"), f.get("target"), f.get("name", ""))
        if key not in seen:
            deduped.append(f)
            seen.add(key)

    return {
        "title": title,
        "lanes": lanes,
        "nodes": nodes,
        "flows": deduped,
    }


def _load_json(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text).strip()
        text = re.sub(r"```$", "", text).strip()
    return json.loads(text)
