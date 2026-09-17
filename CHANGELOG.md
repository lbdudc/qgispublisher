# Changelog

All notable changes to this project will be documented in this file.

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
