from pathlib import Path

import folium
import geopandas as gpd
import requests
import streamlit as st
from shapely.geometry import Point
from streamlit_folium import st_folium

# Configurazione pagina Streamlit
st.set_page_config(layout="wide", page_title="Conosci il tuo paesaggio agricolo")
st.title("🌾 Conosci i tuoi vicini, conosci il tuo paesaggio")
st.write(
    "Scopri cosa viene coltivato intorno alla tua azienda. Seleziona le colture di tuo "
    "interesse e visualizza la composizione del paesaggio agricolo che ti circonda."
)

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

CROP_CLASS_MAP = {
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

# Classi non agricole (artefatti di classificazione satellitare): escluse dai
# calcoli di superficie agricola.
NON_AGRI_CODES = {10, 11, 15, 16}

# Sistema metrico locale (UTM 32N) per buffer e calcolo aree in Emilia-Romagna.
METRIC_EPSG = 32632

_COLORS = [
    "#e6194b", "#3cb44b", "#ffe119", "#4363d8", "#f58231", "#911eb4", "#46f0f0",
    "#f032e6", "#bcf60c", "#fabebe", "#008080", "#e6beff", "#9a6324", "#fffac8",
    "#800000", "#aaffc3", "#808000", "#ffd8b1", "#000075", "#808080",
]


def presence_indicator(pct: float):
    """Indicatore divulgativo di presenza nel paesaggio (NON un indice di rischio).

    Soglie indicative: <20% limitata, 20-50% diffusa, >=50% elevata.
    """
    if pct < 20:
        return "🌱", "presenza limitata"
    if pct < 50:
        return "🌱🌱", "presenza diffusa"
    return "🌱🌱🌱", "presenza elevata"


# 1. CARICAMENTO DATI
@st.cache_data(show_spinner="Caricamento dati iColt 2025…")
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
    gdf_fields["crop_class"] = gdf_fields["ID_CROP"].map(
        lambda c: CROP_CLASS_MAP.get(c, "altro/sconosciuto")
    )
    gdf_fields["is_agri"] = ~gdf_fields["ID_CROP"].isin(NON_AGRI_CODES)
    return gdf_fields


# 2. ANALISI DEL PAESAGGIO
# Le percentuali sono calcolate sulle SUPERFICI (ettari), ritagliando gli
# appezzamenti al buffer in proiezione metrica: un campo a cavallo del bordo
# contribuisce solo per la parte interna al buffer.
@st.cache_data(show_spinner="Analisi del paesaggio agricolo…")
def analyze_landscape(lat: float, lon: float, radius_m: float):
    gdf = load_data()
    center_metric = gpd.GeoSeries([Point(lon, lat)], crs=4326).to_crs(METRIC_EPSG)
    buffer_metric = center_metric.buffer(radius_m).iloc[0]
    buffer_geo = (
        gpd.GeoSeries([buffer_metric], crs=METRIC_EPSG).to_crs(4326).iloc[0]
    )
    buffer_ha = buffer_metric.area / 10_000

    idx = gdf.sindex.query(buffer_geo, predicate="intersects")
    fields = gdf.iloc[idx].copy()
    if fields.empty:
        fields["ha_in_buffer"] = []
        return fields, buffer_geo, buffer_ha

    metric_geoms = fields.geometry.to_crs(METRIC_EPSG).make_valid()
    clipped = metric_geoms.intersection(buffer_metric)
    fields["ha_in_buffer"] = clipped.area / 10_000
    fields = fields[fields["ha_in_buffer"] > 0.001]
    return fields, buffer_geo, buffer_ha


# 3. GEOCODING (Nominatim)
@st.cache_data(show_spinner=False)
def geocode_address(address: str):
    """Restituisce (lat, lon) per un indirizzo testuale, o None se non trovato."""
    try:
        resp = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={"q": address, "format": "json", "limit": 1},
            headers={"User-Agent": "crop-class-map/1.0"},
            timeout=5,
        )
        resp.raise_for_status()
        results = resp.json()
        if results:
            return float(results[0]["lat"]), float(results[0]["lon"])
    except Exception:
        pass
    return None


# 4. STATO
if "clicked_point" not in st.session_state:
    st.session_state.clicked_point = None

gdf_all = load_data()
ALL_CROPS = sorted(gdf_all.loc[gdf_all["is_agri"], "crop_class"].unique())
COLOR_MAP = {crop: _COLORS[i % len(_COLORS)] for i, crop in enumerate(ALL_CROPS)}

