# Domain Interface Contracts & Modular Refactoring Specification

**Document Version**: 1.0.0  
**Target Milestone**: Milestone 2 (Domain Modularization)  
**Author**: Agent A (Architecture & Integration Lead)  
**Applicable Agents**: Agent B (Vector & Network Implementer), Agent C (Raster & Terrain Implementer), Agent D (QA & Regression Auditor)  

---

## 1. Architectural Architecture & Dependency Hierarchy

All refactoring adheres to a strict four-layer unidirectional dependency architecture to mathematically prevent circular dependencies:

```text
 ┌────────────────────────────────────────────────────────┐
 │   Layer 3: backend/services/tools.py                  │
 │   - Unified Compatibility Facade & AI Tool Registry    │
 │   - _ToolsFacadeModule dynamic proxy                   │
 └───────────────────────────┬────────────────────────────┘
                             │ imports domain tools
                             ▼
 ┌────────────────────────────────────────────────────────┐
 │   Layer 2: Domain Modules                              │
 │   - Agent B: vector.py, network.py                    │
 │   - Agent C: raster.py, terrain.py, map_ops.py         │
 │   - workflow_tools.py: stateless workflow execution    │
 └───────────────────────────┬────────────────────────────┘
                             │ imports shared state & helpers
                             ▼
 ┌────────────────────────────────────────────────────────┐
 │   Layer 1: backend/services/tool_modules/runtime.py   │
 │   - Shared map layer state (_registered_layers, etc.)  │
 │   - State locks & concurrency controls                 │
 │   - GIS layer conversion & registration helpers        │
 └───────────────────────────┬────────────────────────────┘
                             │ imports pure stateless utilities
                             ▼
 ┌────────────────────────────────────────────────────────┐
 │   Layer 0: backend/services/tool_modules/common.py    │
 │   - Pure geometry math, bbox, fid, AST validators      │
 └────────────────────────────────────────────────────────┘
```

### Strict Dependency Rules
Validation errors returned as plain text must start with `错误：` (or an existing explicit failure prefix). API responses, processing history, and workflow execution classify these returned values; an explanatory sentence alone can otherwise be recorded as success. Keep successful summaries free of an error prefix.

1. **Zero Circular Imports**: Domain modules (`vector.py`, `network.py`, `raster.py`, `terrain.py`, `map_ops.py`) MUST NEVER import `backend.services.tools` or `tools`.
2. **Layer Invariance**:
   - `Layer 0 (common.py)` depends ONLY on the standard library and pure math libraries.
   - `Layer 1 (runtime.py)` depends ONLY on `common.py`, standard libraries, and foundational GIS libraries (`geopandas`, `shapely`).
   - `Layer 2 (domain modules)` depend on `runtime.py`, `common.py`, and third-party domain libraries (`scipy`, `numpy`, `rasterio`, `networkx`, `matplotlib`, etc.). `map_ops.py` owns layer-control and map-focus business logic, accessing runtime state dynamically through the runtime module so module-level mutable state is never copied. Network and terrain tools reuse the shared raster lookup/output helpers through one-way imports into `raster.py`; raster must not import network or terrain. Do not copy these helpers into domain modules, where state handling can diverge. `workflow_tools.py` owns workflow-step execution, DAG execution/event formatting, and materialization formatting; the facade injects the public tool list, workflow factory/validator/executor, layer registration and snapshot callbacks, failure classifier, stream-writer provider, current task ID, workflow-history loader, and saver so registry, task-state, error, and event-stream semantics are preserved without a reverse import.
   - `Layer 3 (tools.py)` imports domain functions, binds `@tool` wrappers, maintains the public tool list, and delegates attribute accesses to `runtime.py`.
   - `io_export.py` owns file-export implementations plus map/PDF export-operation queueing. `tools.py` retains decorated compatibility wrappers and passes its authoritative `_pending_layer_ops` object explicitly; `io_export.py` must not create a second queue or import the facade.
   - `map_ops.py` owns layer-control and map-focus implementations. It accesses the authoritative runtime module state directly; `runtime.py` must not import `map_ops.py`, and `map_ops.py` must not import the `tools.py` facade.

---

## 2. Shared Runtime State & Common Utility Contracts

All domain implementations must access shared state and helper methods exclusively through `runtime.py` and `common.py`.

