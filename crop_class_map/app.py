from pathlib import Path

import streamlit as st
import geopandas as gpd
import folium
import requests
from streamlit_folium import st_folium
from shapely.geometry import Point

# Dati ARPAE iColt 2025, risolti rispetto alla radice del progetto
# (indipendente dalla directory da cui si lancia Streamlit).
# Il GeoParquet è la fonte primaria (compatto, incluso nel repo, già in WGS84);
# lo shapefile originale resta come fallback per l'uso locale.
_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DATA_PARQUET = _DATA_DIR / "icolt2025_er.parquet"
DATA_SHP = (
    _DATA_DIR
    / "icolt2025_web"
    / "iCOLT2025_ER_vec_unione"
    / "iCOLT2025_ER_vec_HAgt05_clean.shp"
)

# Configurazione pagina Streamlit
st.set_page_config(layout="wide", page_title="Crop Class Spatial Filter")
st.title("🚜 Analisi Campi per Raggio e Coltura")
st.write("Clicca in un punto qualsiasi sulla mappa per caricare i campi nel raggio selezionato.")

# 1. CARICAMENTO DATI (Simulato o da file)
@st.cache_data
def load_data():
    if DATA_PARQUET.exists():
        gdf_fields = gpd.read_parquet(DATA_PARQUET)
    elif DATA_SHP.exists():
        gdf_fields = gpd.read_file(DATA_SHP)
    else:
        st.error(
            f"Dati non trovati: {DATA_PARQUET}\n\n"
            "Serve il GeoParquet dei campi iColt 2025 (o lo shapefile ARPAE estratto) "
            "nella cartella `data/` (vedi README)."
        )
        st.stop()
    if gdf_fields.crs is None or gdf_fields.crs.to_epsg() != 4326:
        gdf_fields = gdf_fields.to_crs(epsg=4326)
    crop_class_map = {
        1: "colture estive",
        2: "colture autunno-vernine",
        3: "prati e medica",
        8: "risaie",
        10: "nubi e neve",
        11: "aree non acquisite",
        12: "vigneti",
        13: "frutteti misti",
        14: "olivo",
        15: "nubi",
        16: "neve",
        17: "arboricoltura da legno",
        20: "kiwi",
        21: "albicocco",
        22: "ciliegio",
        23: "kaki",
        24: "melo",
        25: "pero",
        26: "pesco",
        27: "susino",
    }
    gdf_fields["crop_class"] = gdf_fields.apply(
        lambda row: crop_class_map.get(row.ID_CROP, "altro/sconosciuto"), axis=1
    )
    # # ESEMPIO SIMULATO (Zona Emilia-Romagna)
    # import numpy as np
    # from shapely.geometry import Polygon
    
    # lon_center, lat_center = 11.0, 44.5
    # polygons, classes = [], []
    # for _ in range(1000):
    #     dx, dy = np.random.uniform(-0.2, 0.2, 2)
    #     cx, cy = lon_center + dx, lat_center + dy
    #     poly = Polygon([(cx, cy), (cx+0.005, cy), (cx+0.005, cy+0.005), (cx, cy+0.005)])
    #     polygons.append(poly)
    #     classes.append(np.random.choice(["Grano", "Mais", "Vite", "Frutteto"]))
        
    # gdf = gpd.GeoDataFrame({"crop_class": gdf, "geometry": polygons}, crs="EPSG:4326")
    return gdf_fields

gdf_all = load_data()

# 2. GESTIONE DELLO STATO (Session State)
if "clicked_point" not in st.session_state:
    st.session_state.clicked_point = None
if "filtered_gdf" not in st.session_state:
    st.session_state.filtered_gdf = gpd.GeoDataFrame(columns=gdf_all.columns, crs="EPSG:4326")
if "radius_km" not in st.session_state:
    st.session_state.radius_km = 5

