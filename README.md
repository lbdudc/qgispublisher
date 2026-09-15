# GISPublisher QGIS Plugin

<div style="display:flex; gap:6px; margin-bottom: 20px;">
  <img src="https://img.shields.io/badge/QGIS-3.x-blue?style=flat-square" alt="QGIS Version">
  <img src="https://img.shields.io/badge/License-GPL%20v2%2B-yellow.svg?style=flat-square" alt="License: GPL v2+">
  <img src="https://img.shields.io/badge/Node.js-19%2B-green?style=flat-square" alt="Node.js 19+">
  <img src="https://img.shields.io/badge/platform-Windows%20%7C%20Linux%20%7C%20macOS-lightgrey?style=flat-square" alt="Platform">
</div>

This plugin integrates **[GISPublisher](https://gitlab.lbd.udc.es/GEMA/lps/gispublisher/gispublisher)** into QGIS, allowing you to generate interactive GIS web applications directly from the layers currently loaded in your QGIS project, without leaving QGIS.

## Table of Contents

1. [Installation](#installation)
2. [Usage](#usage)
3. [Data Visualizations with Vega](#data-visualizations-with-vega)
4. [Geoprocessing Models](#geoprocessing-models)
5. [Requirements](#requirements)
6. [Contributing](#contributing)
7. [Authors](#authors)
8. [License](#license)

## Installation

### From the QGIS Plugin Repository (recommended)

1. Open QGIS and go to **Plugins → Manage and Install Plugins**.
2. Search for **GISPublisher** and click **Install**.

### Manual installation

1. Download the latest `.zip` release from the [Releases](https://github.com/lbdudc/qgispublisher/releases) page.
2. In QGIS, go to **Plugins → Manage and Install Plugins → Install from ZIP**.
3. Select the downloaded `.zip` and click **Install Plugin**.

Alternatively, extract the zip contents into your QGIS plugins directory:

| Platform | Path |
|----------|------|
| Windows  | `%APPDATA%\QGIS\QGIS3\profiles\default\python\plugins\` |
| Linux    | `~/.local/share/QGIS/QGIS3/profiles/default/python/plugins/` |
| macOS    | `~/Library/Application Support/QGIS/QGIS3/profiles/default/python/plugins/` |

4. Restart QGIS and enable the plugin in **Plugins → Manage and Install Plugins → Installed**.

## Usage

1. Open QGIS and locate the **GISPublisher** icon in the toolbar.
2. Click the icon to launch the plugin.
3. The plugin will check that **Node.js** and **GISPublisher** are installed. If any requirement is missing, it will guide you through the installation.
4. Once requirements are met, a window will appear where you can:
   - Select the layers from your current QGIS project to include in the generated application.
   - Optionally, select a `charts` folder containing **Vega** or **Vega-Lite** charts.
   - Optionally, select a `models` folder containing QGIS geoprocessing models (`.model3` files).
5. Choose one of the following actions:
   - **Generate**: Select a destination folder where the GIS application will be generated.
   - **Deploy**: Open a deployment window to deploy the application to **local**, **SSH**, or **AWS** environments.
6. A message box will confirm whether the action completed successfully or if an error occurred.

## Data Visualizations with Vega

The plugin supports attaching custom charts built with [Vega](https://vega.github.io/vega/) or [Vega-Lite](https://vega.github.io/vega-lite/) to the generated application. Place your `.json` chart definitions in a folder and select it in the plugin dialog.

## Geoprocessing Models

The plugin supports including custom QGIS geoprocessing models (`.model3` files) in the generated application. These models are created in QGIS using the **Graphical Modeler**.

To create and export a model:
1. Open **Processing → Graphical Modeler**.
2. Design your model and save it.
3. Export it as a `.model3` file via **Model → Save Model to File**.
4. Place the exported file in the `models` folder you will select in the plugin.

## Requirements

- QGIS 3.x
- Node.js 19+ ([download](https://nodejs.org/en/download))
- GISPublisher: install via `npm install -g @lbdudc/gis-publisher`
- At least one vector or raster layer loaded in QGIS

Optional:
- A `charts` folder with valid Vega or Vega-Lite chart definitions
- A `models` folder with QGIS geoprocessing model files (`.model3`)

## Contributing

Bug reports and feature requests are welcome via the [issue tracker](https://github.com/lbdudc/qgispublisher/issues).

To contribute code:
1. Fork the repository.
2. Create a feature branch: `git checkout -b feature/my-feature`.
3. Commit your changes and open a pull request.

## Authors

| Name          | Email                           |
|---------------|---------------------------------|
| Patricia Mato | patricia.mato.miragaya@udc.es   |

## License

This plugin is released under the **GNU General Public License v2 or later** — see [LICENSE](LICENSE) for details.
