# GIS WorkTable

An open-source GIS workbench that brings manual spatial tools, AI-assisted workflows, map views, and project outputs together in one local workspace.

[简体中文 README](README.md) · [Features (Chinese)](docs/features.md) · [Architecture (Chinese)](docs/architecture.md) · [Contributing](CONTRIBUTING.en.md) · [贡献指南](CONTRIBUTING.md) · [Changelog (Chinese)](CHANGELOG.md)

The competition walkthrough is Mandarin-first for domestic review, with the English interface available as a switchable edition. See the [English demo runbook](docs/competition/demo-runbook.en.md) and the [portable sample project](frontend/samples/GIS-WorkTable-Competition-Demo.giswork).

GIS WorkTable is intended for GIS learning, spatial-analysis prototyping, and workflow demonstrations. The project is under active development. Analysis results must be checked against source-data quality, coordinate reference systems, units, and method assumptions.

The AI `execute_python` tool runs code in a local child process with AST checks and a 120-second timeout. These controls are not an operating-system security sandbox and do not isolate local files, network access, or resource use. The built-in launcher binds to `127.0.0.1` by default; do not expose the service to untrusted users or use it as a public multi-tenant service.

## What it does

- **Manual GIS tools:** manage layers, inspect attributes, measure, buffer, overlay, style, and export spatial results. The analysis launcher localizes its title, four categories, and 20 tool names in English.
- **AI-assisted workflows:** describe a task in natural language and let a configured model help organize calls to GIS tools. Manual analysis does not require a model API key.
- **2D and 3D views:** inspect shared project layers with Leaflet and CesiumJS. Online basemaps and services require network access and may have their own terms.
- **Projects and outputs:** save workspaces, restore layers, and exchange project packages or standard GIS data formats.
- **Data connections:** work with local files and supported OGC, ArcGIS REST, and cloud-optimized raster sources, subject to format, network, provider, and licensing constraints.

## Recent maintenance (2026-10-30)

This round continued tracing the data path from inputs through analysis and saved projects:

- **Preserved analysis outputs:** parameter-specific vector and raster runs now keep distinct layer names and files. This includes spatial analysis, the raster calculator, resampling, reprojection, reclassification, and focal statistics.
- **Upload and project recovery:** GeoJSON/GeoTIFF uploads and project import, save, and restore flows now retain exact attributes, original raster assets, and layer state more reliably.
- **UI and data boundaries:** fixes cover history reruns, layer synchronization, failed-upload recovery, export paths, dynamic content, and external requests.
- **Evidence and limits:** see the [module scan log](docs/validation/module-scan-progress.md) and [changelog](CHANGELOG.md) for reproducible checks and remaining validation limits. Passing local tests does not establish that every online service, real model, or full browser workflow has been accepted.

## Recent maintenance (2026-10-27)

- **GeoSource request safety:** authenticated requests stop when redirected to another host. The local proxy keeps API keys out of AI prompts and project files, blocks public-to-private redirects, and limits read-only catalog SQL to 10,000 characters and five seconds.
- **Project and result reliability:** project files remain the source of truth if the recent-project index cannot be written; the UI reports the index warning and can rebuild the listing. Network service areas disclose their convex-hull approximation, and plain chat text is rendered as text.
- **Scope:** see the [module scan log](docs/validation/module-scan-progress.md) for automated checks and remaining validation limits. Passing local checks does not establish that every online service, real model, or full UI workflow has been accepted.

Local uploads preserve backend validation messages. If the server runs out of disk space while writing an upload, it removes the partial file and reports that the upload did not complete; this recovery path is covered by fault-injection tests, not by an actual full-disk run.

Local-file selection was rechecked in an isolated browser and temporary service at `127.0.0.1:8003`: a small GeoJSON and valid `EPSG:4326` GeoTIFF reached the layer panel; an invalid TIFF produced a readable parse error without leaving fragments. A fault-injection proxy then dropped the browser response after the backend had registered a GeoJSON upload. The client recovered that same result by request ID, leaving one layer and one uploaded file. This verifies recovery for a reproduced response-loss path, but does not identify the exact cause of the original `Failed to fetch` on port 8000. No file was uploaded to that service.

## Requirements

- Python 3.11 or newer; Python 3.13 was used for the Windows acceptance record.
- A modern browser for the web workbench.
- Node.js and npm only for the experimental Electron desktop shell.
- A compatible model service and credentials only for AI-assisted workflows.

## Run locally

On Windows 64-bit, `start.bat` prepares the local Python environment and starts the workbench. The first run needs network access to install dependencies and a writable project directory.

For a manually prepared environment, run these commands from the repository root:

```bash
python -m venv .venv
```

Activate the environment, then install dependencies and start the local server:

