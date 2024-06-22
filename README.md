# ipxe-image-server
This is a server to provide images of OS to boot from PXE or iPXE.

## Run the container
```
docker run --rm --volume "${PWD}/os/images:/var/www/os" -ti tsutomu/ipxe-image-server
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
You can prepare auto install scripts for each MAC address.

```bash
mkdir -p /var/www/os/autoinstall/52:54:ff:00:00:01
cat << 'EOF' > /var/www/os/autoinstall/52:54:ff:00:00:01/user-data
#cloud-config
autoinstall:
  version: 1
  identity:
    hostname: ubuntu-server
    username: ubuntu
    # p@ssw0rd
    password: "$6$xyz$rfUoxhnScmjOykLAVIhgfxmKgIWmTirRSrIZ9j5EJ1Vf765rQS.dCbXjXBx4PuhbcNNrXx2XpwUywQ96C7EJB/"
  ssh:
    install-server: yes
EOF
touch /var/www/os/autoinstall/52:54:ff:00:00:01/meta-data

mkdir -p /var/www/os/autoinstall/common
cat << 'EOF' > /var/www/os/autoinstall/common/user-data
#cloud-config
autoinstall:
  version: 1
  identity:
    hostname: common
    username: ubuntu
    # p@ssw0rd
    password: "$6$xyz$rfUoxhnScmjOykLAVIhgfxmKgIWmTirRSrIZ9j5EJ1Vf765rQS.dCbXjXBx4PuhbcNNrXx2XpwUywQ96C7EJB/"
  ssh:
    install-server: yes
EOF
touch /var/www/os/autoinstall/common/meta-data
```

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

