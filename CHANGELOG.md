# Changelog

All notable changes to this project will be documented in this file.

## [0.5.0] - 2026-09-25

### Added
- **Complex QGIS styles reach the app.** Each layer's symbology is prepared before its SLD is exported, so what QGIS's exporter cannot carry no longer leaves the layer with no style (or, for some, drawing nothing): nested `ELSE` rules, gradient fills, SVG and font markers, heatmaps, point clusters, inverted polygons and label expressions are approximated by the closest thing GeoServer draws, and the run log lists what was approximated (`[STYLE] <layer>: ...`). Hatch, dot-pattern and marker-line fills, all QGIS marker shapes, rule filters using `upper`/`lower`/`length`... and hillshade rasters now render too.
- **"Web app" box** (main dialog): the app's title, logo, colour and basemap, and switches for the map search (with an optional OpenStreetMap place lookup), the legend and the data downloads. Saved per project.
- **Popups like QGIS**: field aliases, hidden attribute-table columns, value-map labels and a simple map tip reach the generated app; the display field names the features in search results and lists.
- **Editable layers** (new column in the Layers table): visitors of the app can add, move and delete that layer's features on the map with a generated editing password, shown when the deployment ends. A redeploy keeps their edits unless "A redeploy replaces the edits made in the web app" is on.
- **Time slider** for layers with QGIS temporal settings (time from a date field, or a start and an end field).
- **Update data only** (Deploy, local and SSH): reloads the data of the app already deployed from here, in seconds, when the layers and fields are unchanged.
- **AWS sign-in by access keys or by an AWS profile**; keys can be remembered in the QGIS password manager and are passed to the CLI as environment variables instead of being written to a file.
- Layers the plugin cannot publish (mesh, vector tile, point cloud) are listed greyed out with the reason instead of missing; nested QGIS groups keep their full path.

### Changed
- The map search is a magnifier button in the generated app's right-hand controls (it opens the field and its suggestions to the left of the buttons) instead of a bar above the map. *(mini-lps)*
- A redeploy updates the styles already in GeoServer (they used to stay as first deployed) and republishes a layer left half-published by a failed deploy. *(mini-lps)*