# 5. CONTROLLI SIDEBAR
with st.sidebar:
    st.subheader("📍 La tua azienda")
    st.caption(
        "In attesa dell'integrazione con i profili aziendali, imposta la posizione "
        "cliccando sulla mappa o cercando un indirizzo."
    )
    address_input = st.text_input("Indirizzo", placeholder="es. Via Emilia 1, Bologna")
    if st.button("Cerca", width="stretch") and address_input.strip():
        coords = geocode_address(address_input.strip())
        if coords:
            st.session_state.clicked_point = coords
            st.rerun()
        else:
            st.error("Indirizzo non trovato. Prova a essere più preciso.")

    radius_km = st.slider("Raggio del buffer (km)", min_value=1, max_value=20, value=5)

    st.subheader("🌾 La tua coltura")
    default_crop = ALL_CROPS.index("pero") if "pero" in ALL_CROPS else 0
    my_crop = st.selectbox(
        "Coltura aziendale (simulata)",
        options=ALL_CROPS,
        index=default_crop,
        help="Nell'app integrata sarà la coltura registrata dall'utente.",
    )

    st.subheader("🗺️ Altri layer")
    other_crops = st.multiselect(
        "Altre colture da esplorare",
        options=[c for c in ALL_CROPS if c != my_crop],
    )
    show_all_agri = st.checkbox("Tutte le superfici agricole", value=False)

# 6. ANALISI (derivata dal punto selezionato)
fields = buffer_geo = None
buffer_ha = 0.0
if st.session_state.clicked_point:
    lat, lon = st.session_state.clicked_point
    fields, buffer_geo, buffer_ha = analyze_landscape(lat, lon, radius_km * 1000)

# 7. MAPPA FOLIUM
if st.session_state.clicked_point:
    center_lat, center_lon = st.session_state.clicked_point
else:
    center_lat, center_lon = 44.5, 11.0
m = folium.Map(location=[center_lat, center_lon], zoom_start=11, tiles="openstreetmap")
folium.TileLayer(
    tiles="https://mt1.google.com/vt/lyrs=y&x={x}&y={y}&z={z}",
    attr="Google",
    name="Google Satellite",
    overlay=False,
    control=True,
).add_to(m)


def add_crop_layer(gdf, name, fill_color, border_color="black", weight=1, opacity=0.6, show=True):
    """Aggiunge un layer di appezzamenti alla mappa (geometrie semplificate per leggerezza)."""
    layer_gdf = gdf[["crop_class", "ha_in_buffer", "geometry"]].copy()
    layer_gdf["ha_lbl"] = layer_gdf["ha_in_buffer"].round(2)
    layer_gdf["geometry"] = layer_gdf.geometry.simplify(0.00005)
    fg = folium.FeatureGroup(name=name, show=show)
    folium.GeoJson(
        layer_gdf,
        style_function=lambda feature, fc=fill_color, bc=border_color, w=weight, op=opacity: {
            "fillColor": fc(feature) if callable(fc) else fc,
            "color": bc,
            "weight": w,
            "fillOpacity": op,
        },
        tooltip=folium.GeoJsonTooltip(
            fields=["crop_class", "ha_lbl"],
            aliases=["Coltura:", "Ettari nel buffer:"],
        ),
    ).add_to(fg)
    fg.add_to(m)


if st.session_state.clicked_point and fields is not None:
    lat, lon = st.session_state.clicked_point
    folium.Marker(
        [lat, lon],
        popup="La tua azienda (posizione simulata)",
        icon=folium.Icon(color="red", icon="home"),
    ).add_to(m)
    folium.GeoJson(
        buffer_geo,
        name="Buffer",
        style_function=lambda x: {
            "fillColor": "#3186cc",
            "color": "#3186cc",
            "weight": 1.5,
            "fillOpacity": 0.08,
        },
    ).add_to(m)

    agri = fields[fields["is_agri"]]

    # Layer 2 — tutte le superfici agricole (sfondo neutro)
    if show_all_agri and not agri.empty:
        add_crop_layer(
            agri,
            "Superficie agricola (tutte le colture)",
            fill_color="#7bb661",
            border_color="#4a7a3a",
            weight=0.5,
            opacity=0.25,
        )

    # Layer colture aggiuntive selezionate
    for crop in other_crops:
        crop_gdf = agri[agri["crop_class"] == crop]
        if not crop_gdf.empty:
            add_crop_layer(
                crop_gdf,
                crop,
                fill_color=COLOR_MAP.get(crop, "gray"),
                opacity=0.6,
            )

    # Layer 1 — la coltura dell'utente, attivo di default ed evidenziato
    my_gdf = agri[agri["crop_class"] == my_crop]
    if not my_gdf.empty:
        add_crop_layer(
            my_gdf,
            f"🌾 {my_crop} (la tua coltura)",
            fill_color=COLOR_MAP.get(my_crop, "#e6194b"),
            border_color="#d62728",
            weight=2,
            opacity=0.75,
        )

    folium.LayerControl(collapsed=False).add_to(m)
    minx, miny, maxx, maxy = buffer_geo.bounds
    m.fit_bounds([[miny, minx], [maxy, maxx]])

# 8. RENDERING MAPPA E CATTURA DEI CLIC
map_data = st_folium(m, width=1100, height=600, returned_objects=["last_clicked"])

