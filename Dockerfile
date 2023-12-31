FROM alpine:3.14


RUN apk update && \
    apk upgrade && \
    apk add nginx python3 && \
    rm -rf /var/cache/apk/*

COPY ipxe_image_server.conf /etc/nginx/http.d/default.conf

ENTRYPOINT ["/usr/sbin/nginx", "-g", "daemon off;"]

