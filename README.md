# ipxe-image-server
This is a server to provide images of OS to boot from PXE or iPXE.

## Run the container
```
docker run --rm --volume "${PWD}/volumes:/var/www/os" -ti tsutomu/ipxe-image-server
```

## Volumes
This container requires locations to store iso files.
I recommend you to attach volumes to store them.

## Locations
This container will publish images by using http protocol with locations below.



