# Add-on packaging and releases

## Packaging

- `repository.yaml` at the repo root makes the repository addable in Home Assistant.
- `addon/glovebox/` holds `config.yaml` (ingress on 8099, port `8100/tcp` off by default, options `currency` and `api_token`, archs `amd64` and `aarch64`), the `Dockerfile`, `DOCS.md`, `CHANGELOG.md` and icons.
- There is no `image:` key yet, so the Supervisor builds the add-on on the user's host. The add-on Dockerfile clones this repository at the tag given by `SOURCE_REF`.
- Each add-on version therefore builds from its own git tag. The tag must exist on GitHub before anyone installs that version.

## Release procedure

1. Bump the version in `addon/glovebox/config.yaml`, in `pyproject.toml` (then run `uv lock`), and `SOURCE_REF=v<version>` in `addon/glovebox/Dockerfile`.
2. Add an entry to `addon/glovebox/CHANGELOG.md`.
3. Run `uv run pytest`.
4. Commit, then tag `v<version>`.
5. Push `master` and the tag.

The `Tests` and `Docs` workflows run on the push. Users then see the update after the add-on store checks for updates.

## Later

A GitHub Actions workflow that builds multi-arch images and publishes them to GHCR is planned. `config.yaml` would then get an `image:` key and the git clone in the Dockerfile goes away.
