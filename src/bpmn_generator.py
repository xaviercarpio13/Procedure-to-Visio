from __future__ import annotations

import copy
from pathlib import Path
from typing import Any
from lxml import etree

from processpiper import ProcessMap, ActivityType, EventType


def _connect(source, target, label=None):
    try:
        if label:
            return source.connect(target, label)
        return source.connect(target)
    except TypeError:
        try:
            if label:
                return source.connect(target, text=label)
            return source.connect(target)
        except TypeError:
            return source.connect(target)


def generate_process_assets(workflow: dict[str, Any], output_dir: str | Path) -> dict[str, Path]:
    """
    Generates:
    - preview PNG
    - raw BPMN from ProcessPiper
    - fixed BPMN valid for BPMN editors
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    title_slug = _slug(workflow.get("title", "process"))
    png_path = output_dir / f"{title_slug}.png"
    raw_bpmn_path = output_dir / f"{title_slug}_raw.bpmn"
    fixed_bpmn_path = output_dir / f"{title_slug}.bpmn"

    bpmn_gateway_ids = set()

    with ProcessMap(
        workflow["title"],
        width=5000,
        height=3000,
        auto_size=True,
        painter_type="png"
    ) as pm:
        pm.set_element_font_size(18)
        pm.set_title_font_size(24)

        lanes = {lane_name: pm.add_lane(lane_name) for lane_name in workflow["lanes"]}

        shapes = {}

        for node in workflow["nodes"]:
            lane = lanes.get(node["lane"]) or next(iter(lanes.values()))
            ntype = node["type"]

            if ntype == "start":
                shape = lane.add_element(node["name"], EventType.START)
            elif ntype == "end":
                shape = lane.add_element(node["name"], EventType.END)
            elif ntype == "exclusiveGateway":
                # ProcessPiper installed version has empty GatewayType, so draw as task first.
                # We convert to real exclusiveGateway in fixed BPMN.
                shape = lane.add_element(
                    node["name"],
                    ActivityType.TASK,
                    fill_colour="#FFF2CC",
                    outline_colour="#D6B656"
                )
                if getattr(shape, "bpmn_id", None):
                    bpmn_gateway_ids.add(shape.bpmn_id)
            else:
                shape = lane.add_element(node["name"], ActivityType.TASK)

            shapes[node["id"]] = shape

        for flow in workflow["flows"]:
            src = shapes[flow["source"]]
            tgt = shapes[flow["target"]]
            _connect(src, tgt, flow.get("name"))

        pm.draw()
        pm.save(str(png_path))
        pm.export_to_bpmn(str(raw_bpmn_path))

    fix_processpiper_bpmn(
        raw_file=raw_bpmn_path,
        fixed_file=fixed_bpmn_path,
        title=workflow["title"],
        gateway_bpmn_ids=bpmn_gateway_ids,
    )

    return {
        "png": png_path,
        "raw_bpmn": raw_bpmn_path,
        "bpmn": fixed_bpmn_path,
    }


def fix_processpiper_bpmn(
    raw_file: str | Path,
    fixed_file: str | Path,
    title: str,
    gateway_bpmn_ids: set[str],
) -> None:
    ns = {
        "bpmn": "http://www.omg.org/spec/BPMN/20100524/MODEL",
        "bpmndi": "http://www.omg.org/spec/BPMN/20100524/DI",
        "dc": "http://www.omg.org/spec/DD/20100524/DC",
        "di": "http://www.omg.org/spec/DD/20100524/DI",
    }

    def q(prefix, tag):
        return f"{{{ns[prefix]}}}{tag}"

    parser = etree.XMLParser(remove_blank_text=True)
    tree = etree.parse(str(raw_file), parser)
    root = tree.getroot()

    old_processes = root.findall("bpmn:process", ns)
    old_collab = root.find("bpmn:collaboration", ns)
    old_diagram = root.find("bpmndi:BPMNDiagram", ns)

    node_tags = {
        q("bpmn", "startEvent"),
        q("bpmn", "endEvent"),
        q("bpmn", "task"),
        q("bpmn", "subProcess"),
        q("bpmn", "exclusiveGateway"),
    }

    process_to_lane = {}
    lane_nodes = {}

    for i, proc in enumerate(old_processes, start=1):
        lane_id = f"Lane_{i}"
        process_to_lane[proc.get("id")] = lane_id
        lane_nodes[lane_id] = []

    new_root = etree.Element(
        q("bpmn", "definitions"),
        nsmap={
            "bpmn": ns["bpmn"],
            "bpmndi": ns["bpmndi"],
            "dc": ns["dc"],
            "di": ns["di"],
        }
    )
    new_root.set("id", "Definitions_1")
    new_root.set("targetNamespace", "http://example.com/procedure-to-visio")

    process = etree.SubElement(new_root, q("bpmn", "process"))
    process.set("id", "Process_1")
    process.set("name", title)
    process.set("isExecutable", "false")

    lane_set = etree.SubElement(process, q("bpmn", "laneSet"))
    lane_set.set("id", "LaneSet_1")

    nodes = {}
    flows = []

    for proc in old_processes:
        lane_id = process_to_lane[proc.get("id")]

        for child in proc:
            if child.tag in node_tags:
                node = copy.deepcopy(child)
                node_id = node.get("id")

                if node_id in gateway_bpmn_ids:
                    node.tag = q("bpmn", "exclusiveGateway")

                for io in node.findall("bpmn:incoming", ns) + node.findall("bpmn:outgoing", ns):
                    node.remove(io)

                nodes[node_id] = node
                lane_nodes[lane_id].append(node_id)

            elif child.tag == q("bpmn", "sequenceFlow"):
                flows.append(copy.deepcopy(child))

    incoming = {nid: [] for nid in nodes}
    outgoing = {nid: [] for nid in nodes}

    for flow in flows:
        fid = flow.get("id")
        src = flow.get("sourceRef")
        tgt = flow.get("targetRef")
        if src in outgoing:
            outgoing[src].append(fid)
        if tgt in incoming:
            incoming[tgt].append(fid)

    for node_id, node in nodes.items():
        for fid in incoming[node_id]:
            el = etree.SubElement(node, q("bpmn", "incoming"))
            el.text = fid
        for fid in outgoing[node_id]:
            el = etree.SubElement(node, q("bpmn", "outgoing"))
            el.text = fid

    for i, proc in enumerate(old_processes, start=1):
        lane_id = process_to_lane[proc.get("id")]
        lane = etree.SubElement(lane_set, q("bpmn", "lane"))
        lane.set("id", lane_id)
        lane.set("name", proc.get("name", f"Lane {i}"))

        for node_id in lane_nodes[lane_id]:
            ref = etree.SubElement(lane, q("bpmn", "flowNodeRef"))
            ref.text = node_id

    for node in nodes.values():
        process.append(node)

    for flow in flows:
        process.append(flow)

    new_diagram = etree.SubElement(new_root, q("bpmndi", "BPMNDiagram"))
    new_diagram.set("id", "BPMNDiagram_1")

    plane = etree.SubElement(new_diagram, q("bpmndi", "BPMNPlane"))
    plane.set("id", "BPMNPlane_1")
    plane.set("bpmnElement", "Process_1")

    participant_to_lane = {}

    if old_collab is not None:
        for p in old_collab.findall("bpmn:participant", ns):
            participant_to_lane[p.get("id")] = process_to_lane.get(p.get("processRef"))

    if old_diagram is not None:
        old_plane = old_diagram.find("bpmndi:BPMNPlane", ns)

        if old_plane is not None:
            counter = 1

            for di_child in old_plane:
                if di_child.tag == q("bpmndi", "BPMNShape"):
                    bpmn_el = di_child.get("bpmnElement")

                    if bpmn_el in participant_to_lane:
                        bpmn_el = participant_to_lane[bpmn_el]

                    if bpmn_el not in nodes and bpmn_el not in lane_nodes:
                        continue

                    new_shape = etree.SubElement(plane, q("bpmndi", "BPMNShape"))
                    new_shape.set("id", f"BPMNShape_{counter}")
                    new_shape.set("bpmnElement", bpmn_el)

                    bounds = di_child.find("dc:Bounds", ns)
                    if bounds is not None:
                        new_bounds = copy.deepcopy(bounds)

                        if bpmn_el in nodes and nodes[bpmn_el].tag == q("bpmn", "exclusiveGateway"):
                            x = float(new_bounds.get("x"))
                            y = float(new_bounds.get("y"))
                            w = float(new_bounds.get("width"))
                            h = float(new_bounds.get("height"))
                            cx = x + w / 2
                            cy = y + h / 2
                            new_bounds.set("x", str(cx - 40))
                            new_bounds.set("y", str(cy - 40))
                            new_bounds.set("width", "80")
                            new_bounds.set("height", "80")

                        new_shape.append(new_bounds)

                    counter += 1

                elif di_child.tag == q("bpmndi", "BPMNEdge"):
                    bpmn_el = di_child.get("bpmnElement")

                    if not any(flow.get("id") == bpmn_el for flow in flows):
                        continue

                    new_edge = etree.SubElement(plane, q("bpmndi", "BPMNEdge"))
                    new_edge.set("id", f"BPMNEdge_{counter}")
                    new_edge.set("bpmnElement", bpmn_el)

                    for wp in di_child.findall("di:waypoint", ns):
                        new_edge.append(copy.deepcopy(wp))

                    counter += 1

    etree.ElementTree(new_root).write(
        str(fixed_file),
        pretty_print=True,
        xml_declaration=True,
        encoding="UTF-8"
    )


def _slug(text: str) -> str:
    import re
    text = text.lower()
    text = re.sub(r"[^a-z0-9áéíóúñü]+", "_", text)
    text = text.strip("_")
    return text or "process"
