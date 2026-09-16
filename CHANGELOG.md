# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

### Fixed
- Deploy now uses the layers selected (checked) in the main dialog instead of every layer in the project.
- Cancelling the charts/models folder picker no longer clears a previously selected folder.

### Changed
- Progress dialogs show a busy indicator instead of a simulated percentage, and can be cancelled while a Generate/Deploy operation is running.
- The AWS Secret Access Key field is masked, and SSH/AWS key path fields have a browse button instead of requiring a typed path.
- Deploy validates required fields for the selected deployment type before running.

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
