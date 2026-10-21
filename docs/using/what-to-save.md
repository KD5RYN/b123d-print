# What to save

## Three things to keep

Only three things need keeping: back them up, put them in git, copy them to another machine.

- `parts/<name>/<name>.py`: the script, the parametric source of the part
- `parts/<name>/ref/`: reference files (models you remix, scans and photos you trace)
- `b123d-print.toml`: the workspace settings, at the workspace root ([Settings](settings.md))

Everything in `out/` is made again by one export (`b123d-print build <name>`, or the `export`
tool), so it does not need a backup.

```
parts/<name>/
  <name>.py            the script (the parametric source)
  ref/                 reference models and images (remixes, traces)
  out/
    README.md          short index: what is where, which file to slice
    print/             3MF, STL and <name>_print.md (print sheet): what you open in the slicer
    print/templates/   3MF and STL of fit-test templates
    cad/               STEP and GLB (incl. <name>_view.glb)
    images/            PNG previews, section views, before/after, compare and trace pictures
    docs/              shopping list (_bom.md, _bom.csv), _hardware.json, _view.html, trace outlines
    .cache/            build cache (never downloaded)
```

A file's folder follows from its name; [Output formats](formats.md#where-each-file-goes) has the
full list.

## Which file to use

- **To print:** the file in `out/print/`. Use the 3MF when your slicer reads it: it keeps units,
  so it can't be scaled wrong. See [From part to print](slicing.md).
- **To edit in other CAD:** the STEP in `out/cad/`.
- **Not sure:** `out/README.md` lists what is where and which files to open in the slicer.

## On a shared server (HTTP or SSH)

The server is a workbench, not storage. A workspace nobody used for 30 days is removed (the
operator can change this with `B123D_PRINT_RETENTION_DAYS`). The copy that `download_part` (or
`b123d-print pull <name>`) brings home is your record. Bring a part home when you finish a
session. See [getting the files over HTTP](../getting-started/http.md#get-the-files) and
[over SSH](../getting-started/ssh.md#get-the-files).

## Older parts

Parts made before 0.3.11 have every file directly in `out/`. The next export sorts them into the
folders; there is nothing to do.

## Versions

b123d-print can keep a **version history** of your project, so you can come back weeks later
to the version that worked, or try a change and go back. It uses git underneath; you do not
need to know git.

**Start it** once per project folder, only if you want it:

```
b123d-print init --git
```

`b123d-print init` and first-run setup (`b123d-print setup`, or the `setup_workspace` prompt)
ask you; nothing happens without a yes. An agent can start it too, with
`save_version(..., start=True)`, after asking you. It makes the folder a git repository on your
machine; nothing is sent anywhere.

**Save, list, go back:**

| You want | Tell the agent, or run | |
| --- | --- | --- |
| keep this version | "save this version" | `b123d-print save "arm 130 mm" [--part shelf_bracket]` |
| see the versions | "list the versions of shelf_bracket" | `b123d-print versions shelf_bracket` |
| go back to one | "go back to version 2" | `b123d-print restore shelf_bracket 2` |

```
Saved shelf_bracket as version 3 (5d6d05f): arm 130 mm
  shelf_bracket: ARM_L 115 → 130
```

- The agent **offers** "Save this version?" after a change that built and passed its checks.
  It never saves on its own.
- Going back **saves the old files as a new version**. Nothing is lost: the versions in between
  stay in the list, and you can go back to them too. Files you added later (a new scan in
  `ref/`) stay where they are.
- Going back is refused while the part has changes you have not saved: save them first.
- After going back, build and check the part again (`b123d-print build <name>`).

### What goes into a version

| Saved | Not saved |
| --- | --- |
| each part's script `parts/<name>/<name>.py` | `out/`: everything an export makes again (3MF, STL, STEP, pictures) |
| other `.py` files beside it (helpers the script imports) | downloaded zips (`*.zip`) |
| `MEASURE.md` beside it (your measurements) | tokens and client configs (`.mcp.json`, `opencode.json`, `*.token`, `.env`) |
| everything in `ref/`: the models you remix, scans and photos you trace | caches (`__pycache__/`, `out/.cache/`, `.venv/`) |
| `b123d-print.toml` (with `save` for the whole project) | any other file you put in the folder |

`init --git` writes a `.gitignore` with the "not saved" lines; if you already have one, it adds
only the lines that are missing.

- **Big files:** files in `ref/` are saved whole, even large binary models and photos, because
  the script needs them to rebuild the part. Each version of a file you change is kept, so the
  history grows with them. Exports are never saved, so they cost nothing. If you push to GitHub,
  it refuses files over 100 MB; `save` warns about files over 20 MB.
- **Other files** you put in a part folder or in the project folder (notes, PDFs, photos outside
  `ref/`) are left alone: not saved, not deleted. Put files the part needs in `ref/`; save anything
  else with git yourself (below).
- **Safety:** the version tools run git with the repository's hooks and file-system monitor
  switched off, and refuse a repository whose own git settings would run a command on the files
  (a filter). They only touch the files above, inside the project folder.

### On a shared server

The history lives **on your machine, in your project folder**, never on the server. On a shared
(HTTP or SSH) server, `save_version`, `list_versions` and `restore_version` run nothing there:
they give the git commands to run in your project folder, after `download_part` has brought
the part home.

## Resume a project later

On a shared server, a workspace nobody used for 30 days is removed. Your copy at home (the
script, `ref/`, `b123d-print.toml`) is all you need to carry on:

1. Connect the agent to the server as before (a new workspace name works too).
2. Tell it: "resume shelf_bracket from my project folder". It puts the part back from your copy:
   `new_part("shelf_bracket")`, then `write_part` with your whole
   `parts/shelf_bracket/shelf_bracket.py`, then `upload_reference` for each file in `ref/` (over
   HTTP it gives a `curl -fT` upload link; over SSH run the
   [`b123d-print push`](../getting-started/cli.md) command it gives).
3. Settings you had in the workspace's `b123d-print.toml` (printer, calibration) go back with
   `save_setup`.
4. Build and export again: `out/` is made again from the script.

When a tool cannot find a part on a shared server, its answer says how to resume it.
Locally there is nothing to resume: the files never leave your project folder.

## If you use git yourself

Everything above is plain git, so you can keep using git as you like: push to GitHub, Gitea or
GitLab, branch, look at diffs. `save` commits only its own files and leaves anything else you
have staged as it was. To keep the print files in git too, change the `.gitignore` line `out/`
to:

```
parts/*/out/*
!parts/*/out/print/
```
