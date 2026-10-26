# GIS WorkTable

An open-source GIS workbench that brings manual spatial tools, AI-assisted workflows, map views, and project outputs together in one local workspace.

[简体中文 README](README.md) · [Features (Chinese)](docs/features.md) · [Architecture (Chinese)](docs/architecture.md) · [Contributing](CONTRIBUTING.en.md) · [贡献指南](CONTRIBUTING.md) · [Changelog (Chinese)](CHANGELOG.md)

The competition walkthrough is Mandarin-first for domestic review, with the English interface available as a switchable edition. See the [English demo runbook](docs/competition/demo-runbook.en.md) and the [portable sample project](frontend/samples/GIS-WorkTable-Competition-Demo.giswork).

GIS WorkTable is intended for GIS learning, spatial-analysis prototyping, and workflow demonstrations. The project is under active development. Analysis results must be checked against source-data quality, coordinate reference systems, units, and method assumptions.

## What it does

- **Manual GIS tools:** manage layers, inspect attributes, measure, buffer, overlay, style, and export spatial results.
- **AI-assisted workflows:** describe a task in natural language and let a configured model help organize calls to GIS tools. Manual analysis does not require a model API key.
- **2D and 3D views:** inspect shared project layers with Leaflet and CesiumJS. Online basemaps and services require network access and may have their own terms.
- **Projects and outputs:** save workspaces, restore layers, and exchange project packages or standard GIS data formats.
- **Data connections:** work with local files and supported OGC, ArcGIS REST, and cloud-optimized raster sources, subject to format, network, provider, and licensing constraints.

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

The embedded GeoSource catalog searches indexed WMS, XYZ, and REST endpoints. Catalog entries can become stale; inspect the service metadata and provider terms before using them. Provider credentials can be configured under **Settings** → **Geospatial services**. The settings screen includes global and China-region providers; availability and signup requirements may vary by country.

## Coordinate systems and units

Check a layer's CRS and coordinate units before running distance- or area-based analysis. A distance entered in meters is meaningful only when the tool's CRS handling and input coordinates support that interpretation. GIS WorkTable does not replace domain review of analytical assumptions or results.

## Internationalization status

English UI strings cover the main workbench navigation, data and tool panels, layer list, buffer workflow, project dialogs, common map controls, online connector settings, and the GeoSource catalog search controls and actions. Project and sample names and some provider-supplied descriptions remain in their source language. Many advanced tools, settings, runtime errors, and help surfaces still need translation. Analysis units are shown explicitly (meters or kilometers); this does not imply locale-based unit conversion. Online data sources depend on provider availability, network access, authentication, and service terms. Treat the international edition as in progress until the remaining UI, documentation, and clean-environment workflow are reviewed.

## Verification and known limits

The recorded Windows browser acceptance covers importing the repository's local GeoJSON fixture, running a 500 m buffer, rejecting invalid distances, exporting and importing a portable `.giswork` project, restoring project layers, loading a public remote COG raster, and retrieving a 1,000-feature ArcGIS REST preview. The ArcGIS preview does not check completeness. Evidence and exact boundaries are in [the core workflow acceptance record](docs/validation/core-workflow-acceptance-2026-10-25.md).

That acceptance does not establish Shapefile/GeoPackage or large-file upload, a DEM analysis journey through result display and project restoration, a full Electron release, or a real AI model call. Remote services may be unavailable or change independently. Check [the tool validation record](docs/tool-validation.md) and [the module scan progress](docs/validation/module-scan-progress.md) for additional evidence and limitations.

## Open-source license

Project code is distributed under the [MIT License](LICENSE). Third-party dependencies, map services, imagery, and datasets remain subject to their own licenses and terms.
