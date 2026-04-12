# Conda Environment Rules

Use Conda as the default Python version manager for this workspace.

## Inspect before changing anything

- Check the active environment with `echo $CONDA_DEFAULT_ENV`.
- Check the interpreter path with `python -c "import sys; print(sys.executable)"`.
- Check all environments with `conda info --envs`.

## Install packages into the correct environment

- If the intended environment is already active, install with `python -m pip install <package>`.
- If the intended environment is not active, install with `conda run -n <env> python -m pip install <package>`.
- Re-check imports after installation with `python -c "import <module>; print(<module>.__version__)"` when possible.

## Avoid environment drift

- Avoid `sudo pip`.
- Avoid mixing system Python with Conda-managed Python.
- Avoid creating a new venv unless the user explicitly asks for one.
- Prefer the currently active Conda environment unless the user names a different target.

## Current observed setup

- Observed on 2026-04-06: `CONDA_DEFAULT_ENV=py311`.
- Observed on 2026-04-06: `python` resolved to `/opt/anaconda3/envs/py311/bin/python3`.
- Treat these as hints, not hardcoded truths. Re-check before running commands.