### 2.1 Importing from `backend.services.tool_modules.runtime`
```python
from backend.services.tool_modules.runtime import (
    # Shared State & Concurrency Controls
    _registered_layers,      # dict: The authoritative map layer registry
    _pending_layers,         # list: Layers queued for frontend transmission
    _pending_layer_ops,      # list: Operation logs queued for frontend
    _pending_images,         # list: Images/HTML artifacts queued for frontend
    _pending_qa_warnings,    # list: Quality assessment warnings
    _state_lock,             # threading.RLock: Thread-safe lock for state mutations
    _shared_state_lock,      # threading.Lock: Global process-level lock
    _temp_output_dir,        # str: Absolute path to session temporary artifacts
    _workspace_dir,          # str: Absolute path to workspace directory
    _raster_output_scope,    # threading.local: Scoped raster output tracking

    # Core GIS Conversion & Registration Helpers
    _layer_to_gdf,           # (layer_name: str) -> (gdf, resolved_name) or (None, err_msg)
    _gdf_to_layer,           # (gdf, name: str, style: dict = None, provenance: dict = None) -> None
    _push_layer,             # (name: str, geojson: dict, style: dict = None, provenance: dict = None) -> None
    _register_layer,         # (name: str, geojson: dict, ...) -> token or None on expected-token mismatch
    _register_raster_layer,  # (name: str, raster: dict, ...) -> token or None on expected-token mismatch
    _unregister_layer,       # (name: str, registration_token: str = None) -> bool
    _disambiguate_layer_name,# (base_name: str) -> str
    _update_registered_layer_data, # (name: str, geojson: dict) -> None
    _get_exact_registered_layer,   # (name: str) -> (name, layer_dict, err_msg); lookup holds _state_lock
    _add_pending_item,       # (url: str, file_path: str = None) -> None
    init_temp_dir,           # () -> None
)
```

### 2.2 Map operations
`map_ops.py` implements `layer_control` and `focus_map` behavior on top of the single runtime state owner. Import those implementations from `backend.services.tool_modules.map_ops`; do not duplicate registry or queue objects.

For HTTP re-registration, `expected_registration_token` is checked inside `_state_lock` when provided. A mismatch or missing current version returns `None` without replacing registry data; callers that omit it retain the legacy unconditional registration behavior.

### 2.3 Importing from `backend.services.tool_modules.common`
```python
from backend.services.tool_modules.common import (
    _compute_bbox,
    _extract_coords,
    _extract_geometry_type,
    _geometry_to_wkt,
    _wkt_to_geometry,
    _layer_property_examples,
    _make_fid,
    _normalize_fid,
    _normalize_geojson,
    _normalize_layer_provenance,
    _parse_iso_datetime,
    _safe_layer_export_stem,
    _sanitize_property_name,
    _valid_registration_geometry,
    _validate_ast,
    _validate_field_calculation_ast,
    _validate_wgs84_geojson,
)
```

### 2.3 Rules for State Mutation
- **DO NOT Rebind State**: Domain modules must never execute `_registered_layers = {}`. Always modify in place (`_registered_layers.clear()`, `_registered_layers[name] = ...`) or invoke `_register_layer` / `_unregister_layer`.
- **Lock Protection**: Any read or write of `_registered_layers` or `_pending_layers` spanning multiple operations must be enclosed in `with _state_lock:`.

---

## 3. Agent B Contracts: Vector & Network Domains

### 3.1 Module Target: `backend/services/tool_modules/vector.py`

Agent B is exclusively responsible for creating and maintaining `vector.py`.

#### Dedicated Helper Functions to Migrate:
- `_to_local_metric_gdf(gdf)`: Projects GDF to local UTM coordinate reference system.
- `_spatial_feature_coordinates(gdf)`: Extracts coordinate points from point/multipoint features.
- `_gdf_area_km2(gdf, unique=False)`: Computes surface area in km² using EPSG:6933.

