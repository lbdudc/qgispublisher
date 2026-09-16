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
5. [Deploying your application](#deploying-your-application)
6. [Requirements](#requirements)
7. [Troubleshooting](#troubleshooting)
8. [Contributing](#contributing)
9. [Authors](#authors)
10. [License](#license)

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

## Deploying your application

The **Deploy** button opens a dialog where you choose one of three deployment targets. All secret fields (AWS Secret Access Key) are masked, and any local file path field (private key, SSH key) has a folder-icon button to browse for the file instead of typing the path.

### Local

Runs the generated application on your own machine using Docker.

| Field | Description |
|-------|-------------|
| Host  | URL the application will be served on, e.g. `http://localhost:80` |

**Requires [Docker Desktop](https://www.docker.com/products/docker-desktop/) to be installed and running.** On Windows, the plugin automatically adds Docker's default install location to its PATH if found.

### SSH

Deploys to a remote server you control over SSH.

| Field | Description |
|-------|-------------|
| Host | Remote server address |
| Private key path | Path to the `.pem`/private key file used to authenticate |
| Username | SSH username |
| Port | SSH port (default `22`) |
| Remote repository path | Absolute path on the remote server to deploy into |

### AWS

Provisions and deploys to a new AWS EC2 instance.

| Field | Description |
|-------|-------------|
| Access key / Secret key | AWS IAM credentials with permission to launch EC2 instances |
| Region | AWS region, e.g. `eu-west-1` |
| AMI ID | Amazon Machine Image to launch, e.g. `ami-0123456789abcdef0` |
| Instance type | EC2 instance type, e.g. `t2.micro` |
| Instance name | Name tag for the created instance |
| Security group ID | Existing security group to attach, e.g. `sg-0123456789abcdef0` |
| Key pair | Name of an existing EC2 key pair |
| SSH username / SSH key path | Credentials used to connect to the instance after it boots |
| Remote repository path | Absolute path on the instance to deploy into |

All fields are required for the selected deployment type; the plugin validates them before running and lists anything missing.

## Requirements

- QGIS 3.x
- Node.js 19+ ([download](https://nodejs.org/en/download))
- GISPublisher: install via `npm install -g @lbdudc/gis-publisher`
- At least one vector or raster layer loaded in QGIS
- Docker Desktop, only if deploying to **Local**

Optional:
- A `charts` folder with valid Vega or Vega-Lite chart definitions
- A `models` folder with QGIS geoprocessing model files (`.model3`)

## Troubleshooting

**"Node.js is not installed" even though it's installed.**
QGIS on Windows sometimes starts with a restricted `PATH` that doesn't include Node.js, especially if Node was installed after QGIS or via a version manager (nvm, Scoop, Volta). Restart QGIS after installing Node.js; if the problem persists, add Node's install folder to your system `PATH` and restart QGIS again.

**"npm not found" errors during install/deploy.**
Same cause as above — npm ships alongside Node.js but isn't always resolved automatically inside QGIS's Python environment. Restarting QGIS after installing/updating Node.js resolves most cases.

**Local deployment fails immediately.**
Local deployment runs the generated app in Docker — make sure Docker Desktop is installed and running before clicking Deploy.

**A layer isn't appearing in the layer list.**
Only vector and raster layers currently loaded in the QGIS project are listed. WMS raster layers are supported but exported as a `urls.wms` reference file rather than copied locally.

**Cancelling generation/deployment.**
While a Generate or Deploy operation is running, click **Cancel** in the progress window to stop it. Partial output in the destination folder is not automatically cleaned up.

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