# 3. GEOCODING (Nominatim)
@st.cache_data(show_spinner=False)
def geocode_address(address: str):
    """Restituisce (lat, lon) per un indirizzo testuale, o None se non trovato."""
    try:
        resp = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={"q": address, "format": "json", "limit": 1},
            headers={"User-Agent": "tornatura-app/1.0"},
            timeout=5,
        )
        resp.raise_for_status()
        results = resp.json()
        if results:
            return float(results[0]["lat"]), float(results[0]["lon"])
    except Exception:
        pass
    return None

# 4. LOGICA DI FILTRO SPAZIALE
def filter_fields(lat, lon, gdf, radius_m=5000):
    # Creiamo il punto cliccato in EPSG:4326
    click_geo = gpd.GeoSeries([Point(lon, lat)], crs="EPSG:4326")
    
    # Convertiamo temporaneamente in un sistema metrico locale (es. EPSG:32632 per l'Italia) 
    # per calcolare accuratamente i 5km di buffer
    click_metric = click_geo.to_crs(epsg=32632)
    buffer_metric = click_metric.buffer(radius_m)
    buffer_geo = buffer_metric.to_crs(epsg=4326).geometry.iloc[0]
    
    # Filtro spaziale: prendiamo solo i campi che intersecano o sono dentro il buffer
    # Utilizziamo l'index spaziale (sindex) per una velocità massima
    possible_matches_index = gdf.sindex.query(buffer_geo, predicate="intersects")
    precise_matches = gdf.iloc[possible_matches_index]
    
    return precise_matches, buffer_geo

# 5. CONTROLLI SIDEBAR
with st.sidebar:
    st.subheader("🔍 Cerca indirizzo")
    address_input = st.text_input("Indirizzo", placeholder="es. Via Emilia 1, Bologna")
    if st.button("Cerca", use_container_width=True) and address_input.strip():
        coords = geocode_address(address_input.strip())
        if coords:
            new_lat, new_lon = coords
            st.session_state.clicked_point = (new_lat, new_lon)
            filtered_fields_gdf, buffer_geom = filter_fields(new_lat, new_lon, gdf_all, st.session_state.radius_km * 1000)
            st.session_state.filtered_gdf = filtered_fields_gdf
            st.session_state.buffer_geom = buffer_geom
            st.rerun()
        else:
            st.error("Indirizzo non trovato. Prova a essere più preciso.")

    st.subheader("⚙️ Filtri")
    radius_km = st.slider("Raggio di ricerca (km)", min_value=1, max_value=20, value=st.session_state.radius_km, step=1)
    all_crops = sorted(gdf_all["crop_class"].unique())
    selected_crop = st.selectbox("Tipo di coltura", options=["Tutte"] + all_crops)

# Ricalcola se il raggio è cambiato e c'è un punto cliccato
if radius_km != st.session_state.radius_km:
    st.session_state.radius_km = radius_km
    if st.session_state.clicked_point:
        lat, lon = st.session_state.clicked_point
        filtered_fields_gdf, buffer_geom = filter_fields(lat, lon, gdf_all, radius_km * 1000)
        st.session_state.filtered_gdf = filtered_fields_gdf
        st.session_state.buffer_geom = buffer_geom
        st.rerun()

# 5. CREAZIONE DELLA MAPPA FOLIUM
if st.session_state.clicked_point:
    center_lat, center_lon = st.session_state.clicked_point
else:
    center_lat, center_lon = 44.5, 11.0
m = folium.Map(location=[center_lat, center_lon], zoom_start=11, tiles="openstreetmap")

# Aggiungiamo un layer stile "Google Maps Satellite/Hybrid" usando dei tasselli custom gratuiti
folium.TileLayer(
    tiles="https://mt1.google.com/vt/lyrs=y&x={x}&y={y}&z={z}",
    attr="Google",
    name="Google Satellite",
    overlay=False,
    control=True
).add_to(m)