```bash
python -m pip install -r backend/requirements.txt
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

Open <http://127.0.0.1:8000> in a browser. The launcher and dependency setup are currently documented and primarily verified on Windows. Other operating systems may require platform-specific dependency setup.

## Reproduce the sample buffer workflow

1. Open **Home** and load **Sample polygons**, or open **Data** → **Import local files** and choose [`frontend/samples/demo-polygons.json`](frontend/samples/demo-polygons.json). The local-file preview should show three polygon features and the `name`, `group`, and `score` fields.
2. Open **Layers** and confirm the selected polygon layer contains three features.
3. Open **Spatial analysis** → **Buffer**, select the layer, keep the distance at `500` meters, and run the operation.
4. Confirm the new buffer layer appears with three features. Save the project, refresh the browser, and reopen it from **Recent projects** to inspect the restored layers.

The built-in sample, local GeoJSON chooser, 500 m buffer, and project refresh/reopen flow were manually accepted in the recorded Windows browser session. The local-file result covers this small GeoJSON fixture only; it does not verify Shapefile, GeoPackage, large-file, or other format upload paths.

## Online data connections

Open **Data** → **Data connectors**, or **Settings** → **Geospatial services** → **Add online data**. Paste an HTTP(S) URL and choose a format, or leave format detection on. The current connector lists COG / remote GeoTIFF, PMTiles, GeoParquet, FlatGeobuf, and ArcGIS REST vector layers. For ArcGIS REST, inspect the layer first; the limited preview does not establish completeness, while the full-fetch option checks object IDs. Service availability, cross-origin access, authentication, quotas, and license terms remain provider-specific.

The embedded GeoSource catalog searches a selected local SQLite snapshot. The UI shows the snapshot file time and each record's stored status; neither is a live availability check. If a provider supports API keys in URL query parameters, users can enter one for a connection. GeoSource requests go through the local WorkTable proxy; a key is forwarded only to the original provider, not to AI, and is not saved in the project. An authenticated request stops if redirected to another host; use the provider's direct URL instead. The proxy allows a user-selected private service and blocks a public service from redirecting to a private or loopback address. Read-only catalog SQL is limited to 10,000 characters and five seconds. Header auth, OAuth, and username/password are not supported.

Model Provider API keys are stored in browser storage. Each chat request or connection test sends the selected key to the connected WorkTable backend, which uses it to contact the selected model provider; the key is not saved in projects or backend settings. Public model endpoints must use HTTPS; HTTP remains available for localhost or endpoints that resolve clearly to a private network, but private HTTP traffic is unencrypted and should only be used on a trusted local network. A configured custom proxy also receives model requests, including requests to private model addresses. If WorkTable is hosted remotely, the key is sent to that remote backend, so use a deployment you trust.

## Coordinate systems and units

Check a layer's CRS and coordinate units before running distance- or area-based analysis. A distance entered in meters is meaningful only when the tool's CRS handling and input coordinates support that interpretation. GIS WorkTable does not replace domain review of analytical assumptions or results.

## Internationalization status

English UI strings cover the main workbench navigation, data and tool panels, layer list, buffer workflow, project dialogs, common map controls, online connector settings, and the GeoSource catalog search controls and actions. Project and sample names and some provider-supplied descriptions remain in their source language. Many advanced tools, settings, runtime errors, and help surfaces still need translation. Analysis units are shown explicitly (meters or kilometers); this does not imply locale-based unit conversion. Online data sources depend on provider availability, network access, authentication, and service terms. Treat the international edition as in progress until the remaining UI, documentation, and clean-environment workflow are reviewed.

## Verification and known limits

The recorded Windows browser acceptance covers importing the repository's local GeoJSON fixture, running a 500 m buffer, rejecting invalid distances, exporting and importing a portable `.giswork` project, restoring project layers, loading a public remote COG raster, and retrieving a 1,000-feature ArcGIS REST preview. The ArcGIS preview does not check completeness. Evidence and exact boundaries are in [the core workflow acceptance record](docs/validation/core-workflow-acceptance-2026-10-25.md).

An additional Windows browser check on 2026-10-26 used an SRTM-derived EPSG:4326 DEM to produce terrain rasters, save and reopen the project, and run slope analysis again after restoration. Raster sources, CRS, value units, and quality notes were visible in the layer inspector. The GeoTIFF for that round-trip check was supplied through the local API after a browser file-picker attempt returned `Failed to fetch`; its cause remains unresolved. A separate isolated browser check later uploaded a small GeoJSON and a valid-CRS GeoTIFF through the file chooser and displayed both in the layer panel/map. That isolated success does not reproduce or resolve the failure in the original 8000-page context. These small-area checks do not validate terrain accuracy or business suitability. A real model call and a full Electron release also remain unverified. Remote services may be unavailable or change independently. Check [the tool validation record](docs/tool-validation.md) and [the module scan progress](docs/validation/module-scan-progress.md) for additional evidence and limits.

Local regression recheck on 2026-10-26: 261 frontend tests passed; 1,430 backend tests passed, 5 were skipped, and none failed (17 warnings). These automated results do not stand in for remote-service, real-model, or full-browser validation.

## Open-source license

Project code is distributed under the [MIT License](LICENSE). Third-party dependencies, map services, imagery, and datasets remain subject to their own licenses and terms.
