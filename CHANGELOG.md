# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

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
