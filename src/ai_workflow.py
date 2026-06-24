from __future__ import annotations
from dotenv import load_dotenv
import re

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
    Rule-based parser for procedure tables.

    Handles:
    - regular sequential activities
    - decision rows like:
        Si: Ir a la actividad 5.1. No: Ir a la actividad 7.
    - decimal activity numbers: 3.1, 5.1, 7.2
    - loopbacks:
        regresa a actividad 5
        luego regresa a la actividad 3
    """

    def clean_no(no: str) -> str:
        return no.strip().strip(".").replace(",", ".")

    def activity_id(no: str, is_gateway: bool = False) -> str:
        clean = clean_no(no)
        clean = re.sub(r"[^0-9A-Za-z_]+", "_", clean).strip("_")
        return ("G" if is_gateway else "A") + clean

    def normalize_lane(value: str) -> str:
        return (value or "").strip().rstrip(".")

    def is_decision_row(activity: str, description: str) -> bool:
        text = f"{activity} {description}".lower()
        return (
            activity.strip().startswith("¿")
            or "si:" in text
            or "sí:" in text
            or "no:" in text
            or "existe" in text and "?" in activity
        )

    def extract_decision_targets(description: str) -> list[dict[str, str]]:
        """
        Extracts:
            Si: Ir a la actividad 5.1.
            No: Ir a la actividad 7.

        Returns:
            [{"label": "Sí", "target_no": "5.1"}, {"label": "No", "target_no": "7"}]
        """

        desc = " ".join((description or "").replace("\n", " ").split())

        # Normalize common OCR/typing variations
        desc = desc.replace("Sí:", "Si:")
        desc = desc.replace("SI:", "Si:")
        desc = desc.replace("NO:", "No:")

        pattern = re.compile(
            r"\b(Si|No)\s*:\s*"
            r"(?:Ir|Dirigirse|Continuar|Continúa|Continua|Pasar|Pasa)?\s*"
            r"(?:a\s*)?"
            r"(?:la\s*)?"
            r"(?:actividad|act\.?)\s*"
            r"([0-9]+(?:\.[0-9]+)*)",
            flags=re.IGNORECASE,
        )

        targets = []

        for match in pattern.finditer(desc):
            raw_label = match.group(1).lower()
            target_no = clean_no(match.group(2))

            label = "Sí" if raw_label == "si" else "No"

            targets.append({
                "label": label,
                "target_no": target_no,
            })

        return targets

    def extract_loop_target(description: str) -> str | None:
        desc = " ".join((description or "").replace("\n", " ").split())

        pattern = re.compile(
            r"(?:regresa|retorna|vuelve|volver|se devuelve)\s*"
            r"(?:a\s*)?"
            r"(?:la\s*)?"
            r"(?:actividad|act\.?)\s*"
            r"([0-9]+(?:\.[0-9]+)*)",
            flags=re.IGNORECASE,
        )

        match = pattern.search(desc)

        if match:
            return clean_no(match.group(1))

        return None

    # ----------------------------------------
    # Lanes
    # ----------------------------------------
    lanes = []

    for row in rows:
        lane = normalize_lane(row.get("responsable", ""))

        if lane and lane not in lanes:
            lanes.append(lane)

    if not lanes:
        lanes = ["Responsable"]

    # ----------------------------------------
    # Nodes
    # ----------------------------------------
    nodes = [
        {
            "id": "START",
            "type": "start",
            "lane": lanes[0],
            "name": "Inicio",
        }
    ]

    no_to_id = {}
    ordered_numbers = []

    for row in rows:
        no = clean_no(row.get("no", ""))
        activity = (row.get("actividad", "") or "").strip()
        description = (row.get("descripcion", "") or "").strip()
        lane = normalize_lane(row.get("responsable", "")) or lanes[0]

        if not no or not activity:
            continue

        is_gateway = is_decision_row(activity, description)
        node_id = activity_id(no, is_gateway=is_gateway)

        no_to_id[no] = node_id
        ordered_numbers.append(no)

        nodes.append({
            "id": node_id,
            "type": "exclusiveGateway" if is_gateway else "task",
            "lane": lane,
            "name": activity,
        })

    last_lane = normalize_lane(rows[-1].get("responsable", "")) or lanes[-1]

    nodes.append({
        "id": "END",
        "type": "end",
        "lane": last_lane,
        "name": "Fin",
    })

    # ----------------------------------------
    # Flows
    # ----------------------------------------
    flows = []

    if ordered_numbers:
        flows.append({
            "source": "START",
            "target": no_to_id[ordered_numbers[0]],
        })

    for idx, row in enumerate(rows):
        no = clean_no(row.get("no", ""))
        description = row.get("descripcion", "") or ""

        if no not in no_to_id:
            continue

        source_id = no_to_id[no]

        decision_targets = extract_decision_targets(description)

        if decision_targets:
            # Decision rows should connect DIRECTLY to both branches.
            for target in decision_targets:
                target_no = target["target_no"]

                if target_no in no_to_id:
                    flows.append({
                        "source": source_id,
                        "target": no_to_id[target_no],
                        "name": target["label"],
                    })

            # Important:
            # Do NOT also add normal sequential flow from a gateway.
            continue

        loop_target_no = extract_loop_target(description)

        if loop_target_no and loop_target_no in no_to_id:
            flows.append({
                "source": source_id,
                "target": no_to_id[loop_target_no],
            })

        # Normal sequential flow
        if idx + 1 < len(ordered_numbers):
            next_no = ordered_numbers[idx + 1]
            flows.append({
                "source": source_id,
                "target": no_to_id[next_no],
            })
        else:
            flows.append({
                "source": source_id,
                "target": "END",
            })

    # ----------------------------------------
    # De-duplicate flows
    # ----------------------------------------
    seen = set()
    deduped = []

    for flow in flows:
        key = (
            flow.get("source"),
            flow.get("target"),
            flow.get("name", ""),
        )

        if key not in seen:
            deduped.append(flow)
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
