# ipxe-image-server
This is a server to provide images of OS to boot from PXE or iPXE.

## Run the container
```
docker run --rm --volume "${PWD}/os/images:/var/www/os/images" -ti tsutomu/ipxe-image-server
```

## Building the image

```
docker build -t tsutomu/ipxe-image-server .
```

# Prepare
## Volumes
This container will download large iso files for the first time.
I recommend you to mount volumes to store and persist them.
Previous example is using `${PWD}/os/images` as a volume.

## HTTP endpoint
ipxe-image-server will run a HTTP server and publish an endpoint `/os` by default.

## Images
Images in `images` of `config.yml` are downloaded to `/var/www/os/images/` when the container starts, unless they already exist.
Then only the files that the iPXE script loads are extracted from each image to `/var/www/os/images/<id of the image>/`.
By default they are `casper/vmlinuz` and `casper/initrd`, because the installer gets everything else from the ISO itself.
You can change them with `extract` if your `boot.ipxe.j2` needs other files.

```yaml
images:
  ubuntu-24.04-live-server-amd64:
    url: "https://releases.ubuntu.com/noble/ubuntu-24.04-live-server-amd64.iso"
    sha256: "8762f7e74e4d64d72fceb5f70682e6b069932deedb4949c6975d0f0fe0a91be3"  # Optional. Quote it.
    extract: ["casper/vmlinuz", "casper/initrd"]                                # Optional. This is the default.
```

The files are extracted again only when the image or `extract` was changed.

### Removing files extracted by older versions
Older versions extracted the whole `casper/` of each image, which takes several GiB.
The container warns about them at startup, but does not delete them.
If you use the default `extract`, you can remove them like below in the directory of the images (e.g. `os/images`).

```bash
cd os/images
for d in */casper; do
  sudo chmod u+w "$d"
  sudo find "$d" -type f ! -name vmlinuz ! -name initrd -delete
done
```

## Auto install scripts
Auto install scripts (cloud-init `user-data`) are generated from `autoinstalls` in `config.yml` when the container starts.
Each of them is written to `/var/www/os/autoinstall/<id>/` with `meta-data` and `vendor-data`.
Use a MAC address as `id` for the menu "with autoinstaller (MAC: ...)", and quote it. It is changed to lower case.

```yaml
autoinstalls:
  - id: "52:54:ff:00:00:01"
    template: autoinstall_by_mac.yml.j2
    args:
      hostname: ubuntu-server
      authorized-keys:
        - "ssh-ed25519 AAAA... user@example.com"
```

### Users and SSH
The built-in templates `common.yml.j2` and `autoinstall_by_mac.yml.j2` accept the args below.

| Arg               | Default            | Description |
|-------------------|--------------------|-------------|
| `hostname`        | `default-server`   | Required in `autoinstall_by_mac.yml.j2`. |
| `username`        | `me`               | The user that will be created. |
| `password`        | Hash of `p@ssw0rd` | A password hash of the user, used for the console and sudo. |
| `authorized-keys` | none               | Public keys that can log in over SSH. |
| `allow-pw`        | `false`            | Set `true` to allow password login over SSH. |

Only public keys can log in over SSH by default.
If you want to allow password login over SSH, set your own password hash with `allow-pw: true`.

```bash
openssl passwd -6        # or: mkpasswd -m sha-512
```

```yaml
    args:
      hostname: ubuntu-server
      password: "$6$..."
      allow-pw: true
```

The container refuses to start if password login over SSH is enabled with the default password `p@ssw0rd`.
This check is also applied to custom templates.
Note that `user-data` is served over HTTP without authentication, so anyone in the network can read the password hash.

### Writing values in custom templates
Use the filter `to_yaml` to write values of `args` in your templates.
It quotes values when needed, so they are read by the installer as they are written in `config.yml`.

```
  network:
{{ args["network"] | to_yaml(indent=4) }}
```

The filter `pretty` is deprecated, because it does not quote values.
For example, a MAC address of only digits like `52:54:00:12:34:56` is read as a number, and a value that contains ` #` is cut there.
It is kept for existing templates. When you replace it with `to_yaml`, check that values in `config.yml` are written with their real types.
For example, write `link-local: []`, not `link-local: "[]"`, because `to_yaml` writes the latter as a string.

## Configuration of installations
config.yml is used to configure the installation.
When the container starts, entrypoint.py will read this file and create a boot.ipxe.
boot.ipxe is a script which OS can be installed or provide any options when installing OS.

If you write `custom_imgargs` of a menu, keep `BOOTIF=01-${netX/mac:hexhyp}` in it like the default.
It makes the installer use the network interface that booted, on a machine that has more than one.

## Requirements of clients
* RAM: about 16 GiB for Ubuntu Server. The installer downloads the whole ISO into memory (`url=`).
  With less memory, cloud-init can be killed and the installer falls back to an interactive installation.
* UEFI Secure Boot must be disabled, because `ipxe.efi` of `ipxe-server-core` is not signed.

# Testing

## Run the containers
You have to launch this container and DHCP server container.
I recommend you to use [TsutomuNakamura/ipxe-boot](https://github.com/TsutomuNakamura/ipxe-boot).

```bash
git clone https://github.com/TsutomuNakamura/ipxe-boot
# Prepare resources. Please refer to the README.md of ipxe-boot.
docker-compose up
```

# Development

## Build and run the container
You can build and run the container on your local environment.

```bash
docker build -t test-ipxe-image-server .
docker run --rm \
    --volume "./os:/var/www/os" \
    --name test-ipxe-image-server \
    --entrypoint /bin/sh \
    -ti test-ipxe-image-server

./entrypoint.py
```

