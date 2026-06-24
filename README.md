# Procedure to Visio

Small app to convert a procedure document into a BPMN diagram and Visio `.vsdx`.

Pipeline:

```text
DOCX upload
→ extract section 6 procedure table
→ AI normalizes it into workflow JSON
→ ProcessPiper draws the process
→ BPMN fixer validates lanes/gateways
→ bpmn-to-visio converts BPMN to VSDX
```

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

Create a `.env` or set your variable manually:

```bash
set OPENAI_API_KEY=your_key_here
```

## Run app

```bash
streamlit run app.py
```

## Run CLI with a DOCX

```bash
python main.py "Concialiacion Bancaria.docx"
```

Generated files are saved in `outputs/`.

## Notes

- The AI only creates normalized JSON.
- The code owns BPMN generation and VSDX conversion.
- This is intentionally reusable for many procedure documents with the same section/table style.
