import io
import re
import json
import zipfile
import tempfile
import chardet
import unicodedata
import pandas as pd
import streamlit as st
import geopandas as gpd
from shapely import wkt
from pyproj import Geod
from shapely.ops import transform
import xml.etree.ElementTree as ET
from shapely.geometry import shape, Point, Polygon, MultiPolygon, MultiPoint

#======================================================================================================================================
# PAGE CONFIGURATION
#======================================================================================================================================

st.set_page_config(
    page_title="File Converter",
    page_icon="sucafina.svg",
    layout="wide"
)

# ======================================================================
# SIDEBAR SETUP
# ======================================================================

st.sidebar.markdown("""
<style>

/* Hide sidebar collapse controls */
[data-testid="stSidebarCollapseButton"],
[data-testid="collapsedControl"] {
    display: none !important;
}

/* Sidebar width */
section[data-testid="stSidebar"] {
    display: block !important;
    min-width: 250px !important;
    width: 205px !important;
    max-width: 205px !important;
}

/* Sidebar background */
[data-testid="stSidebar"] {
    background: #ffffff !important;
    border-right: 1px solid #e5e7eb;
}

/* Sidebar content spacing */
[data-testid="stSidebar"] .block-container {
    padding: 0 0.5rem !important;
}

/* Sidebar logo */
.sidebar-logo {
    width: 100%;
    text-align: center;
    margin: 10px 0 25px 0;
}

.sidebar-logo img {
    width: 180px;
    max-width: 100%;
    height: auto;
    display: block;
    margin: 0 auto;
}

/* Sidebar headings */
.sidebar-heading {
    font-family: 'Poppins', sans-serif;
    font-size: 16px;
    font-weight: 700;
    color: #0F7E89;
    margin: 15px 0 8px 0;
}

.content-headings {
    font-family: 'Poppins', sans-serif !important;
    font-size: 16px !important;
    font-weight: 700 !important;
    color: #0F7E89 !important;
    margin: 0 0 12px 0 !important;
    padding: 0 !important;
}

/* Body Heading */

/* Sidebar text */
.sidebar-text {
    font-family: 'Poppins', sans-serif;
    font-size: 12px;
    font-weight: 400;
    line-height: 1.8;
    color: #374151;
    text-align: justify;
}

/* Sidebar lists */
.sidebar-text ul {
    padding-left: 18px;
    margin-top: 5px;
}

.sidebar-text li {
    margin-bottom: 5px;
}

/* Main body spacing */
.stMainBlockContainer {
    padding-left: 1.5rem !important;
    padding-right: 1.5rem !important;
    max-width: 100% !important;
}

/* Main page buttons */
.stMainBlockContainer div.stButton > button,
.stMainBlockContainer div.stDownloadButton > button {
    min-height: 36px !important;
    padding: 6px 16px !important;
    border-radius: 6px !important;
    font-family: 'Poppins', sans-serif !important;
    font-size: 13px !important;
    font-weight: 600 !important;
    border: 1px solid #0F7E89 !important;
    background: #0F7E89 !important;
    color: #ffffff !important;
    box-shadow: none !important;
    transition: all 0.2s ease !important;
}

/* Button hover */
.stMainBlockContainer div.stButton > button:hover,
.stMainBlockContainer div.stDownloadButton > button:hover {
    background: #096873 !important;
    border-color: #096873 !important;
    color: #ffffff !important;
}

/* Disabled buttons */
.stMainBlockContainer div.stButton > button:disabled,
.stMainBlockContainer div.stDownloadButton > button:disabled {
    background: #d1e5e6 !important;
    border-color: #d1e5e6 !important;
    color: #64748b !important;
    cursor: not-allowed !important;
}


</style>
""", unsafe_allow_html=True)


# ======================================================================
# SIDEBAR CONTENT
# ======================================================================

