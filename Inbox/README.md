# Inbox — drop zone

Drop papers and documents here to have them integrated into the `Literature/` library.

Supported: `.pdf`, `.docx`, `.pptx`, `.epub`, `.md`, `.txt`, `.xlsx`, `.ipynb`, `.bpmn`
(subfolders are fine).

Then, from the project, run:

```bash
cd ~/docs && scripts/.venv/bin/python scripts/import-downloads.py
```

Each file is renamed to `Author et al. - Title.ext`, classified into the right `Literature/`
subfolder, and skipped if it already exists in the library. A log of the last run is written to
`_last-import.log` in this folder.

This Inbox replaces reaching into `~/Downloads` (which is path-restricted).
