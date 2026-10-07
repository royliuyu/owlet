# owlet

Local-first library of papers, notes, and files.

## Install

Use the same Python interpreter that starts owlet.

```powershell
python -m pip install -e .
```

Word files need the public package `python-docx`. The command above installs it. Python imports it as `docx`; the PyPI name is `python-docx`. Do not install the unrelated package named `docx`.

If this environment was created before Word support was added, install it directly, then start owlet again:

```powershell
python -m pip install python-docx
```

Google sign-in stores its secret with `keyring`. The install command above includes it. If this environment was created before that, install it directly, then start owlet again:

```powershell
python -m pip install keyring
```
