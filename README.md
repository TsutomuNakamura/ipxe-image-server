# ipxe-image-server
This is a server to provide images of OS to boot from PXE or iPXE.

## Run the container
```
docker run --rm --volume "${PWD}/volumes:/var/www/os" -ti tsutomu/ipxe-image-server
```

## Volumes
This container requires locations to store iso files.
I recommend you to attach volumes to store them.

## Location
ipxe-image-server will run a http server and publish a location `/os` by default.
You can put any resources in the location.

## Boot script
For example, you can create a script `boot.ipxe` that provide `ubuntu-22.04` like below if you will use [TsutomuNakamura/ipxe-server-core](https://github.com/TsutomuNakamura/ipxe-server-core) as a iPXE server.

```
mkdir -p os/images/ os/autoinstall os/config
```

* ${PWD}/os/config/boot.ipxe
```
#!ipxe
set server_ip ${next-server}
set root_path /pxeboot
set mac_addr ${net0/mac}
menu Select an OS to boot
item --gap --           -------------------- Choose installations --------------------
item ubuntu-22.04.3-live-server-amd64         Install Ubuntu 22.04 LTS (MAC: ${mac_addr})
item ubuntu-22.04.3-live-server-amd64-common  Install Ubuntu 22.04 LTS
item --gap --           ---------------------- Advanced options ----------------------
item --key c config     Configure settings
item shell              Drop to iPXE shell
item reboot             Reboot Computer
choose --default exit --timeout 180000 option && goto ${option}

:ubuntu-22.04.3-live-server-amd64
set os_root os/images/ubuntu-22.04.3-live-server-amd64
kernel http://${server_ip}/${os_root}/casper/vmlinuz
initrd http://${server_ip}/${os_root}/casper/initrd
imgargs vmlinuz initrd=initrd autoinstall ip=dhcp url=http://${server_ip}/os/images/ubuntu-22.04.3-live-server-amd64.iso ds=nocloud-net;s=http://${server_ip}/os/autoinstall/${mac_addr}/ ---
boot

:ubuntu-22.04.3-live-server-amd64-common
set os_root os/images/ubuntu-22.04.3-live-server-amd64
kernel http://${server_ip}/${os_root}/casper/vmlinuz
initrd http://${server_ip}/${os_root}/casper/initrd
imgargs vmlinuz initrd=initrd autoinstall ip=dhcp url=http://${server_ip}/os/images/ubuntu-22.04.3-live-server-amd64.iso ds=nocloud-net;s=http://${server_ip}/os/autoinstall/common/ ---
boot

:exit
exit

:cancel
echo You cancelled the menu, dropping you to a shell

:shell
echo Type 'exit' to get the back to the menu
shell
set menu-timeout 0
goto start

:reboot
reboot
```

## Images
Preparing `ubuntu-22.04.3-live-server-amd64.iso` 

```
wget -O os/images/ubuntu-22.04.3-live-server-amd64.iso https://releases.ubuntu.com/jammy/ubuntu-22.04.3-live-server-amd64.iso
sudo mount -o loop os/images/ubuntu-22.04.3-live-server-amd64.iso /mnt
mkdir -p os/images/ubuntu-22.04.3-live-server-amd64
rsync -avz /mnt/casper/* os/images/ubuntu-22.04.3-live-server-amd64/casper/
sudo umount /mnt
```

## Auto install scripts

```
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
## Testing

```bash
docker build -t test-ipxe-image-server .
docker run --rm \
    --volume "./os:/var/www/os" \
    --name test-ipxe-image-server \
    --entrypoint /bin/sh \
    -ti test-ipxe-image-server

./entrypoint.py
```