if map_data and map_data.get("last_clicked"):
    click = (map_data["last_clicked"]["lat"], map_data["last_clicked"]["lng"])
    if st.session_state.clicked_point != click:
        st.session_state.clicked_point = click
        st.rerun()

# 9. STATISTICHE DEL PAESAGGIO
if fields is None:
    st.info("📍 Fai clic sulla mappa (o cerca un indirizzo) per impostare la posizione della tua azienda.")
else:
    agri = fields[fields["is_agri"]]
    agri_ha = float(agri["ha_in_buffer"].sum())
    my_ha = float(agri.loc[agri["crop_class"] == my_crop, "ha_in_buffer"].sum())
    pct_my = 100 * my_ha / agri_ha if agri_ha > 0 else 0.0
    pct_agri = 100 * agri_ha / buffer_ha if buffer_ha > 0 else 0.0
    emoji, label = presence_indicator(pct_my)

    st.subheader("📊 Il paesaggio intorno alla tua azienda")
    col1, col2, col3 = st.columns(3)
    col1.metric(
        f"🌾 {my_crop}",
        f"{pct_my:.0f}% dell'area agricola",
        help="Quota della superficie agricola nel buffer occupata dalla tua coltura "
        "(calcolata sugli ettari effettivamente interni al buffer).",
    )
    col2.metric(
        "Superficie agricola",
        f"{pct_agri:.0f}% del buffer",
        help=f"{agri_ha:,.0f} ha agricoli su {buffer_ha:,.0f} ha totali nel raggio di {radius_km} km.",
    )
    col3.metric("Appezzamenti agricoli nel buffer", f"{len(agri):,}")

    st.markdown(
        f"**La tua coltura nel paesaggio circostante:** {emoji} "
        f"{my_crop} occupa il **{pct_my:.0f}%** della superficie agricola "
        f"nel raggio di {radius_km} km — *{label}*."
    )
    st.caption(
        "Indicatore divulgativo di consapevolezza del paesaggio (soglie indicative: "
        "<20% limitata, 20–50% diffusa, ≥50% elevata). Non è un indice di rischio: "
        "una presenza elevata della stessa coltura può però favorire disponibilità e "
        "continuità di risorse per organismi dannosi ad essa associati."
    )

    if not agri.empty:
        st.markdown("**Composizione della superficie agricola nel buffer**")
        table = (
            agri.groupby("crop_class")
            .agg(ettari=("ha_in_buffer", "sum"), appezzamenti=("ha_in_buffer", "size"))
            .sort_values("ettari", ascending=False)
        )
        table["% sup. agricola"] = (100 * table["ettari"] / agri_ha).round(1)
        table["ettari"] = table["ettari"].round(1)
        table.index.name = "coltura"
        st.dataframe(table, width="stretch")

# 10. SEZIONE DIVULGATIVA (bozza — testi e grafica da sviluppare con Alex)
with st.expander("🐛 Perché è importante sapere cosa c'è intorno a te?"):
    st.markdown(
        """
**I parassiti non conoscono i confini aziendali!**

Durante la stagione possono spostarsi tra aziende e colture diverse seguendo la
disponibilità di risorse, lo sviluppo e la maturazione dei frutti e le diverse
epoche di raccolta. Per questo, conoscere il paesaggio agricolo che ti circonda
può aiutarti a capire **da dove può arrivare il rischio** e **come può cambiare
durante la stagione**.

**Un esempio: la cimice asiatica (*Halyomorpha halys*)**

Nel corso della stagione può spostarsi tra colture ospiti diverse, seguendo la
maturazione dei frutti:

<div style="font-size: 1.3em; text-align: center; padding: 0.5em;">
INIZIO STAGIONE&nbsp;&nbsp;→&nbsp;&nbsp;ESTATE&nbsp;&nbsp;→&nbsp;&nbsp;FINE STAGIONE<br>
🍑 Pesco&nbsp;&nbsp;&nbsp;🐛→&nbsp;&nbsp;&nbsp;🍐 Pero&nbsp;&nbsp;&nbsp;🐛→&nbsp;&nbsp;&nbsp;🥝 Kiwi
</div>

| Periodo | Colture ospiti principali (esempio indicativo) |
|---|---|
| Inizio stagione (primavera) | 🍑 pesco, albicocco, ciliegio |
| Piena estate | 🍐 pero, susino, melo, colture estive |
| Fine stagione (autunno) | 🥝 kiwi, kaki, vigneti |

*L'esempio non rappresenta un percorso fisso: comunica che la disponibilità di
ospiti cambia durante la stagione e che gli insetti possono spostarsi
all'interno del paesaggio agricolo.*
        """,
        unsafe_allow_html=True,
    )
    st.caption("Sezione divulgativa preliminare — testi, grafica e contenuti da sviluppare con Alex.")