# Se l'utente ha già cliccato, mostriamo il punto, il buffer e i campi filtrati
if st.session_state.clicked_point:
    lat, lon = st.session_state.clicked_point
    
    # 1. Marker sul punto cliccato
    folium.Marker([lat, lon], popup="Punto selezionato", icon=folium.Icon(color="red", icon="info-sign")).add_to(m)
    
    # 2. Poligono del raggio di 5km (Buffer)
    if "buffer_geom" in st.session_state:
        folium.GeoJson(
            st.session_state.buffer_geom,
            style_function=lambda x: {"fillColor": "#3186cc", "color": "#3186cc", "weight": 1, "fillOpacity": 0.15}
        ).add_to(m)
    
    # 3. Campi filtrati (se presenti), con eventuale filtro per coltura
    display_gdf = (
        st.session_state.filtered_gdf
        if selected_crop == "Tutte"
        else st.session_state.filtered_gdf[st.session_state.filtered_gdf["crop_class"] == selected_crop]
    )
    if not display_gdf.empty:
        # Colori dinamici in base alla classe di coltura
        unique_crops = gdf_all["crop_class"].unique()
        _colors = [
            '#e6194b', '#3cb44b', '#ffe119', '#4363d8', '#f58231', '#911eb4', '#46f0f0', '#f032e6', '#bcf60c', '#fabebe',
            '#008080', '#e6beff', '#9a6324', '#fffac8', '#800000', '#aaffc3', '#808000', '#ffd8b1', '#000075', '#808080'
        ]
        color_map = {crop: _colors[i % len(_colors)] for i, crop in enumerate(unique_crops)}

        folium.GeoJson(
            display_gdf,
            name="Campi nel raggio",
            style_function=lambda feature, color_map=color_map: {
                "fillColor": color_map.get(feature["properties"]["crop_class"], "gray"),
                "color": "black",
                "weight": 1,
                "fillOpacity": 0.6,
            },
            tooltip=folium.GeoJsonTooltip(fields=["crop_class"], aliases=["Coltura:"])
        ).add_to(m)

# 5. RENDERING DELLA MAPPA E CATTURA DEI CLIC
# Nota: abilitiamo solo l'evento 'last_clicked' per evitare rinfreschi continui inutili
map_data = st_folium(m, width=1100, height=600, returned_objects=["last_clicked"])

# 6. ASCOLTO DEL CLIC SULLA MAPPA
if map_data and map_data.get("last_clicked"):
    click_coords = map_data["last_clicked"]
    new_lat, new_lon = click_coords["lat"], click_coords["lng"]
    
    # Evita loop infiniti controllando se il punto è effettivamente cambiato
    if st.session_state.clicked_point != (new_lat, new_lon):
        st.session_state.clicked_point = (new_lat, new_lon)
        
        # Calcola i nuovi campi e il buffer
        filtered_fields_gdf, buffer_geom = filter_fields(new_lat, new_lon, gdf_all, radius_km * 1000)
        st.session_state.filtered_gdf = filtered_fields_gdf
        st.session_state.buffer_geom = buffer_geom
        
        # Forza il refresh della pagina per mostrare i nuovi dati sulla mappa
        st.rerun()

# 7. PANNELLO LATERALE INFORMATIVO
with st.sidebar:
    st.subheader("📊 Statistiche Area Selezionata")
    if st.session_state.clicked_point:
        st.write(f"**Coordinate cliccate:** \nLat: {st.session_state.clicked_point[0]:.5f}\nLon: {st.session_state.clicked_point[1]:.5f}")
        display_gdf_stats = (
            st.session_state.filtered_gdf
            if selected_crop == "Tutte"
            else st.session_state.filtered_gdf[st.session_state.filtered_gdf["crop_class"] == selected_crop]
        )
        st.write(f"**Campi trovati:** {len(display_gdf_stats)}")
        
        if not display_gdf_stats.empty:
            st.write("**Conteggio per classe:**")
            st.dataframe(display_gdf_stats["crop_class"].value_counts())
    else:
        st.info("Fai clic sulla mappa per analizzare una zona.")