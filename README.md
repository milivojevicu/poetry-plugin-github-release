# GitHub Release plugin for [Poetry](https://github.com/python-poetry/poetry)

[![black](https://github.com/milivojevicu/poetry-plugin-github-release/actions/workflows/black.yml/badge.svg)](https://github.com/milivojevicu/poetry-plugin-github-release/actions/workflows/black.yml)
[![isort](https://github.com/milivojevicu/poetry-plugin-github-release/actions/workflows/isort.yml/badge.svg)](https://github.com/milivojevicu/poetry-plugin-github-release/actions/workflows/isort.yml)
[![pycln](https://github.com/milivojevicu/poetry-plugin-github-release/actions/workflows/pycln.yml/badge.svg)](https://github.com/milivojevicu/poetry-plugin-github-release/actions/workflows/pycln.yml)
[![pylint](https://github.com/milivojevicu/poetry-plugin-github-release/actions/workflows/pylint.yml/badge.svg)](https://github.com/milivojevicu/poetry-plugin-github-release/actions/workflows/pylint.yml)

A plugin for Poetry that adds a `release` subcommand which creates a new release on GitHub,
and with that a new Git tag as well.

## Installation

Using `poetry`:

```bash
$ poetry self add git+https://github.com/milivojevicu/poetry-plugin-github-release
```

Using `pipx inject`:

```bash
$ pipx inject poetry git+https://github.com/milivojevicu/poetry-plugin-github-release
```

Using `pip`:

```bash
$ pip install git+https://github.com/milivojevicu/poetry-plugin-github-release
```

More details at: [python-poetry.org/docs/plugins](https://python-poetry.org/docs/plugins/#using-plugins)

## Usage

```bash
$ poetry release
Release v0.1.0 created and accessable through the following URL:
  https://github.com/milivojevicu/poetry-plugin-github-release/releases/tag/v0.1.0
Attempting to attach 2 asset(s) to the release.
  1. Uploading 'poetry-plugin-github-release-0.1.0.tar.gz'... Done.
  2. Uploading 'poetry_plugin_github_release-0.1.0-py3-none-any.whl'... Done.
```
