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
   - On the left, a tabbed panel switches between **Layers**, **Charts**, **Models** and **Web app**:
     - **Layers** — choose which layers from your current QGIS project to include (all are selected by default; use "Select all" to toggle everything).
     - **Charts** (optional) — click **New chart…** to build one from a layer's fields with a live preview, or select a folder of hand-authored **Vega**/**Vega-Lite** chart definitions; once selected, its contents appear as a checkable list so you can include or exclude individual files. See [Data Visualizations with Vega](#data-visualizations-with-vega).
     - **Web app** — how the generated app looks (title, logo, colour, basemap) and what it offers (map search, address search, legend, data downloads, and whether a redeploy replaces the edits made in the app).
     - **Models** (optional) — geoprocessing models saved in the current project or in your QGIS profile are listed automatically as a checkable list; use the refresh button if you've just saved a new one. **Add folder…** appends models from an extra folder (e.g. shared on a network drive). See [Geoprocessing Models](#geoprocessing-models).
   - On the right, the **Action** panel: choose **Generate** or **Deploy**. Generate shows an output folder picker and a checkbox to also save the app as a zip; Deploy shows the Local/SSH/AWS/Hetzner Cloud/DigitalOcean configuration described in [Deploying your application](#deploying-your-application), plus a **History** section — see [Deployment history](#deployment-history).
   - Drag the divider between the two panes to resize them.
3. Click **Run** at the bottom of the window to start the selected action. Your layer/chart/model selections and output folder are remembered per-project — see [Saved selections](#saved-selections).
4. A progress window opens listing the run as steps (export layers, generate the app, check Docker, build & start services, wait for services…), each with its status and duration, and the state of every service while the app starts. Tick **Show details** for the underlying GISPublisher/Docker output (remembered for next time).
   - **Run in background** hides the window and the run continues: it appears in the QGIS task manager (bottom status bar, where it can also be cancelled), and a message-bar notification tells you when it ends, with **Open app** / **Details** buttons. Click **Show progress…** on the main window to bring the window back. One run at a time.
   - When it finishes, the window shows the result: the app's URL (**Open app**, **Copy link**) or a plain-language reason for the failure (Docker not running, port already in use, SSH authentication failed…) with a hint, plus the full log.

## Labels and styles

The generated map is drawn by GeoServer from each layer's QGIS style, so what you set in QGIS is what the map shows. Labels:

- **A field as the label** is published as it is, with its font, size, colour, halo and placement.
- **A label expression** (for example `concat("name", '\n', round("pop" / 1000), 'k')`) and **rule-based labels** are worked out by QGIS for every feature while publishing and stored in a hidden text column (`gp_label`) that the labels are drawn from. The column is not shown in the app's lists, forms, popups or downloads.
  - With rule-based labels, each feature gets the text of the first rule whose filter matches, and all are drawn with the style of the first rule (per-rule fonts, colours and scale ranges are not kept).
  - The text is fixed when you publish: a feature added or changed in the web app (an *Editable* layer) keeps its old label, or has none if it is new, until the next publish.
- Other label kinds (blocking, obstacles) are not published. The run log lists what was approximated (`[STYLE] <layer>: ...`).

GeoServer draws the map in tiles, so a label of a large polygon can appear once per tile.

## Live PostGIS and WFS layers

Tick **Live** on a PostGIS or WFS layer (the column is in the layer list) to publish it *without copying its data*: the app's map server (GeoServer) connects to the source and draws it with the layer's QGIS style, so the map follows the source, with nothing to republish when the data changes.

- A live layer is **map only**: no list, search, popup-from-table, download or editing (it does still show its legend and identify popup from the server). A label written as an expression is not applied.
- The source's login is kept in the app's server configuration, never in the pages people download; a login that lives in the QGIS authentication database is read from there.
- The source must be reachable **from the machine that runs the app**. On *Local*/*Generate* a source on this computer (`localhost`) is reached as `host.docker.internal`, so the database has to accept connections from Docker. When deploying to another machine, a source on this computer or a private network cannot be reached: the run log says so (`[WARN]`).
- A PostGIS layer must be a plain table (no filter, no query layer, no PostgreSQL service file); otherwise it is copied like any other layer, and the log says why.
- The sidecar behind it (`<name>.live.json`) can also be written by hand for `gispublisher` on the command line, see its README.

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

### In the generated app

Selected models are copied into the generated product's `server/models/` folder and served by its QGIS WPS container. Open the **toolbox** button on the map, pick your model under **Models**, choose an input layer for each vector input, and run it; each layer output is added to the map when the job finishes. If you select no models, the product ships a small demo model instead.

Before a run, the plugin checks each checked model and warns (in the model's tooltip and the pre-run confirmation) about things that work in QGIS but not in the generated app:

- steps that use algorithms from a provider the app's processing container doesn't have (only `native`, `qgis` and `gdal` are available);
- vector inputs no published layer can satisfy (for example a polygon input with only point layers published);
- fixed distances, such as a 2000-unit buffer: the app stores and processes data in EPSG:4326, so unless the QGIS project itself uses a projected CRS the number is read as degrees. With a projected project CRS, models run in that CRS instead.

## Generate as a zip

**Generate** writes the app into the output folder you choose. With **Also save it as a zip (with a README and start scripts)** checked (it is not by default), it also writes `<app name>-<version>.zip` there: the app, a `README.md` and `start.sh` / `start.ps1`, so that whoever gets it can start the app on any machine with Docker, with HTTPS if they give it a domain (`./start.sh --domain gis.example.org`). Use it to hand the app to an IT team, or to run it on a server you set up yourself. The app made for a zip has its own random passwords, so keep the zip private.

## Deploying your application

Selecting **Deploy** in the Action section lets you configure one of five deployment targets (Local, SSH, AWS, Hetzner Cloud, DigitalOcean) before clicking **Run**. All secret fields (AWS Secret Access Key) are masked, and any local file path field (private key, SSH key) has a folder-icon button to browse for the file instead of typing the path. Hover any field for a description of what it expects, and see the links next to the AWS fields for where to find those values in the AWS Console.

A line under the target buttons always says what the run will do and where the app will end up (for example *Deploys to ubuntu@203.0.113.5 over SSH, into /home/ubuntu/app. The app will be at https://gis.example.org.*), with warnings in amber: no domain means plain HTTP, and editable layers over plain HTTP send the editing password unencrypted. **Copy as a gispublisher command** puts the equivalent command line on the clipboard, to run the same deployment from a terminal or a script (AWS keys are not included: the command reads them from the environment).

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
| Domain (optional) | A name that points at the server, e.g. `gis.example.org`: the app is then served over **HTTPS** with a free Let's Encrypt certificate (ports 80 and 443 must be open). Empty: plain HTTP at the server's address |
| Email for the certificate (optional) | Where Let's Encrypt sends expiry notices |

An `ssh` client (OpenSSH) must be installed on this computer; on Windows it is an optional feature (*Settings > System > Optional features > OpenSSH Client*). If a layer is editable and there is no domain, the plugin warns that the editing password would travel unencrypted.

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
| Domain / Email (optional) | As for SSH. With a domain, the security group must open ports 80 and 443 (checked before the instance is created); the domain can only point at the instance after it exists, so the certificate is issued once you point the name at it |

### Hetzner Cloud and DigitalOcean

Rent a server at the provider on the first deploy and deploy to it (Ubuntu, Docker installed for you, a firewall for ports 22, 80 and 443). Later deploys find the server again by its name, so the data stays. **Not tried yet against the real services** (they need an account with a payment method); the page says so.

| Field | Description |
|-------|-------------|
| API token | A token with write access (where to create it is written on the page). Masked; **Test token** asks the provider's API if it accepts it. It goes to the CLI as `HCLOUD_TOKEN` / `DIGITALOCEAN_TOKEN`, never into a file. *Remember the token* keeps it in the QGIS password manager |
| Name | The server's name; a server with that name is reused |
| Size / Region | Presets (at least 4 GB: the build needs it), and you can type any other size or region of the provider |
| SSH key | Your private key; its `.pub` half is added to your account and lets you in as `root` |
| Domain / Email (optional) | As for SSH; the name can only point at the server once it exists |

Update data only is not offered for these targets (use SSH with the server's address for that).

All fields are required for the selected deployment type; the plugin validates them before running and lists anything missing. The remote path must be an absolute folder at least two levels deep (for example `/home/ubuntu/app`): **it is emptied on every deploy**.

Each app is generated into its own folder, `<QGIS profile>/GISPublisher/deployments/<app name>/output`, so History can open it and redeploying an app replaces its previous deployment. Docker is installed on an SSH/AWS server the first time (this needs a user with passwordless `sudo`); afterwards that step is skipped. A deploy is finished when every service is healthy, not just started.

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
While a Generate or Deploy operation is running, click **Cancel** in the progress window (or cancel its entry in the QGIS task manager) to stop it. This stops GISPublisher and the commands it started, but a Docker image build that the Docker engine already began may finish in the background; the next deploy of the same app cleans up. Partial output in the destination folder is not automatically cleaned up. Temporary staging folders under your system temp directory are swept automatically after a day; nothing to clean up by hand.

**A published map doesn't use my QGIS styling.**
Only styling on layers copied as shapefiles is exported (as an `.sld` file alongside them) — GeoPackage, PostGIS and other non-shapefile vector sources still fall back to a generated random-colour style, since layer export itself remains shapefile-only. Check the log (**Show details** in the progress window) for a `[STYLE]` line per layer confirming whether its style was exported.

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
