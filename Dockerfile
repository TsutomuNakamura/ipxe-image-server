FROM alpine:3.14

COPY ipxe_image_server.conf /etc/nginx/http.d/ipxe_image_server.conf

RUN apk update && \
    apk upgrade && \
    apk add nginx python3 && \
    rm -rf /var/cache/apk/* && \

ENTRYPOINT ["/usr/sbin/nginx", "-g", "daemon off;"]