st.sidebar.markdown("""
<div class="sidebar-logo">
    <img src="https://maprinitiative.org/wp-content/uploads/2026/08/Sucafina-Logo-300x162.jpg"
         alt="Sucafina Logo">
</div>

<div class="sidebar-heading">Geodata Conversion Tool</div>

<div class="sidebar-text">
The Geodata Conversion Tool converts geospatial datasets from
various file formats, including CSV, Excel, KML and GeoJSON.
</div>

<div class="sidebar-heading">Supported File Formats</div>

<div class="sidebar-text">
<ul>
    <li>CSV</li>
    <li>Excel</li>
    <li>GeoJSON</li>
    <li>KML</li>
    <li>ZIP</li>
</ul>
</div>

<div class="sidebar-heading">Geometry Columns </div>

<div class="sidebar-text">
The tool recognises the following geometry column names:
<ul>
    <li>geometry</li>
    <li>plot_wkt</li>
    <li>wkt</li>
</ul>
</div>

""", unsafe_allow_html=True)


#======================================================================================================================================
# Divider
#======================================================================================================================================

def add_divider():
    st.markdown(
        """
        <hr style="
            width: 100%;
            height: 2px;
            border: 0;
            background-color: #0F7E89;
            margin: 20px 0;
            opacity: 1;
        ">
        """,
        unsafe_allow_html=True
    )

#======================================================================================================================================
# DATA LOADING AND PROCESSING COLUMN 
#======================================================================================================================================

final_data = pd.DataFrame()
standardized_df = pd.DataFrame()
base_name = pd.DataFrame()

def normalize(col):
    col = str(col).strip().lower()
    col = unicodedata.normalize('NFKD', col).encode('ascii', 'ignore').decode('ascii')
    col = col.replace(" ", "_")
    return col


GEOMETRY_CANDIDATES = [
    "point", "polygon",
    "wkt", "plot_wkt",
    "geom", "geometry"
]


def find_geom_columns(df):
    normalized_candidates = [normalize(c) for c in GEOMETRY_CANDIDATES]

    geom_columns = [
        col for col in df.columns
        if any(candidate in normalize(col) for candidate in normalized_candidates)
    ]

    return geom_columns


def clean_geometry(value):

    if pd.isna(value) or not isinstance(value, str):
        return value

    text = value.strip()

    if not text:
        return value

    try:

        def strip_zvalues(coords):

            if not coords:
                return coords

            if isinstance(coords[0], (int, float)):
                return coords[:2]

            return [strip_zvalues(c) for c in coords]

 
        def close_ring(coords, tol=1e-9):

            coords = list(coords)

            if len(coords) > 2:

                x0, y0 = coords[0][:2]
                x1, y1 = coords[-1][:2]

                if abs(x0 - x1) > tol or abs(y0 - y1) > tol:
                    coords.append(coords[0])

            return coords


        def extract_xy_from_xyz(text):

            triplet_pattern = re.compile(
                r'(-?\d+(?:\.\d+)?)\s*,\s*'
                r'(-?\d+(?:\.\d+)?)\s*,\s*'
                r'(-?\d+(?:\.\d+)?)'
            )

            matches = triplet_pattern.findall(text)

            return [(float(x), float(y)) for x, y, z in matches]

        def extract_xy_pairs(text):

            pair_pattern = re.compile(
                r'(-?\d+(?:\.\d+)?)\s*[,\s]\s*'
                r'(-?\d+(?:\.\d+)?)'
            )

            pairs = pair_pattern.findall(text)

            return [(float(a), float(b)) for a, b in pairs]

        if '"coordinates"' in text and '"type"' in text:

            geo = json.loads(text)

            geo = geo.get("geometry", geo)

            geo["coordinates"] = strip_zvalues(geo["coordinates"])

            geom = shape(geo)

        elif re.match(
            r'^\s*(POINT|LINESTRING|POLYGON|MULTIPOINT|MULTILINESTRING|MULTIPOLYGON)',
            text,
            re.I
        ):

            geom = wkt.loads(text)

        else:

            text = re.sub(r'[,\s]+$', '', text)

            xyz_coords = extract_xy_from_xyz(text)

            total_numbers = len(
                re.findall(r'-?\d+(?:\.\d+)?', text)
            )

            if len(xyz_coords) >= 3 and len(xyz_coords) * 3 >= 0.6 * total_numbers:

                coords = close_ring(xyz_coords)

                geom = Polygon(coords)

            else:

                coords = extract_xy_pairs(text)

                if len(coords) == 1:
                    geom = Point(coords[0])

                elif len(coords) >= 3:
                    geom = Polygon(close_ring(coords))

                else:
                    return value
        geom = transform(
            lambda x, y, z=None: (x, y),
            geom
        )

        return geom.wkt

    except Exception:
        return value