#### Tools to Migrate (57 tools, including attribute and geometry-edit migrations):
| Tool Name | Key Arguments | Return / Behavior |
|:---|:---|:---|
| `spatial_buffer` | `layer_name`, `distance`, `unit`, `dissolve` | Buffers vector features by metric distance. |
| `spatial_multi_ring_buffer` | `layer_name`, `distances`, `unit`, `dissolve` | Creates concentric multi-ring buffer zones. |
| `spatial_intersect` | `layer_a`, `layer_b` | Computes geometric intersection between two layers. |
| `spatial_union` | `layer_a`, `layer_b` | Computes geometric union between two layers. |
| `spatial_difference` | `layer_a`, `layer_b` | Computes geometric difference (layer_a - layer_b). |
| `spatial_clip` | `layer_name`, `clip_layer` | Clips vector features using boundary polygon. |
| `spatial_centroid` | `layer_name` | Calculates centroids of geometries. |
| `spatial_simplify` | `layer_name`, `tolerance` | Douglas-Peucker geometry simplification. |
| `spatial_dissolve` | `layer_name`, `by_field` | Merges geometries sharing common attribute or all. |
| `spatial_select` | `target_layer`, `source_layer`, `predicate` | Spatial predicate selection (intersects, within, etc.). |
| `spatial_sample` | `layer_name`, `n`, `method` | Random, stratified, or systematic spatial sampling. |
| `spatial_near` | `layer_name`, `target_layer`, `max_distance` | Calculates distance to nearest features. |
| `nearest_pair` | `layer_name`, `target_layer`, `feature_filter`, `target_filter` | Identifies closest pair of entities with distance line. |
| `spatial_cluster` | `layer_name`, `n_clusters`, `method` | DBSCAN, KMeans, or Agglomerative spatial clustering. |
| `spatial_voronoi` | `layer_name`, `clip_extent` | Voronoi / Thiessen polygon generation from points. |
| `spatial_field_stats` | `layer_name`, `field` | Descriptive statistics (mean, std, min, max, percentiles). |
| `spatial_join` | `target_layer`, `join_layer`, `how`, `predicate` | Spatial join of attributes based on spatial relations. |
| `layer_merge` | `layer_names` | Concatenates multiple vector layers into one. |
| `layer_split` | `layer_name`, `by_field` | Splits layer into distinct layers based on attribute. |
| `layer_add_geometry` | `layer_name`, `geometry_type`, `coordinates` | Adds new geometry feature to existing layer. |
| `spatial_select_by_attribute` | `layer_name`, `where` | SQL-like / pandas query filter on attributes. |
| `topology_check` | `layer_name`, `checks` | Audits geometries for overlaps, self-intersections, gaps. |
| `spatial_fix_geometry` | `layer_name`, `method` | Repairs invalid geometries using `make_valid` / buffer(0). |
| `spatial_check_duplicates`| `layer_name`, `fields`, `geometry_check` | Finds and flags duplicate attributes or geometries. |
| `spatial_explode` | `layer_name` | Explodes MultiPart geometries into SinglePart features. |
| `geometry_convert` | `layer_name`, `to_type` | Converts geometry representations (e.g. polygon to line). |
| `join_field` | `target_layer`, `join_layer`, `target_field`, `join_field`, `fields` | Joins table attributes based on common key field. |
| `geometry_attributes` | `layer_name`, `attributes` | Injects geometry attributes (length, perimeter, area, xy). |
| `minimum_bounding_geometry` | `layer_name`, `geometry_type` | Computes convex hull, envelope, or minimum bounding box. |
| `points_to_line` | `layer_name`, `sort_field`, `group_field` | Connects ordered points to construct polylines. |
| `generate_points_along_lines` | `layer_name`, `distance`, `unit` | Generates equidistant station points along line paths. |
| `spatial_weights_matrix` | `layer_name`, `method`, `k` | Constructs spatial weights matrix (Queen, Rook, KNN). |
| `spatial_regression` | `layer_name`, `dependent_var`, `independent_vars` | OLS and Spatial Error/Lag regression. |
| `spatial_moran` | `layer_name`, `field`, `weight_type`, `threshold`, `k`, `local`, `threshold_m` | Computes global Moran's I and optional local LISA clusters. |
| `spatial_hotspot` | `layer_name`, `field`, `threshold`, `threshold_m` | Computes Getis-Ord Gi* hotspots and coldspots. |
| `spatial_kde` | `layer_name`, `bandwidth`, `grid_size`, `bandwidth_m`, `metric_units` | Estimates point-event density and registers a density grid layer. |
| `measure_distance` | `lon1`, `lat1`, `lon2`, `lat2` | Computes WGS-84 Haversine distance and returns meters/km. |
| `measure_area` | `layer_name` | Measures feature area with local UTM or WGS-84 ellipsoidal area. |
| `convert_coordinates` | `coords`, `source_crs`, `target_crs` | Converts coordinate pairs between CRSs, including automatic UTM selection; validates EPSG:3857 source and target coordinates against its declared area of use. |
| `convert_crs` | `layer_name`, `target_crs` | Reprojects a registered vector layer into a target CRS and registers a new layer; rejects Web Mercator inputs outside its declared area of use. |
| `add_length_field` | `layer_name`, `field_name` | Calculates per-feature projected length and registers an output vector layer. |
| `edit_vertices` | `layer_name` | Queues frontend vertex-edit mode for a registered vector layer. |
| `draw_feature` | `geometry_type`, `coordinates`, `layer_name` | Creates and registers a point, line, polygon, rectangle, or circle layer. |
| `add_legend` | `layer_name` | Queues a legend for a registered vector layer using its symbology. |
| `update_attribute` | `layer_name`, `field`, `value`, `condition_field`, `condition_value` | Updates attributes on all or matching features and syncs the registered layer. |
| `delete_features` | `layer_name`, `condition_field`, `condition_value` | Deletes matching features while retaining at least one feature in the registered layer. |
| `add_field` | `layer_name`, `field_name`, `field_type`, `default_value` | Adds a typed attribute to all features while preserving existing properties. |
| `delete_field` | `layer_name`, `field_name` | Removes an attribute field; protects geometry and stable `_fid` identity. |
| `move_features` | `layer_name`, `dx`, `dy`, `unit` | Translates all vector features in local metric coordinates. |
| `rotate_features` | `layer_name`, `angle` | Rotates vector features around their projected geometry center. |
| `scale_features` | `layer_name`, `x_factor`, `y_factor` | Scales features around their projected geometry center. |
| `add_labels` | `layer_name`, `field`, `font_size`, `color` | Queues per-feature text labels using a selected attribute field. |
| `spatial_graduated_colors` | `layer_name`, `field`, `n_classes`, `color_scheme`, `method`, `fill_opacity` | Queues numeric graduated symbology with equal-interval or quantile breaks. |
| `spatial_unique_values` | `layer_name`, `field`, `color_scheme` | Queues categorical symbology while preserving typed category distinctions. |
| `directional_distribution`| `layer_name`, `weight_field`, `std_dev` | Computes standard deviational ellipse (SDE). |
| `central_tendency` | `layer_name`, `method` | Mean center, median center, or central feature. |
| `create_fishnet` | `bounds`, `cell_width`, `cell_height`, `cell_type` | Creates regular square or hexagonal grid fishnet. |

