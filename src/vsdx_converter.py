from __future__ import annotations

from pathlib import Path
from bpmn_to_vsdx import convert_bpmn_to_vsdx


def convert_to_vsdx(bpmn_path: str | Path, output_dir: str | Path) -> Path:
    """
    Converts BPMN to VSDX using bpmn-to-visio.
    Package docs expose:
        from bpmn_to_vsdx import convert_bpmn_to_vsdx
    """
    bpmn_path = Path(bpmn_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    convert_bpmn_to_vsdx(str(bpmn_path), output_dir=str(output_dir))

    expected = output_dir / f"{bpmn_path.stem}.vsdx"
    if not expected.exists():
        matches = list(output_dir.glob("*.vsdx"))
        if matches:
            return matches[0]
        raise FileNotFoundError("VSDX conversion finished but no .vsdx file was found.")

    return expected