#======================================================================================================================================
# CORDINATE FORMATTING FUNCTIONS
#======================================================================================================================================
def format_coord(value):
    s = str(value)
    if '.' in s:
        integer, decimal = s.split('.')
        if len(decimal) > 6:
            return f"{round(float(s), 6):.6f}"
        elif len(decimal) < 6:
            padding = '0' * (5 - len(decimal)) + '1'
            new_decimal = decimal + padding
            return f"{integer}.{new_decimal}"
        else:
            return f"{float(s):.6f}"
    else:
        return f"{s}.000001"


def apply_n_times(func, value, n):
    for _ in range(n):
        value = func(value)
    return value


def process_coords(coords):
    return [
        (float(format_coord(lon)), float(format_coord(lat)))
        for lon, lat in coords
    ]


def process_polygon(polygon):
    exterior = process_coords(polygon.exterior.coords)
    interiors = [
        process_coords(ring.coords)
        for ring in polygon.interiors
    ]
    return Polygon(exterior, interiors)


def process_point(point):
    lon = float(format_coord(point.x))
    lat = float(format_coord(point.y))
    return Point(lon, lat)


def process_wkt(wkt_string):

    try:
        geom = wkt.loads(wkt_string)

        # Remove Z values and retain only X, Y coordinate pairs
        geom = transform(
            lambda x, y, z=None: (x, y),
            geom
        )

        if isinstance(geom, Polygon):
            return process_polygon(geom).wkt

        elif isinstance(geom, MultiPolygon):
            return MultiPolygon(
                [process_polygon(p) for p in geom.geoms]
            ).wkt

        elif isinstance(geom, Point):
            return process_point(geom).wkt

        elif isinstance(geom, MultiPoint):
            return MultiPoint(
                [process_point(p) for p in geom.geoms]
            ).wkt

        else:
            return geom.wkt

    except Exception:
        return wkt_string

# ============================================================================================================================================
# CONVERTING GEOMETRY COLUMNS TO GEODATAFRAME
# ============================================================================================================================================

def normalize_text(Data):
    for col in Data.select_dtypes(include=["object"]).columns:
        Data[col] = Data[col].apply(
            lambda x: unicodedata.normalize("NFKD", str(x)).encode("ASCII", "ignore").decode("ASCII")
            if pd.notna(x) else x
        )
    return Data

#========================================================================================================================================
# CONVERSION FUNCTION TO GEODATAFRAME
#========================================================================================================================================

