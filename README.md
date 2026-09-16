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
6. [Deployment history](#deployment-history)
7. [Saved selections](#saved-selections)
8. [Requirements](#requirements)
9. [Troubleshooting](#troubleshooting)
10. [Contributing](#contributing)
11. [Authors](#authors)
12. [License](#license)

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
2. Click the icon to launch the plugin. A window opens with a compact status line at the top (hover it for details on Node.js/GISPublisher detection; a small refresh button rechecks, and an "Install GISPublisher" button appears only if it's missing), then a two-pane layout below it:
   - On the left, a tabbed panel switches between **Layers**, **Charts** and **Models**:
     - **Layers** — choose which layers from your current QGIS project to include (all are selected by default; use "Select all" to toggle everything).
     - **Charts** (optional) — click **New chart…** to build one from a layer's fields with a live preview, or select a folder of hand-authored **Vega**/**Vega-Lite** chart definitions; once selected, its contents appear as a checkable list so you can include or exclude individual files. See [Data Visualizations with Vega](#data-visualizations-with-vega).
     - **Models** (optional) — geoprocessing models saved in the current project or in your QGIS profile are listed automatically as a checkable list; use the refresh button if you've just saved a new one. **Add folder…** appends models from an extra folder (e.g. shared on a network drive). See [Geoprocessing Models](#geoprocessing-models).
   - On the right, the **Action** panel: choose **Generate** or **Deploy**. Generate shows an output folder picker; Deploy shows the Local/SSH/AWS configuration described in [Deploying your application](#deploying-your-application), plus a **History** section — see [Deployment history](#deployment-history).
   - Drag the divider between the two panes to resize them.
3. Click **Run** at the bottom of the window to start the selected action. Your layer/chart/model selections and output folder are remembered per-project — see [Saved selections](#saved-selections).
4. A progress window opens showing the operation's status; you can cancel it while it's running. Tick **Show log** to see the underlying GISPublisher output (the setting is remembered for next time). A message box confirms success, or shows the error (with a **Show Details…** button for the full log), when it finishes.

## Data Visualizations with Vega

The plugin supports attaching charts built with [Vega](https://vega.github.io/vega/) or [Vega-Lite](https://vega.github.io/vega-lite/) to the generated application, in two ways:

- **Build one in the plugin.** Click **New chart…** on the Charts tab, pick a layer and a chart type — bar, line, area, scatter, pie/donut, grouped bar, stacked bar, histogram, box plot, or heatmap — and the fields to use. A live preview on the right renders the chart against the layer's real attribute data (using the plugin's own bundled, offline copy of Vega/Vega-Lite — no running backend needed to preview). Saving writes a ready-to-use spec into your charts folder (or a plugin-managed one, if you haven't picked a folder yet) and checks it in the list.

  Live preview requires QtWebEngine, which isn't available on every QGIS install/platform; when it's missing, use **Preview in browser** instead.

- **Hand-author your own.** Place `.json` Vega/Vega-Lite chart definitions in a folder and select it in the plugin dialog. Every chart in the list is checked for common mistakes — a data URL that doesn't match any selected layer, a field name that doesn't exist on that layer, or leftover `__XFIELD__`-style placeholders (which only get expanded in the app's *built-in* chart templates, not in your own saved charts, and would otherwise render as the literal text "null"). A file with issues gets a warning icon — hover it for details — and Run asks for confirmation before continuing with an invalid chart still checked.

Either way, a chart fetches its data from the deployed application's own REST API at `<backend URL>/api/entities/<entity>/export/tsv`, so it only shows data once the corresponding layer's application is actually running.

## Geoprocessing Models

The plugin includes QGIS geoprocessing models (`.model3`) in the generated application, discovered the same way layers are: automatically, from wherever QGIS already keeps them —

- **models saved inside the current project** (via the Graphical Modeler's "Save Model" into the project rather than to a file), and
- **models saved in your QGIS profile's models folder** (`Processing → Options → Models`, or **Model → Save Model to File** from the Graphical Modeler).

Both show up as a checkable list on the Models tab with no extra steps; use the refresh button after saving a new one. **Add folder…** appends models from anywhere else — e.g. one a colleague shared on a network drive — as a third source, filtered to `.model3` files.

> **Note:** the current GISPublisher CLI (`@lbdudc/gis-publisher`) stages selected models into the generated application's build input but doesn't yet wire them into the generated app itself — this is a limitation of that separate tool, not of the plugin's discovery. Track [gispublisher](https://github.com/lbdudc/gispublisher) for when model support lands there.

## Deploying your application

Selecting **Deploy** in the Action section lets you configure one of three deployment targets before clicking **Run**. All secret fields (AWS Secret Access Key) are masked, and any local file path field (private key, SSH key) has a folder-icon button to browse for the file instead of typing the path. Hover any field for a description of what it expects, and see the links next to the AWS fields for where to find those values in the AWS Console.

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

## Deployment history

The **History** section at the bottom of the Deploy page keeps a record of your last 20 deploy runs on this machine — timestamp, target, and the URL the application ended up at (best-effort: parsed from the CLI's own output for AWS, where the host isn't known until the instance boots). Select a run for three actions:

- **Open app** — opens the recorded URL in your browser.
- **Restore settings** — refills the deploy form's non-secret fields (host, port, remote path, AWS region/instance settings, etc.) from that run.
- **View log** — shows the last ~50 lines of that run's output.

**Credentials are never stored.** AWS access/secret keys and SSH usernames/key paths are excluded from history entirely — restoring a run leaves those fields blank for you to re-enter. History lives in a JSON file under your QGIS profile (not in the project), so it's shared across every project you open, and never leaves your machine.

## Saved selections

Your layer, chart and model selections, the chart/model folders, the output folder, and which action/deploy type was last chosen are saved into the project file itself (as custom project properties, alongside your layers and styles) when you click **Run** or close the plugin window. Reopening the same project restores them automatically — no need to re-check the same layers or re-pick the same output folder every session. A brand new project with nothing saved yet keeps the original default of everything selected.

## Requirements

- QGIS 3.x
- Node.js 19+ ([download](https://nodejs.org/en/download))
- GISPublisher: install via `npm install -g @lbdudc/gis-publisher`
- At least one vector or raster layer loaded in QGIS
- Docker Desktop, only if deploying to **Local**

Optional:
- A `charts` folder with valid Vega or Vega-Lite chart definitions (or build them in the plugin instead)
- QtWebEngine (bundled with most QGIS installs) for the chart builder's live preview — otherwise use "Preview in browser"

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
While a Generate or Deploy operation is running, click **Cancel** in the progress window to stop it. Partial output in the destination folder is not automatically cleaned up. Temporary staging folders under your system temp directory are swept automatically after a day; nothing to clean up by hand.

**A published map doesn't use my QGIS styling.**
Only styling on layers copied as shapefiles is exported (as an `.sld` file alongside them) — GeoPackage, PostGIS and other non-shapefile vector sources still fall back to a generated random-colour style, since layer export itself remains shapefile-only. Check the log (**Show log** in the progress window) for a `[STYLE]` line per layer confirming whether its style was exported.

**A model I saved doesn't show up on the Models tab.**
Click the refresh button next to "Models to include" to force a rescan of QGIS's Processing registry.

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
