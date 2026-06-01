# GisPublisher QGIS Plugin

<div style="display:flex; margin-bottom: 20px;">
  <img src="https://img.shields.io/badge/QGIS-3.x-blue?&style=flat-square" alt="QGIS Version">
  <img src="https://img.shields.io/badge/License-MIT-yellow.svg?&style=flat-square" alt="License: MIT">
  <img src="https://img.shields.io/node/v/@lbdudc/gis-publisher?&style=flat-square" alt="Node.js Version">
</div>

This plugin integrates **[GisPublisher]https://gitlab.lbd.udc.es/GEMA/lps/gispublisher/gispublisher)** into QGIS, allowing you to generate interactive GIS applications directly from the layers currently loaded in your QGIS project, without leaving QGIS.

## Table of Contents

1. [Installation](#installation)
2. [Usage](#usage)
3. [Data Visualizations with Vega](#data-visualizations-with-vega)
4. [Geoprocessing Models](#geoprocessing-models)
5. [Requirements](#requirements)
6. [Authors](#authors)
7. [License](#license)

## Installation

1. Copy the plugin folder (`GisPublisherPlugin`) to the QGIS plugins directory:

   - **Windows:** `%APPDATA%\QGIS\QGIS3\profiles\default\python\plugins\`
   - **Linux:** `~/.local/share/QGIS/QGIS3/profiles/default/python/plugins/`

2. Restart QGIS.
3. Enable the plugin in **Plugins → Manage and Install Plugins → Installed**.

## Usage

1. Open QGIS and locate the **GisPublisher** icon in the toolbar.
2. Click the icon to launch the plugin. 
3. The plugin will first check that **Node.js** and **GisPublisher** are installed. If any requirement is missing, it will guide you through the installation.
3. Once the requirements are met, a window will appear where you can:
   - Select the layers from your current QGIS project that you want to include in the generated application.
   - Optionally, select a `charts` folder containing **Vega** or **Vega-Lite** charts.
   - Optionally, select a `models` folder containing QGIS geoprocessing models (`.model3` files).
4. Choose one of the following actions:
   - **Generate**: Select a destination folder where the GIS application will be generated using GisPublisher, including the selected layers and charts.
   - **Deploy**: Open a deployment window where you can provide configuration details to deploy the application to **local**, **SSH**, or **AWS** environments.
5. After the action completes, a message box will inform you whether the generation or deployment was successful, or if an error occurred.

## Geoprocessing Models

The plugin supports including custom QGIS geoprocessing models in the generated application. These models are created in QGIS using the **Graphical Modeler** and exported as `.model3` files.

To include models, select a `models` folder in the plugin dialog. All `.model3` files found in that folder will be copied into the generated application and made available in the **Toolbox** panel alongside the built-in QGIS processes.

To create and export a model from QGIS:
1. Open **Processing → Graphical Modeler**.
2. Design your model and save it.
3. Export it as a `.model3` file via **Model → Save Model to File**.
4. Place the exported file in the `models` folder you will select in the plugin.

## Requirements

- QGIS 3.x
- Node.js 19+ installed
- GisPublisher installed and accessible from the system PATH
- Layers loaded in QGIS that you want to include in your GIS application 
- Optional: `charts` folder containing valid Vega or Vega-Lite charts 
- Optional: `models` folder containing QGIS geoprocessing model files (`.model3`)

## Authors

| Name               | Email                             |
| ------------------ | --------------------------------- |
| Patricia Mato      | <patricia.mato.miragaya@udc.es>   |

## License

MIT License - see [LICENSE.md](LICENSE.md) for details.
