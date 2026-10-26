# GIS WorkTable Demo Runbook

This runbook corresponds to the [portable sample project](../../frontend/samples/GIS-WorkTable-Competition-Demo.giswork). The competition walkthrough is Mandarin-first for domestic review. The English interface can be selected in Settings → Appearance; no AI model key is needed for the manual GIS workflow.

## Local data and analysis

1. Start the local web workbench with `start.bat`, or follow [the README setup steps](../../README.en.md#run-locally).
2. Open **File → Open project** and choose **Import local .giswork file**. Import `frontend/samples/GIS-WorkTable-Competition-Demo.giswork`.
3. Open **Layers**. Confirm two Polygon layers, `demo-polygons_1.json` and `demo-buffer-500m`, each with three features.
4. Open **Spatial analysis → Buffer**, select `demo-polygons_1.json`, set distance to `500` meters, and run it. The expected output is one new layer with three polygon features.
5. Save the project to the workspace. Refresh the browser, then use **File → Open project → Saved projects → Restore** and confirm both layers return.

To rebuild the result from the input, open **Data → Import local files**, choose `frontend/samples/demo-polygons.json`, and confirm the preview shows three Polygon features and the `name`, `group`, and `score` fields. Then follow steps 3–5.

## Optional: public online-data connectivity

This optional step uses Esri's public US Census sample service. The third-party endpoint may change or become unavailable. Check access and provider terms before using it.

1. Open **Data → Data connectors → Add online data**.
2. Choose **ArcGIS REST vector layer** and enter:

   `https://sampleserver6.arcgisonline.com/arcgis/rest/services/Census/MapServer/1`

3. Keep **Limited preview** selected, click **Fetch**, and wait for the request to finish.
4. The current acceptance retrieved and loaded a preview of 1,000 Polygon / MultiPolygon features. The interface marks completeness as unchecked; this does not confirm that the full layer was downloaded.

If the service is unreachable at the venue, skip this optional step and continue with the portable local project. Catalog search returns metadata from the embedded index and does not establish remote endpoint availability. VPN or proxy needs depend on the venue network and target service. Do not place personal accounts or API keys in demo files.

## Acceptance scope

The Windows local workbench was manually used to import the GeoJSON fixture, run a 500 m buffer, export and import a `.giswork` project, and restore both layers. A 1,000-feature limited preview was also retrieved from the public ArcGIS REST sample service and loaded into the map. Full ArcGIS retrieval, access from all regions, Shapefile or GeoPackage upload, clean-machine installation, and a complete Electron release have not been accepted. See the [core workflow acceptance record](../validation/core-workflow-acceptance-2026-10-25.md).
