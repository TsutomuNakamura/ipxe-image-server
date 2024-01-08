FROM alpine:3.14

COPY default.conf /etc/nginx/http.d/default.conf
COPY entrypoint.py /entrypoint.py
COPY config.yml /config.yml
COPY boot.ipxe.j2 /boot.ipxe.j2
COPY templates /templates

RUN apk update && \
    apk upgrade && \
    apk add nginx python3 py3-pip xorriso && \
    pip3 install PyYAML progressbar jinja2 && \
    rm -rf /var/cache/apk/* && \
    chmod +x /entrypoint.py

ENTRYPOINT ["/entrypoint.py"]
