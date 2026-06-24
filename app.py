from __future__ import annotations

import json
from pathlib import Path
import tempfile

import streamlit as st

from src.docx_extractor import extract_section6_tables
from src.ai_workflow import workflow_from_rows_rule_based, workflow_from_rows_with_ai
from src.bpmn_generator import generate_process_assets
from src.vsdx_converter import convert_to_vsdx


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

        output_dir = Path("outputs")
        output_dir.mkdir(exist_ok=True)

        try:
            extracted = extract_section6_tables(input_path)

            st.subheader("Extracted procedure rows")
            st.dataframe(extracted["rows"], use_container_width=True)

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

                st.success("Done!")

                col1, col2 = st.columns([2, 1])

                with col1:
                    st.image(str(assets["png"]), caption="Generated preview", use_container_width=True)

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
