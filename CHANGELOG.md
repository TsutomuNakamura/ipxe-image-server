# Changelog

## v0.5.0

### Changes that may need your action
- Built-in templates allow only public keys for SSH (`allow-pw: false`), and the default user is `me` instead of `ubuntu`.
  Add `authorized-keys` to `args`, or set your own `password` with `allow-pw: true` to log in with a password over SSH.
- The container refuses to start if password login over SSH is enabled with the default password `p@ssw0rd`.
  This is also checked for custom templates, e.g. a `user-data` that has neither `allow-pw` nor `authorized-keys`.
- The container refuses to start if `config.yml` has errors, e.g. a template that does not exist, an `image_id`
  that is not in `images`, or a duplicated `id`. All errors are reported at once before downloading images.
- Quote MAC addresses used as `id` and values of `sha256` in `config.yml`. YAML reads a value of only digits
  such as `52:54:00:30:00:00` as a number.
- Only `casper/vmlinuz` and `casper/initrd` are extracted from images. Files that older versions extracted
  are reported at startup and can be removed (see "Removing files extracted by older versions" in README.md).
- The filter `pretty` is deprecated. Use `to_yaml` in custom templates (see "Writing values in custom templates" in README.md).

### Added
- `custom_imgargs` of menus to change the kernel arguments of each menu.
- `extract` of images to choose the files extracted from each image.
- `username`, `password`, `authorized-keys` and `allow-pw` in `args` of the built-in templates.
- The filter `to_yaml` for templates.
- An empty `vendor-data` for each autoinstall, so that cloud-init does not retry it.

### Changed
- The menu of a MAC address uses the MAC of the network interface that booted (`${netX/mac}`) instead of the first one,
  and passes `BOOTIF` so that the installer uses that interface.
- MAC addresses used as `id` are changed to lower case, because iPXE requests them in lower case.
- Autoinstall configs and `boot.ipxe` are generated before downloading images, so that errors are reported first.
- Files are extracted only when the image or `extract` was changed, instead of at every start.
- The base image is `alpine:3.24` (it was `alpine:3.14`, which is end of life).
- Actions in the workflow are updated to their current major versions.

### Fixed
- Boot menu: "Configure settings", returning to the menu from the shell, the timeout after the shell, and Esc.
- Downloads: a partial download is no longer used as a complete image, a stalled download times out,
  a new download is checked with `sha256`, and the real error is reported.
- `docker stop` stops cleanly, also while images are being downloaded or extracted.
- Values in `network` and other `args` of the built-in templates are quoted when needed.
- Checking `sha256` no longer reads the whole image into memory.
- Output of the entrypoint appears in `docker logs` while the container is running.
- README: the volume to mount, and outdated instructions to prepare images and autoinstall configs by hand.

## v0.4.11
- The last release before this changelog was started.
