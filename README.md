# crop_class_map

crop_class_map is a Streamlit app for agricultural data analysis and mapping:
click a point (or search an address) in Emilia-Romagna and see all crop fields
within a chosen radius, colored by crop class, with per-class statistics.

## Data
The app uses the **iColt 2025** crop classification by **ARPAE**
(Agenzia regionale per la prevenzione, l'ambiente e l'energia dell'Emilia-Romagna),
derived from satellite imagery. A compact GeoParquet copy of the 2025 layer
(`data/icolt2025_er.parquet`, ~31 MB, EPSG:4326, parcels > 0.5 ha) is included in
this repository, so the app works out of the box. The original shapefiles for all
years (2010-2025) can be downloaded from ARPAE.

## Setup and Run

### Using `uv` (Recommended)
If you have `uv` installed, you can run the application directly:

```bash
uv run streamlit run crop_class_map/app.py
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
   streamlit run crop_class_map/app.py
   ```
