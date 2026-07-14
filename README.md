# Tornatura

Tornatura is a project for agricultural data analysis and mapping.

## Data
The agricultural data used in this project can be downloaded from **ARPA** (Agenzia Regionale per la Prevenzione, l'Ambiente e l'Energia).

## Setup and Run

### Using `uv` (Recommended)
If you have `uv` installed, you can run the application directly:

```bash
uv run streamlit run tornatura/app.py
```

`uv` will automatically handle the environment and dependencies.

### Using `venv` and `requirements.txt`
Alternatively, you can use a standard Python virtual environment:

1. Create a virtual environment:
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # On macOS/Linux
   ```
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Run the application:
   ```bash
   streamlit run tornatura/app.py
   ```