def convert_to_geodf(Data):

    existing_columns = find_geom_columns(Data)

    for col in existing_columns:
        Data[col] = Data[col].apply(
            lambda x: apply_n_times(process_wkt, clean_geometry(x), 2)
            if pd.notna(x) and str(x).strip() else ""
        )

    lon_cols = [
        c for c in Data.columns
        if any(k in normalize(c) for k in ["longitude", "lon", "easting"])
        or normalize(c) == "x"
    ]

    lat_cols = [
        c for c in Data.columns
        if any(k in normalize(c) for k in ["latitude", "lat", "northing"])
        or normalize(c) == "y"
    ]

    #========================================================================================================================================
    # SELECT GEOMETRY BY TYPE
    #========================================================================================================================================

    def choose_geometry(row):

        polygon = ""
        point = ""
        other_geometry = ""

        for col in existing_columns:

            val = row.get(col)

            if pd.isna(val) or not str(val).strip():
                continue

            try:
                geom = wkt.loads(str(val))
                geom_type = geom.geom_type

                if geom_type in ["Polygon", "MultiPolygon"] and not polygon:
                    polygon = geom.wkt

                elif geom_type == "Point" and not point:
                    point = geom.wkt

                elif not other_geometry:
                    other_geometry = geom.wkt

            except Exception:
                continue

        lon = None
        lat = None

        for c in lon_cols:
            val = pd.to_numeric(row.get(c), errors="coerce")
            if pd.notna(val):
                lon = val
                break

        for c in lat_cols:
            val = pd.to_numeric(row.get(c), errors="coerce")
            if pd.notna(val):
                lat = val
                break

        coord_wkt = ""

        if lon is not None and lat is not None:
            coord_wkt = process_wkt(f"POINT ({lon} {lat})")

        final_wkt = (
            polygon
            if polygon
            else point
            if point
            else other_geometry
            if other_geometry
            else coord_wkt
        )

        return pd.Series({"plot_wkt": final_wkt})

    geom_df = Data.apply(choose_geometry, axis=1)

    Data = Data.drop(columns=existing_columns, errors="ignore")

    final_data = pd.concat([Data, geom_df], axis=1)

    final_data = final_data.fillna("")

    final_data.columns = final_data.columns.str.strip()
    final_data.columns = final_data.columns.str.replace(
        "\u200b", "", regex=False
    )
    final_data.columns = final_data.columns.str.lower()

    #========================================================================================================================================
    # AREA CALCULATION
    #========================================================================================================================================

    def compute_plot_area(data):

        geod = Geod(ellps="WGS84")
        data = data.copy()

        area_cols = [
            col for col in data.columns
            if "area" in normalize(col) or "size" in normalize(col)
        ]

        if not area_cols:
            area_cols = ["plot_area_ha"]
            data["plot_area_ha"] = ""

        def calculate_area(geometry, existing_area):

            if geometry is None or not str(geometry).strip():
                return existing_area

            try:
                if isinstance(geometry, str):
                    geometry = wkt.loads(geometry)

                if geometry is None or geometry.is_empty:
                    return existing_area

                if geometry.geom_type == "Polygon":
                    area, _ = geod.geometry_area_perimeter(geometry)
                    return round(abs(area) / 10000, 3)

                elif geometry.geom_type == "MultiPolygon":
                    total_area = 0

                    for polygon in geometry.geoms:
                        area, _ = geod.geometry_area_perimeter(polygon)
                        total_area += abs(area)

                    return round(total_area / 10000, 3)

            except Exception:
                return existing_area

            return existing_area

        for col in area_cols:

            data[col] = data.apply(
                lambda row: calculate_area(
                    row["plot_wkt"],
                    row[col]
                ),
                axis=1
            )

            data[col] = pd.to_numeric(
                data[col], errors="coerce"
            ).round(3)

        return data

    final_data = compute_plot_area(final_data)

    return final_data


#========================================================================================================================================
# AREA CALCULATION
#========================================================================================================================================

    def compute_plot_area(data):

        geod = Geod(ellps="WGS84")
        data = data.copy()

        area_cols = [
            col for col in data.columns
            if "area" in normalize(col) or "size" in normalize(col)
        ]

        def calculate_area(geometry, existing_area):

            if geometry is None:
                return existing_area

            if isinstance(geometry, str):
                try:
                    geometry = wkt.loads(geometry)
                except Exception:
                    return existing_area

            if geometry is None or geometry.is_empty:
                return existing_area

            geom_type = geometry.geom_type

            if geom_type == "Polygon":
                area, _ = geod.geometry_area_perimeter(geometry)
                return round(abs(area) / 10000, 3)

            elif geom_type == "MultiPolygon":
                total_area = 0

                for polygon in geometry.geoms:
                    area, _ = geod.geometry_area_perimeter(polygon)
                    total_area += abs(area)

                return round(total_area / 10000, 3)

            return existing_area

        for col in area_cols:

            data[col] = data.apply(
                lambda row: calculate_area(
                    row["plot_wkt"],
                    row[col]
                ),
                axis=1
            )

            data[col] = pd.to_numeric(
                data[col], errors="coerce"
            ).round(3)

        return data


    final_data = compute_plot_area(final_data)

    return final_data


