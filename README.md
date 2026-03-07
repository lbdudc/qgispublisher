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
4. [Requirements](#requirements)
5. [Authors](#authors)
6. [License](#license)

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
4. Choose one of the following actions:
   - **Generate**: Select a destination folder where the GIS application will be generated using GisPublisher, including the selected layers and charts.
   - **Deploy**: Open a deployment window where you can provide configuration details to deploy the application to **local**, **SSH**, or **AWS** environments.
5. After the action completes, a message box will inform you whether the generation or deployment was successful, or if an error occurred.

## Requirements

- QGIS 3.x
- Node.js 19+ installed
- GisPublisher installed and accessible from the system PATH
- Layers loaded in QGIS that you want to include in your GIS application 
- Optional: `charts` folder containing valid Vega or Vega-Lite charts 

## Authors

| Name               | Email                             |
| ------------------ | --------------------------------- |
| Patricia Mato      | <patricia.mato.miragaya@udc.es>   |

## License

MIT License - see [LICENSE.md](LICENSE.md) for details.