### Fixed
- Histogram charts never rendered (Vega's `bin` needs an extent).
- Charts on a field with an underscore in its name (`obs_date`) were empty: the app exposes `obsDate`.
- Layer names with accents lost their accented letter in the generated app (`Árboles` became `rboles`), which broke their charts; names are now ASCII from the start.
- Saved charts on a layer whose name does not end in "s" (`landuse`) requested a wrong URL. *(mini-lps)*
- Heatmap legends did not show (two copies of `vega-scale` in the client). *(mini-lps)*
- The generated map opened on the whole world when the project had an XYZ or WMS basemap and no saved view extent.

### Requires
- `gispublisher` 1.7.1 or later (it brings mini-lps 0.6.1).

## [0.4.1] - 2026-09-24

### Added
- **Geoprocessing models now run in the generated app.** Selected models are served by the product's QGIS WPS container and can be run from the map's toolbox. If no model is selected, the product's demo model is shipped instead.
- **Model preflight warnings**, in each model's tooltip (with a warning icon) and in the pre-run confirm dialog; click a model or chart with warnings to read them in a dialog:
  - steps from a Processing provider the app's container doesn't have (only `native`, `qgis` and `gdal` exist);
  - vector inputs no published layer can satisfy (e.g. a polygon input with only point layers);
  - fixed distances (e.g. a 2000 buffer) that the app would read as degrees, because it stores and processes data in EPSG:4326.
- **"Run models in CRS"** (Models tab): the CRS the generated app runs models in, e.g. `EPSG:25829`. Empty means the QGIS project's CRS when that is projected, else EPSG:4326. Saved per project.
- **QGIS spatial bookmarks** are exported and shown as a bookmarks menu in the generated map viewer.
- **Scale-based visibility** (min/max scale) now reaches the generated map as per-layer zoom limits.
- **"Use the project CRS for the web map"** (experimental, off by default): builds the web map in the project's projected CRS; the OpenStreetMap base layer is left out of it.
- **XYZ tile layers** (OpenTopoMap, Stamen, any `{z}/{x}/{y}` service) are now published as tile overlays in the generated app, keeping their QGIS order, visibility, opacity, scale limits and zoom range. Quadkey (`{q}`) URLs and non-http(s) URLs are still refused, with the reason.
- **Raster styles.** A local raster with a singleband gray/pseudocolor, paletted or multiband renderer publishes its QGIS style (colour ramp, contrast) as an SLD; other renderers use GeoServer's default raster style. The layer table's tooltip says which.
- **Rasters in a non-EPSG CRS** are reprojected to EPSG:4326 when staged (GeoServer only knows EPSG codes).
- **Deploys run in the background.** The progress window has a **Run in background** button; the run keeps going (also with the main dialog closed), shows up in the QGIS task manager with its progress (and can be cancelled from there) and ends with a message-bar notification (**Open app** / **Open folder** / **Details**). One run at a time; the main window's button becomes **Show progress…** meanwhile.
- **A readable progress window** for Generate and Deploy: a list of steps with status and duration, a step-measured progress bar, the state of each service while the app starts, and a result panel with the app URL (**Open app**, **Copy link**, **Open folder**). The raw Docker/CLI output is under **Show details** (opened automatically when a run fails).
- **Plain-language failures**: Docker not running/installed, port already in use, SSH authentication failed, server unreachable, sudo needed, a service that did not start, etc., each with a hint.
- **Deploy form validation**: the host must not be a URL and the remote folder must be a safe absolute path (it is emptied on every deploy).
- Each deploy has a **persistent per-app folder** under the QGIS profile (`GISPublisher/deployments/<app>`), recorded in History, instead of a shared temp folder.

### Changed
- The project manifest (`qgis-project.json`) also carries the project CRS, bookmarks, the processing-CRS choice and the display-CRS flag.
- Local rasters are named `r_<name>` in GeoServer, and the generated app now asks for that name (it used to ask for a different one, so a GeoTIFF never showed). They are also uploaded on Generate + `docker compose up`, not only on Deploy.
- A layer named `raster` is now flagged by the preflight: `RASTER` is a keyword of the layer DSL.
- A deploy now ends when every service is healthy (one-shot services such as the data importer must have exited successfully), not when the containers merely started.
- Cancel also stops what the CLI started (docker compose, ssh), and works while layers are still being staged.
- `GISPublisherRunner` no longer touches any widget: it emits signals, and a `PublishJobManager` owns the run.
- README: replaced the outdated note that models aren't wired into the generated app.
- Needs `@lbdudc/gis-publisher` 1.5.0 (older CLIs still work, with an indeterminate bar and the plain log).

### Fixed
- Errors while updating or finalizing the QGIS task entry are written to the QGIS message log instead of being swallowed silently (Bandit B110).
- The CI unit-test job failed on Linux: two tests only passed on Windows (an AWS config test missing fields, and a test comparing a literal Windows path).

### Internal
- 232 unit tests (182 in 0.4.0); they pass on Linux and Windows.

## [0.4.0] - 2026-09-24

### Added
- **Pre-run summary.** Before Generate/Deploy actually starts, a one-screen summary shows layer/map/chart/model counts and the deploy target, so an obviously-wrong selection is caught before a multi-minute run instead of after.
- **"Open app" / "Open output folder"** buttons on the success dialog after a local deploy (previously text-only for the app URL, and folder-opening was generate-only).
- **"Run again"** button in History — restores a Generate or local-Deploy run's settings and runs immediately; SSH/AWS runs still restore fields only, since credentials are never stored.
- **New pre-run warnings**, shown in both the layers table and the pre-run confirm dialog:
  - A layer name that collides with the generator's own DSL grammar keywords (e.g. a layer named "point" or "polygon") — previously failed generation with a cryptic parser error, now caught and flagged with a rename suggestion before running.
  - Symbology QGIS can't convert to SLD faithfully (heatmap, 2.5D, inverted polygon, null-symbol renderers fail outright; point-displacement/point-cluster silently degrade to a generic default style) — verified against real QGIS.
  - An informational note that local raster layers always publish unstyled.
  - A QGIS group named "Output", "Charts" or "Models" no longer collides with the plugin's own reserved staging directories.

### Internal
- 12 new unit tests (182 total).

## [0.3.1] - 2026-09-23

### Added
- **The UI no longer freezes on Generate/Deploy.** Node.js/GISPublisher requirement checks now run off the UI thread (previously several npm/node subprocess calls ran synchronously on every dialog open and before every run), and the progress dialog now shows live per-layer progress during staging instead of sitting frozen until the CLI process starts.
- **Run History is now a standalone window** (new "History" button), and now covers Generate runs too, not just Deploy — a Generate run's log used to disappear once its progress dialog closed. Open/Restore settings/View log/Clear actions all moved with it; "View log" is now a resizable window instead of a barely-resizable `QMessageBox` popup.
- **The Layers tab is a table** (Layer/Type/Features/CRS/Group columns, with a "Show details" toggle) instead of a plain name list, built from the same per-layer checks (CRS/feature count/geometry/field count) the export itself uses — flagged issues now also show up in the pre-run confirm dialog, not only as a tooltip.
- **"Test connection" (SSH) / "Test credentials" (AWS) buttons** on the Deploy page check reachability/credentials up front, instead of only failing after committing to a multi-minute deploy attempt.
- AWS region and instance type are now dropdowns with common values pre-populated, instead of bare free-text fields.
- Right-click a chart file (Charts tab) to rename or delete it.
- Ctrl+Enter (Run) / Ctrl+H (History) keyboard shortcuts.

### Fixed
- The AWS deploy page no longer leaves blank space under the Generate/Local/SSH views by reserving height for its own (much taller) page.
- Deploy secrets (AWS/SSH credentials) written to a temporary config file are now written with 0600 permissions on POSIX, and cleanup is crash-proof — a failed delete no longer silently skips recording the run in History.
- A couple of previously-silent failures (QGIS layer-tree read errors, a model whose parameters can't be read) now report what went wrong instead of failing blank.

### Internal
- 39 new unit tests covering `deploy_config`, `state_store` and `model_discovery` (132 → 171).

## [0.3.0] - 2026-09-17

### Added
- **Every vector layer is now published, not just shapefiles.** GeoPackage, PostGIS and memory/scratch layers are exported to shapefile during staging (through QGIS's own writer) instead of being silently skipped, so their data, attributes and SLD styling all reach the generated app. Reprojection to a consistent target CRS happens as part of the same export.
- **Chart color fields now do something.** Bar, line and area charts accept an optional color field to render a colored/multi-series chart (grouped lines or areas, tinted bars) with a legend, instead of silently ignoring it.
- A `ci.yml` GitHub Actions workflow runs the QGIS-free unit test suite and a lint pass on every push and pull request.

### Fixed
- Two layers that would have staged under the same basename (e.g. same-named layers from different folders, or same-named tables from one GeoPackage) no longer silently overwrite each other — collisions are detected and deduplicated.
- Grouped bar, stacked bar and heatmap charts no longer silently degrade into a meaningless chart (grouping a field by itself, or aggregating the wrong field) when no color field is given — building one without it is now a clear error instead.
- The scatter plot no longer renders as empty/NaN points when a categorical field is used for an axis.
- A non-UTF-8 byte in the GISPublisher CLI's output no longer crashes the run.
- SLD style rewriting after a field rename now uses real XML parsing, so an attribute-form or whitespaced `PropertyName` is no longer missed.
- A field name that's a valid identifier but too long for a DBF field slot (only reachable from a non-shapefile source) is now correctly renamed instead of silently mismatching the generated app's actual field name.

## [0.2.0]

### Added
- **Geoprocessing models are discovered automatically**, the same way layers are: models saved inside the current project and models saved in your QGIS profile's models folder both appear on the Models tab as a checkable list, with a refresh button and an "Add folder…" option for models kept elsewhere. No more manually exporting every model to a folder each session.
- **QGIS symbology is exported as SLD** alongside each published shapefile layer, so the generated application renders with your QGIS styling instead of a randomly generated color; the run log records whether each layer's style was exported.
- **Layer, chart and model selections are now remembered per project**, saved into the project file itself (output folder and action/deploy type included) and restored automatically the next time the project is opened.
- **Deployment history**: the Deploy page's new History section keeps the last 20 deploy runs (target, resulting host URL, exit code, log tail) in your QGIS profile, with actions to open the deployed app, restore non-secret settings from that run, or view its log. Credentials are never recorded.
- **In-plugin Vega chart builder**: "New chart…" on the Charts tab builds a chart from a layer's fields — bar, line, area, scatter, pie, donut, grouped bar, stacked bar, histogram, box plot, and heatmap, beyond the generated app's built-in line/bar/pie — with a live preview rendered against the layer's real attribute data using the plugin's own bundled, offline Vega/Vega-Lite/vega-embed (falls back to "Preview in browser" where QtWebEngine isn't available).
- **Chart validation**: every chart file in the Charts list is checked for a mismatched entity URL, unknown field references, and leftover template placeholders; files with issues get a warning icon and tooltip, and Run asks for confirmation before continuing with one still checked.
- A **Show log** toggle on the progress window (remembered between runs) replaces the old developer-only debug flag for viewing GISPublisher's raw output.

### Changed
- Replaced the main dialog and the separate Generate/Deploy/Requirements popups with a single resizable window: a live requirements status at the top, a two-pane layout below it (Layers/Charts/Models tabs on the left, the Action/Generate/Deploy panel on the right, resizable via a splitter), and a single **Run** button at the bottom.
- Selecting a Charts or Models folder now lists its contents as a checkable list, so individual files can be excluded instead of all-or-nothing per folder; each tab gives its list the full panel height instead of a small fixed-size box.
- Replaced emoji buttons/icons with native Qt standard icons (folder, reload, play, cancel, etc.) for a more consistent, platform-correct look.
- Collapsed the requirements status area into a single compact line with the detection details moved to a tooltip, and turned "Recheck" into a small icon-only button, so it no longer competes for space with the Layers/Charts/Models/Action panels.
- The AWS deploy form is split into grouped sections (Credentials, Instance settings, SSH access) with tooltips and links to the relevant AWS documentation for each field, instead of one flat list of 10+ fields.
- Progress dialogs show a busy indicator instead of a simulated percentage, and can be cancelled while a Generate/Deploy operation is running.
- The AWS Secret Access Key field is masked, and SSH/AWS key path fields have a browse button instead of requiring a typed path.
- Deploy validates required fields for the selected deployment type before running.

### Fixed
- Deploying with no models and no charts selected no longer fails after the app has already been deployed (the CLI's own file walk choked on an empty staging subfolder it expected to contain processed output).
- A Generate/Deploy error popup now shows the actual failure detail (with a **Show Details…** button for the full log) instead of a generic "An error occurred" message.
- Unchecking layers is no longer discarded the next time QGIS fires a layersAdded/layersRemoved signal (e.g. from an unrelated layer being added elsewhere) — check state is now preserved.
- Staging folders under the system temp directory older than a day are now swept automatically instead of accumulating indefinitely.
- Deploy now uses the layers selected (checked) in the main dialog instead of every layer in the project.
- Cancelling the charts/models folder picker no longer clears a previously selected folder.

## [0.1.1] - 2025

### Fixed
- `WinError 123` caused by the QGIS URI suffix (e.g. `|layername=...`) being included in the layer source path.
- npm/node detection failing in QGIS's restricted PATH environment on Windows.
- npm not found when `find_npm()` was called without `find_node()` first.
- Remaining Bandit security warnings on subprocess calls, addressed with justified `nosec` annotations.

## [0.1.0] - 2024

### Added
- Initial release
- Generate interactive GIS web applications from QGIS layers (vector + WMS raster)
- Deploy to local, SSH, and AWS environments
- Optional Vega/Vega-Lite chart folder support
- Optional QGIS geoprocessing model (`.model3`) folder support
- Automatic Node.js and GISPublisher dependency check with guided installation
- Cross-platform Node.js/npm detection (Windows, Linux, macOS)