# ============================================================================================================================================
# KML LOADING FUNCTION
# ============================================================================================================================================

def load_kml(uploaded_file, ext):
    uploaded_file.seek(0)

    if ext == "kmz":
        with zipfile.ZipFile(uploaded_file) as z:
            kml_name = [
                f for f in z.namelist()
                if f.lower().endswith(".kml")
            ][0]
            kml_bytes = z.read(kml_name)
    else:
        kml_bytes = uploaded_file.read()

    root = ET.fromstring(kml_bytes)
    ns = {"kml": "http://www.opengis.net/kml/2.2"}

    rows = []

    for placemark in root.findall(".//kml:Placemark", ns):
        geom = placemark.find(".//kml:Polygon", ns)

        if geom is None:
            geom = placemark.find(".//kml:Point", ns)

        if geom is None:
            geom = placemark.find(".//kml:LineString", ns)

        geom_wkt = ""

        if geom is not None:
            coordinates = geom.find(".//kml:coordinates", ns)

            if coordinates is not None and coordinates.text:
                coords_text = coordinates.text.strip()
                try:
                    geom_wkt = wkt.dumps(shape(coords_text))
                except Exception:
                    geom_wkt = coords_text

        row = {
            "plot_gps_polygon": geom_wkt if geom is not None and "Polygon" in geom.tag else "",
            "plot_gps_point": geom_wkt if geom is not None and "Point" in geom.tag else "",
            "plot_wkt": geom_wkt
        }

        for sd in placemark.findall(".//kml:SimpleData", ns):
            row[sd.attrib.get("name")] = sd.text

        for ed in placemark.findall(".//kml:Data", ns):
            value = ed.find("kml:value", ns)
            row[ed.attrib.get("name")] = value.text if value is not None else ""

        name = placemark.find("kml:name", ns)
        if name is not None and name.text:
            row["name"] = name.text

        desc = placemark.find("kml:description", ns)
        if desc is not None and desc.text:
            row["description"] = desc.text

        rows.append(row)

    return pd.DataFrame(rows)


# ============================================================================================================================================
# GEOJSON LOADING FUNCTION
# ============================================================================================================================================