---

### 3.2 Module Target: `backend/services/tool_modules/network.py`

Agent B is exclusively responsible for creating and maintaining `network.py`.

#### Tools to Migrate (6 tools):
| Tool Name | Key Arguments | Return / Behavior |
|:---|:---|:---|
| `download_road_network` | `place_name`, `network_type`, `buffer_dist` | Downloads road network via OSMnx / Overpass API. |
| `network_analysis` | `network_source`, `start_coord`, `end_coord`, `weight` | Shortest path, travel time, and route turn directions. |
| `od_cost_matrix` | `origins_layer`, `destinations_layer`, `network_source`, `weight` | Computes all-to-all Origin-Destination impedance matrix. |
| `metro_line` | `city`, `line_name` | Retrieves transit metro line alignment and station points. |
| `cost_distance` | `source_layer`, `cost_surface`, `max_distance` | Calculates accumulated cost distance from sources over surface. |
| `least_cost_path` | `cost_distance_surface`, `destination_layer` | Traces least-cost path downhill from destination to source. |

---

## 4. Agent C Contracts: Raster & Terrain Domains

### 4.1 Module Target: `backend/services/tool_modules/raster.py`

Agent C is exclusively responsible for creating and maintaining `raster.py`.

#### Tools to Migrate (20 tools):
| Tool Name | Key Arguments | Return / Behavior |
|:---|:---|:---|
| `ndvi_analysis` | `nir_band`, `red_band`, `output_layer_name` | Normalized Difference Vegetation Index calculation. |
| `raster_calculator` | `expression`, `rasters`, `output_layer_name` | Map algebra evaluation over multiple raster bands. |
| `spatial_interpolate` | `points_layer`, `value_field`, `method`, `resolution` | IDW, Kriging, or TIN surface interpolation. |
| `clip_raster` | `raster_layer_name`, `clip_layer_name` | Masking and clipping raster using vector geometry bounds. |
| `calc_spectral_index` | `index_name`, `bands`, `output_layer_name` | Universal spectral index calculator. |
| `ndwi_analysis` | `green_band`, `nir_band` | Normalized Difference Water Index. |
| `ndbi_analysis` | `swir_band`, `nir_band` | Normalized Difference Built-up Index. |
| `evi_analysis` | `nir_band`, `red_band`, `blue_band` | Enhanced Vegetation Index. |
| `ndmi_analysis` | `nir_band`, `swir_band` | Normalized Difference Moisture Index. |
| `zonal_statistics` | `zone_layer`, `raster_layer`, `stats` | Summary statistics (mean, sum, std) per vector polygon zone. |
| `raster_resample` | `raster_layer_name`, `scale_factor`, `method` | Resampling cell size via nearest, bilinear, or cubic. |
| `raster_reproject` | `raster_layer_name`, `target_crs` | Reprojects raster to different spatial reference system. |
| `raster_reclassify` | `raster_layer_name`, `reclass_rules` | Reclassifies continuous pixel values into discrete classes. |
| `raster_focal_stats` | `raster_layer_name`, `window_size`, `stat` | Moving window neighborhood analysis (focal mean, max, etc.). |
| `euclidean_distance` | `source_layer`, `cell_size`, `max_distance` | Computes straight-line Euclidean distance raster. |
| `raster_extract_by_mask` | `raster_layer_name`, `mask_layer_name` | Extracts raster cells falling within polygon mask. |
| `feature_to_raster` | `layer_name`, `value_field`, `cell_size` | Vector-to-raster rasterization. |
| `raster_to_feature` | `raster_layer_name`, `connectedness` | Raster-to-vector polygon polygonization. |
| `load_cog` | `url`, `layer_name` | Cloud-Optimized GeoTIFF streaming and header inspection. |
| `get_cog_info` | `url` | Metadata and band overview inspection for COG datasets. |

