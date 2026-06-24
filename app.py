from __future__ import annotations
import subprocess
import sys
import json
from pathlib import Path
import tempfile
from datetime import datetime

import streamlit as st

from src.docx_extractor import extract_section6_tables
from src.ai_workflow import workflow_from_rows_rule_based, workflow_from_rows_with_ai
from src.bpmn_generator import generate_process_assets
from src.vsdx_converter import convert_to_vsdx
from src.visio_postprocess import move_lane_labels_to_left



st.set_page_config(page_title="Procedure to Visio", layout="wide")

st.title("Procedure → BPMN → Visio")
st.caption("Upload a procedure DOCX. The app reads section 6 and generates PNG, BPMN, and VSDX.")

uploaded = st.file_uploader("Upload procedure document", type=["docx"])

use_ai = st.toggle(
    "Use AI extraction",
    value=False,
    help="Turn on after setting OPENAI_API_KEY. Rule-based mode is useful for first tests."
)

if uploaded:
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        input_path = tmp_path / uploaded.name
        input_path.write_bytes(uploaded.getvalue())

        run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_dir = Path("outputs") / run_id
        output_dir.mkdir(parents=True, exist_ok=True)

        try:
            extracted = extract_section6_tables(input_path)

            st.subheader("Extracted procedure rows")
            st.dataframe(extracted["rows"], width="stretch")

            if st.button("Generate Visio file", type="primary"):
                with st.spinner("Generating workflow..."):
                    if use_ai:
                        workflow = workflow_from_rows_with_ai(extracted["title"], extracted["rows"])
                    else:
                        workflow = workflow_from_rows_rule_based(extracted["title"], extracted["rows"])

                    workflow_path = output_dir / "workflow.json"
                    workflow_path.write_text(
                        json.dumps(workflow, ensure_ascii=False, indent=2),
                        encoding="utf-8"
                    )

                with st.spinner("Generating BPMN and PNG preview..."):
                    assets = generate_process_assets(workflow, output_dir)

                with st.spinner("Converting BPMN to VSDX..."):
                    vsdx_path = convert_to_vsdx(assets["bpmn"], output_dir)
                    try:
                        postprocess_script = Path(__file__).resolve().parent / "postprocess_vsdx.py"

                        result = subprocess.run(
                            [
                                sys.executable,
                                str(postprocess_script),
                                str(Path(vsdx_path).resolve()),
                                json.dumps(workflow["lanes"], ensure_ascii=False),
                            ],
                            capture_output=True,
                            text=True,
                            timeout=45,
                        )
                        fixed_vsdx_path = vsdx_path

                        for line in result.stdout.splitlines():
                            if line.startswith("FIXED_FILE="):
                                fixed_vsdx_path = Path(line.replace("FIXED_FILE=", "").strip())
                                break

                        vsdx_path = fixed_vsdx_path

                        if result.stdout:
                            st.code(result.stdout)

                        if result.returncode != 0:
                            st.warning("VSDX created, but lane-label cleanup failed.")
                            st.code(result.stderr)

                    except subprocess.TimeoutExpired:
                        st.warning("VSDX created, but lane-label cleanup took too long. Skipping cleanup.")
                    except Exception as exc:
                        st.warning(f"VSDX created, but lane-label cleanup failed: {exc}")
                st.success("Done!")

                col1, col2 = st.columns([2, 1])

                with col1:
                    st.image(str(assets["png"]), caption="Generated preview", width="stretch")

                with col2:
                    st.download_button(
                        "Download VSDX",
                        data=vsdx_path.read_bytes(),
                        file_name=vsdx_path.name,
                        mime="application/vnd.ms-visio.drawing"
                    )
                    st.download_button(
                        "Download BPMN",
                        data=assets["bpmn"].read_bytes(),
                        file_name=assets["bpmn"].name,
                        mime="application/xml"
                    )
                    st.download_button(
                        "Download JSON",
                        data=workflow_path.read_bytes(),
                        file_name=workflow_path.name,
                        mime="application/json"
                    )

                    st.json(workflow)

        except Exception as exc:
            st.error(str(exc))
            st.exception(exc)
else:
    st.info("Upload a DOCX like the Conciliación Bancaria procedure.")