def load_geojson(uploaded_file, ext):
    uploaded_file.seek(0)

    if ext == "zip":
        with zipfile.ZipFile(uploaded_file) as z:
            geojson_files = [
                f for f in z.namelist()
                if f.lower().endswith((".geojson", ".json"))
            ]

            if not geojson_files:
                return None

            dfs = []

            for fname in geojson_files:
                file_bytes = z.read(fname)

                try:
                    file_str = file_bytes.decode("utf-8")
                except UnicodeDecodeError:
                    file_str = file_bytes.decode("latin-1")

                data = json.loads(file_str)
                features = data.get("features", [])
                rows = []

                for feature in features:
                    geom = feature.get("geometry")
                    props = feature.get("properties") or {}
                    geom_wkt = ""
                    geom_type = ""

                    if geom:
                        try:
                            shapely_geom = shape(geom)
                            geom_wkt = wkt.dumps(shapely_geom)
                            geom_type = shapely_geom.geom_type
                        except Exception:
                            geom_wkt = ""

                    row = {
                        "plot_gps_polygon": geom_wkt if geom_type in ["Polygon", "MultiPolygon"] else "",
                        "plot_gps_point": geom_wkt if geom_type == "Point" else "",
                        "plot_wkt": geom_wkt
                    }

                    for k, v in props.items():
                        row[k] = v

                    extra_keys = [
                        k for k in feature.keys()
                        if k not in ["type", "geometry", "properties"]
                    ]

                    for key in extra_keys:
                        row[key] = feature.get(key)

                    rows.append(row)

                dfs.append(pd.DataFrame(rows))

            if not dfs:
                return None

            return pd.concat(dfs, ignore_index=True, sort=False)

    else:
        file_bytes = uploaded_file.read()

        try:
            file_str = file_bytes.decode("utf-8")
        except UnicodeDecodeError:
            file_str = file_bytes.decode("latin-1")

        data = json.loads(file_str)
        features = data.get("features", [])
        rows = []

        for feature in features:
            geom = feature.get("geometry")
            props = feature.get("properties") or {}
            geom_wkt = ""
            geom_type = ""

            if geom:
                try:
                    shapely_geom = shape(geom)
                    geom_wkt = wkt.dumps(shapely_geom)
                    geom_type = shapely_geom.geom_type
                except Exception:
                    geom_wkt = ""

            row = {
                "plot_gps_polygon": geom_wkt if geom_type in ["Polygon", "MultiPolygon"] else "",
                "plot_gps_point": geom_wkt if geom_type == "Point" else "",
                "plot_wkt": geom_wkt
            }

            for k, v in props.items():
                row[k] = v

            extra_keys = [
                k for k in feature.keys()
                if k not in ["type", "geometry", "properties"]
            ]

            for key in extra_keys:
                row[key] = feature.get(key)

            rows.append(row)

        return pd.DataFrame(rows)


# ============================================================================================================================================
# LOADING DATA
# ============================================================================================================================================
add_divider()


def load_file(file_bytes, ext):

    ext = ext.lower()
    final_data = None

    if ext == "csv":
        raw_data = file_bytes.read()
        file_bytes.seek(0)
        encoding = chardet.detect(raw_data)["encoding"] or "utf-8"
        final_data = pd.read_csv(file_bytes, encoding=encoding)

    elif ext in ["xls", "xlsx"]:
        header_row = st.session_state.get("header_row", 1)
        final_data = pd.read_excel(file_bytes, header=header_row - 1)

    elif ext == "kml":
        final_data = load_kml(file_bytes, ext)

    elif ext in ["geojson", "json"]:
        final_data = load_geojson(file_bytes, ext)

    if final_data is None:
        return None

    final_data = normalize_text(final_data)

    return convert_to_geodf(final_data)


# ============================================================================================================================================
# UPLOADING DATA
# ============================================================================================================================================


col1, col2 = st.columns([1.2, 1])


with col1:
    st.markdown(
        '<div class="content-headings">Upload Data</div>',
        unsafe_allow_html=True
    )

    uploaded_file = st.file_uploader(
        "Upload CSV, Excel, GeoJSON, KML, or ZIP",
        type=["csv", "xls", "xlsx", "geojson", "kml", "zip"]
    )

    if uploaded_file is not None and uploaded_file.name.lower().endswith((".xls", ".xlsx")):
        st.number_input(
            "Enter the row number containing column headers",
            min_value=1,
            value=1,
            step=1,
            key="header_row"
        )

with col2:
    st.markdown(
        '<div class="content-headings">Data Statistics</div>',
        unsafe_allow_html=True
    )

    if uploaded_file is None:
        st.caption("Upload a file to view dataset statistics.")