---

### 4.2 Module Target: `backend/services/tool_modules/terrain.py`

Agent C is exclusively responsible for creating and maintaining `terrain.py`.

#### Tools to Migrate (7 tools):
| Tool Name | Key Arguments | Return / Behavior |
|:---|:---|:---|
| `dem_analysis` | `dem_layer_name`, `analysis_type` | Slope (度/百分比), Aspect (坡向), Hillshade (山体阴影). |
| `hydrology_analysis` | `dem_layer_name`, `flow_dir`, `flow_acc` | D8 flow direction, flow accumulation, stream network. |
| `view_3d_terrain` | `dem_layer_name`, `texture_layer_name` | Generates 3D terrain mesh payload for frontend Cesium viewer. |
| `terrain_profile` | `dem_layer_name`, `line_layer_name` | Samples elevation along 2D line to yield elevation profile. |
| `extract_contours` | `dem_layer_name`, `interval`, `base_contour` | Isohypse / contour line extraction into vector polyline layer. |
| `get_elevation_data` | `bounds`, `resolution` | Downloads and mosaics open-access elevation datasets. |
| `surface_volumes` | `dem_layer_name`, `base_height`, `direction` | Cut and fill volumetric analysis above/below reference plane. |

---

## 5. Integration Protocols for Agent B and Agent C

### 5.1 Authoritative Decorator & Facade Compatibility
1. **Preserve `@tool` Signature & Name**:
   Each tool implementation must retain its exact function name, arguments, types, defaults, and docstrings.
2. **Tools Export in Domain Modules**:
   Each domain module should declare its public tools in `__all__`:
   ```python
   __all__ = [
       "spatial_buffer",
       "spatial_multi_ring_buffer",
       ...
   ]
   ```
3. **Re-export in `backend/services/tools.py`**:
   Agent A will import each migrated tool from the domain modules into `tools.py` to maintain backward compatibility:
   ```python
   from backend.services.tool_modules.vector import (
       spatial_buffer,
       spatial_multi_ring_buffer,
       ...
   )
   ```
4. **Tool Registry Invariance**:
   The `tools = [_recorded(t) for t in tools]` list in `backend/services/tools.py` MUST maintain its 153 tools in identical order.
   `test_source_definition_count_matches_registry` will continue to pass because Agent A maintains the facade registration.

### 5.2 Verification Commands for Domain Modules
Prior to reporting task completion, each agent must execute:
```powershell
$env:PYTHONPATH="E:\my_repo\Gis-WorkTable"; $env:OPENBLAS_NUM_THREADS="1"; .venv\Scripts\python.exe -m pytest backend/tests/test_tool_registry.py backend/tests/layered/test_layer1_unit.py backend/tests/test_spatial_tools.py -q
```
Verify zero circular imports:
```powershell
.venv\Scripts\python.exe -c "import sys; from backend.services.tool_modules import vector; assert 'backend.services.tools' not in sys.modules; print('VECTOR_ISOLATION_OK')"
.venv\Scripts\python.exe -c "import sys; from backend.services.tool_modules import network; assert 'backend.services.tools' not in sys.modules; print('NETWORK_ISOLATION_OK')"
.venv\Scripts\python.exe -c "import sys; from backend.services.tool_modules import raster; assert 'backend.services.tools' not in sys.modules; print('RASTER_ISOLATION_OK')"
.venv\Scripts\python.exe -c "import sys; from backend.services.tool_modules import terrain; assert 'backend.services.tools' not in sys.modules; print('TERRAIN_ISOLATION_OK')"
```
