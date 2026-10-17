FROM alpine:3.24

COPY default.conf /etc/nginx/http.d/default.conf
COPY entrypoint.py /entrypoint.py
COPY config.yml /config.yml
COPY boot.ipxe.j2 /boot.ipxe.j2
COPY templates /templates

RUN apk update && \
    apk upgrade && \
    apk add nginx python3 py3-yaml py3-jinja2 xorriso && \
    rm -rf /var/cache/apk/* && \
    chmod +x /entrypoint.py

ENTRYPOINT ["/entrypoint.py"]