if uploaded_file:

    original_name = uploaded_file.name
    file_ext = original_name.split(".")[-1].lower()
    all_dfs = []

    if file_ext == "zip":
        with zipfile.ZipFile(uploaded_file) as zip_ref:

            for f in zip_ref.namelist():

                if f.endswith("/"):
                    continue

                ext = f.split(".")[-1].lower()

                if ext not in ["csv", "xls", "xlsx", "geojson", "json", "kml"]:
                    continue

                with zip_ref.open(f) as file_bytes:
                    data = load_file(file_bytes, ext)

                    if data is not None:
                        all_dfs.append(data)

        if not all_dfs:
            st.error("No valid files found in ZIP.")
            st.stop()

        final_data = pd.concat(all_dfs, ignore_index=True, sort=False)
        base_name = original_name.split(".")[0]

    else:
        final_data = load_file(uploaded_file, file_ext)

        if final_data is None:
            st.error("Failed to read file.")
            st.stop()

        base_name = original_name.split(".")[0]

    with col2:
        stat1, stat2 = st.columns(2)

        with stat1:
            st.metric("Total Rows", f"{final_data.shape[0]:,}")

        with stat2:
            st.metric("Total Columns", f"{final_data.shape[1]:,}")

        st.success("File(s) successfully loaded")
    

    add_divider()

    st.dataframe(
        final_data,
        height=450,
        use_container_width=True
    )
    
# ============================================================================================================================
# DATA DOWNLOAD OPTIONS
# ============================================================================================================================
   
add_divider()

if not final_data.empty:

    st.markdown(
        """
        <div class="content-headings">Download Options</div>
        """,
        unsafe_allow_html=True
    )

    download_col1, download_col2 = st.columns(
    [1, 1],
    vertical_alignment="bottom"
)

    with download_col1:
        download_format = st.selectbox(
            "Select file format",
            ["GeoJSON", "CSV", "Excel", "KML"],
            key="download_format"
        )

    with download_col2:

        if download_format == "CSV":

            csv_data = final_data.to_csv(index=False).encode("utf-8")

            st.download_button(
                "Download CSV",
                data=csv_data,
                file_name=f"{base_name}.csv",
                mime="text/csv",
                key="download_csv",
                use_container_width=True
            )

        elif download_format == "Excel":

            buffer = io.BytesIO()

            with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
                final_data.to_excel(writer, index=False)

            st.download_button(
                "Download Excel",
                data=buffer.getvalue(),
                file_name=f"{base_name}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key="download_excel",
                use_container_width=True
            )

        elif download_format == "GeoJSON":

            if "plot_wkt" not in final_data.columns:
                st.error("Column 'plot_wkt' is required for GeoJSON export.")

            else:
                try:
                    gdf = gpd.GeoDataFrame(
                        final_data.copy(),
                        geometry=final_data["plot_wkt"].apply(
                            lambda x: wkt.loads(x)
                            if pd.notna(x) and str(x).strip() else None
                        ),
                        crs="EPSG:4326"
                    )

                    gdf = gdf[gdf.geometry.notnull()]

                    geojson_data = gdf.to_json().encode("utf-8")

                    st.download_button(
                        "Download GeoJSON",
                        data=geojson_data,
                        file_name=f"{base_name}.geojson",
                        mime="application/geo+json",
                        key="download_geojson",
                        use_container_width=True
                    )

                except Exception as e:
                    st.error(f"GeoJSON export failed: {e}")

        elif download_format == "KML":

            if "plot_wkt" not in final_data.columns:
                st.error("Column 'plot_wkt' is required for KML export.")

            else:
                try:
                    gdf = gpd.GeoDataFrame(
                        final_data.copy(),
                        geometry=final_data["plot_wkt"].apply(
                            lambda x: wkt.loads(x)
                            if pd.notna(x) and str(x).strip() else None
                        ),
                        crs="EPSG:4326"
                    )

                    gdf = gdf[gdf.geometry.notnull()]

                    with tempfile.NamedTemporaryFile(suffix=".kml") as tmp:
                        gdf.to_file(tmp.name, driver="KML")

                        with open(tmp.name, "rb") as f:
                            kml_data = f.read()

                    st.download_button(
                        "Download KML",
                        data=kml_data,
                        file_name=f"{base_name}.kml",
                        mime="application/vnd.google-earth.kml+xml",
                        key="download_kml",
                        use_container_width=True
                    )

                except Exception as e:
                    st.error(f"KML export failed: {e}")
add_divider()
