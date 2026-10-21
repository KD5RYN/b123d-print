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

## If you use git

Commit the script, `ref/` and `b123d-print.toml`. Add `out/` to `.gitignore`, or ignore all of
`out/` except `out/print/` if you want the print files in git:

```
parts/*/out/*
!parts/*/out/print/
```

## Version history

Simple version history of a part is planned
([issue #125](https://github.com/KD5RYN/b123d-print/issues/125)). Until then, use git, or keep
copies of the script.
