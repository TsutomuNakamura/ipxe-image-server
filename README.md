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
Preparing `ubuntu-22.04.3-live-server-amd64.iso` for example.

```
wget -O os/images/ubuntu-22.04.3-live-server-amd64.iso https://releases.ubuntu.com/jammy/ubuntu-22.04.3-live-server-amd64.iso
sudo mount -o loop os/images/ubuntu-22.04.3-live-server-amd64.iso /mnt
mkdir -p os/images/ubuntu-22.04.3-live-server-amd64
rsync -avz /mnt/casper/* os/images/ubuntu-22.04.3-live-server-amd64/casper/
sudo umount /mnt
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

## Configuration of installations
config.yml is used to configure the installation.
When the container starts, entrypoint.py will read this file and create a boot.ipxe.
boot.ipxe is a script which OS can be installed or provide any options when installing OS.

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

